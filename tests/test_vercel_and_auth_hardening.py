"""Unit and integration tests for Vercel deployment compatibility and authentication hardening."""

import pytest
from flask import session
from app import create_app
from app.config import resolve_database_uri, resolve_engine_options
from app.extensions import db
from app.models.user import User, UserRole
from app.services.user_service import UserService
from unittest.mock import patch


def test_database_uri_mysql_normalization(monkeypatch):
    """Ensure standard cloud MySQL URIs (mysql://) are automatically rewritten to mysql+pymysql://."""
    monkeypatch.setenv("DATABASE_URL", "mysql://admin:secret123@db.example.com:3306/dronedb")
    normalized = resolve_database_uri()
    assert normalized == "mysql+pymysql://admin:secret123@db.example.com:3306/dronedb"


def test_database_uri_postgres_normalization(monkeypatch):
    """Ensure postgres:// is normalized to postgresql://."""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db")
    normalized = resolve_database_uri()
    assert normalized == "postgresql://user:pass@host:5432/db"


def test_database_engine_options():
    """Ensure correct engine options are generated per dialect."""
    sqlite_opts = resolve_engine_options("sqlite:///:memory:")
    assert "pool_size" not in sqlite_opts
    assert sqlite_opts["pool_pre_ping"] is True

    mysql_opts = resolve_engine_options("mysql+pymysql://user:pass@localhost/db")
    assert mysql_opts["pool_size"] == 5
    assert mysql_opts["pool_recycle"] == 280
    assert mysql_opts["pool_pre_ping"] is True


def test_health_check_endpoint(client):
    """Verify /api/health returns minimal public health status without leaking database details."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert "service" in data
    assert "version" in data
    # Public health check must NOT leak database internals
    assert "database" not in data
    assert "host" not in data
    assert "tables" not in data
    assert "user_count" not in data


def test_login_page_no_publicly_exposed_credentials(client):
    """Verify that demonstration passwords are NOT rendered publicly on the login page."""
    res = client.get("/login")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "AdminSecurePassword123!" not in html
    assert "OperatorSecurePassword123!" not in html
    assert "RequesterSecurePassword123!" not in html
    assert "demo-credentials-box" not in html


def test_login_database_error_graceful_handling(client, monkeypatch):
    """Verify that a database failure during authentication displays a clean 503 instead of 500 crash."""
    def broken_authenticate(email, password):
        raise ConnectionError("Simulated database network timeout")

    monkeypatch.setattr(UserService, "authenticate", broken_authenticate)

    res = client.post("/login", data={"email": "requester@hospital.org", "password": "AnyPassword123!"})
    assert res.status_code == 503
    html = res.get_data(as_text=True)
    assert "Authentication service is temporarily unavailable" in html


def test_successful_login_and_role_redirect(client):
    """Verify successful login redirects to the correct role dashboard."""
    # Seed a test admin
    user = User(
        full_name="Admin Test",
        email="testadmin@emergencydrone.org",
        password="TestAdminPassword123!",
        role=UserRole.ADMIN.value,
    )
    db.session.add(user)
    db.session.commit()

    res = client.post(
        "/login",
        data={"email": "testadmin@emergencydrone.org", "password": "TestAdminPassword123!"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "/dashboard" in res.headers["Location"]


def test_vercel_middleware_route_rewrites(client):
    """Verify that VercelServerlessMiddleware unpacks __route query parameters accurately."""
    # Simulation of Vercel serverless request rewritten to /api/index.py?__route=/api/health
    res = client.get("/api/index.py?__route=/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"

    # Simulation of Vercel serverless request rewritten to /api/index.py?__route=/login&next=%2Fdashboard
    res = client.get("/api/index.py?__route=/login&next=%2Fdashboard")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'name="next" value="/dashboard"' in html

