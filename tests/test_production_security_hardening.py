"""Comprehensive tests for Phase 32 Production Security and Database Hardening.

Verifies:
1. Debug endpoints are unavailable (404) and root API does not disclose environment/headers.
2. Public /api/health returns minimal status without leaking database details.
3. Administrative database diagnostics endpoint (/api/health/db) requires admin authorization.
4. Account provisioning fails safely when strong passwords are missing.
5. Provisioning is strictly idempotent: existing user passwords are not overwritten without --rotate.
6. Production configuration rejects insecure SECRET_KEY, unallowed SQLite, and missing DATABASE_URL.
7. Flask-Migrate / Alembic migrations execute cleanly on a fresh database and upgrade without data loss.
"""

import os
import pytest
from pathlib import Path
from flask import session
from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.config import ProductionConfig, validate_production_environment
from scripts.seed_production_users import provision_users, validate_password_strength, DEFAULT_ACCOUNTS


def test_debug_endpoints_unavailable(client):
    """Verify that debug endpoints are removed and return 404."""
    res_vercel = client.get("/debug-vercel")
    assert res_vercel.status_code == 404

    res_api_vercel = client.get("/api/debug-vercel")
    assert res_api_vercel.status_code == 404


def test_root_endpoint_no_sensitive_disclosure(client):
    """Verify that the root endpoint does not disclose headers, environ, or database URLs."""
    res = client.get("/", headers={"Authorization": "Bearer sensitive-token-123", "Cookie": "session=sensitive-cookie"})
    assert res.status_code == 200
    data = res.get_json()

    assert "message" in data
    assert "documentation" in data
    # Sensitive information must never be exposed
    assert "debug_headers" not in data
    assert "debug_environ" not in data
    assert "environment" not in data
    assert "database_configured" not in data
    assert "SQLALCHEMY_DATABASE_URI" not in data
    assert "sensitive-token-123" not in str(data)
    assert "sensitive-cookie" not in str(data)


def test_public_health_does_not_disclose_database_details(client):
    """Verify public /api/health returns only minimal service status."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()

    assert data["status"] == "healthy"
    assert "service" in data
    assert "version" in data
    assert "timestamp" in data

    # Must NOT disclose database internals
    assert "database" not in data
    assert "host" not in data
    assert "tables" not in data
    assert "user_count" not in data
    assert "engine_dialect" not in data
    assert "error" not in data


def test_admin_diagnostics_unauthorized_access(client):
    """Verify unauthenticated access to /api/health/db is rejected with 401."""
    res = client.get("/api/health/db")
    assert res.status_code == 401
    data = res.get_json()
    assert data["success"] is False
    assert "Authentication required" in data["error"]


def test_admin_diagnostics_forbidden_for_non_admins(client):
    """Verify non-admin users (Requester / Operator) are rejected with 403."""
    user = User(
        full_name="Hospital Nurse",
        email="nurse@hospital.org",
        password="ValidNursePassword123!",
        role=UserRole.REQUESTER.value,
    )
    db.session.add(user)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = user.id
        sess["role"] = user.role

    res = client.get("/api/health/db")
    assert res.status_code == 403
    data = res.get_json()
    assert data["success"] is False
    assert "Administrator privileges required" in data["error"]


def test_admin_diagnostics_success_for_admin(client):
    """Verify authenticated administrators can access safe database diagnostics."""
    admin = User(
        full_name="Chief Admin",
        email="chiefadmin@emergencydrone.org",
        password="ChiefAdminPassword123!",
        role=UserRole.ADMIN.value,
    )
    db.session.add(admin)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = admin.id
        sess["role"] = admin.role

    res = client.get("/api/health/db")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "diagnostics" in data
    diag = data["diagnostics"]
    assert diag["connected"] is True
    assert diag["engine_dialect"] == "sqlite"
    assert diag["table_count"] > 0
    assert "users" in diag["tables"]
    assert diag["user_count"] >= 1
    # Ensure no credentials or URLs are leaked
    assert "password" not in str(diag).lower()
    assert "connection_string" not in diag


def test_password_strength_validation():
    """Verify password strength validation rejects weak, short, or missing passwords."""
    # Missing / empty
    with pytest.raises(ValueError, match="missing or empty"):
        validate_password_strength("", "ADMIN_INITIAL_PASSWORD")

    # Too short (< 12 chars)
    with pytest.raises(ValueError, match="too weak"):
        validate_password_strength("Short123!", "ADMIN_INITIAL_PASSWORD")

    # Known demo password
    with pytest.raises(ValueError, match="known insecure demo password"):
        validate_password_strength("AdminSecurePassword123!", "ADMIN_INITIAL_PASSWORD")

    # Strong password passes
    validate_password_strength("MyUniqueP@ssw0rd2026!Str0ng", "ADMIN_INITIAL_PASSWORD")


def test_account_provisioning_fails_when_passwords_missing(monkeypatch, app):
    """Verify provisioning refuses to create accounts without strong environment passwords."""
    with app.app_context():
        # Ensure target test users do not exist
        for acc in DEFAULT_ACCOUNTS:
            u = User.query.filter_by(email=acc["email"]).first()
            if u:
                db.session.delete(u)
        db.session.commit()

        # Clear environment variables
        monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
        monkeypatch.delenv("OPERATOR_INITIAL_PASSWORD", raising=False)
        monkeypatch.delenv("REQUESTER_INITIAL_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="Mandatory environment variable"):
            provision_users(rotate=False, app=app)


def test_account_provisioning_idempotency_and_rotation(monkeypatch, app):
    """Verify provisioning is idempotent and only rotates passwords on explicit request."""
    with app.app_context():
        # Ensure clean state for test
        for acc in DEFAULT_ACCOUNTS:
            u = User.query.filter_by(email=acc["email"]).first()
            if u:
                db.session.delete(u)
        db.session.commit()

        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "StrongAdminPassword2026!X")
        monkeypatch.setenv("OPERATOR_INITIAL_PASSWORD", "StrongOperatorPassword2026!Y")
        monkeypatch.setenv("REQUESTER_INITIAL_PASSWORD", "StrongRequesterPassword2026!Z")

        # Provision initially
        provision_users(rotate=False, app=app)

        admin = User.query.filter_by(email="admin@emergencydrone.org").first()
        assert admin is not None
        assert admin.check_password("StrongAdminPassword2026!X")
        original_hash = admin.password_hash

        # Run again without rotate: hash must NOT change (idempotent)
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "BrandNewPassword2026!Changed")
        provision_users(rotate=False, app=app)

        db.session.refresh(admin)
        assert admin.password_hash == original_hash
        assert admin.check_password("StrongAdminPassword2026!X")

        # Now run with rotate=True: password MUST be updated
        provision_users(rotate=True, app=app)
        db.session.refresh(admin)
        assert admin.password_hash != original_hash
        assert admin.check_password("BrandNewPassword2026!Changed")


def test_production_config_rejects_insecure_secret_key(monkeypatch):
    """Verify ProductionConfig rejects empty or weak SECRET_KEY."""
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-change-in-production")
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://user:pass@remotehost:3306/db")
    with pytest.raises(ValueError, match="SECRET_KEY is missing or set to an insecure placeholder"):
        validate_production_environment(ProductionConfig)

    monkeypatch.setenv("SECRET_KEY", "short-key-123")
    with pytest.raises(ValueError, match="SECRET_KEY must be at least 32 characters long"):
        validate_production_environment(ProductionConfig)


def test_production_config_rejects_unallowed_sqlite(monkeypatch):
    """Verify ProductionConfig rejects accidental SQLite fallback when DATABASE_URL is missing."""
    monkeypatch.setenv("SECRET_KEY", "c7b508f77395b2c7e09ab43e74a62e08df079b76c703b44b82d3e0df7ac4435b")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_SQLITE_IN_PRODUCTION", raising=False)

    with pytest.raises(ValueError, match="Database configuration incomplete"):
        validate_production_environment(ProductionConfig)


def test_production_config_rejects_serverless_localhost_db(monkeypatch):
    """Verify ProductionConfig rejects localhost database in Vercel serverless."""
    monkeypatch.setenv("SECRET_KEY", "c7b508f77395b2c7e09ab43e74a62e08df079b76c703b44b82d3e0df7ac4435b")
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://drone_user:pass@127.0.0.1:3306/db")
    monkeypatch.setenv("VERCEL", "1")

    with pytest.raises(ValueError, match=r"DATABASE_URL points to localhost/127\.0\.0\.1"):
        validate_production_environment(ProductionConfig)


def test_migrations_execute_on_fresh_database(tmp_path):
    """Verify that Alembic migrations execute cleanly on a fresh database and preserve data on re-upgrade."""
    import subprocess
    import sys
    from sqlalchemy import create_engine, inspect, text

    db_file = tmp_path / "fresh_migration_test.db"
    db_uri = f"sqlite:///{db_file}"

    base_dir = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["DATABASE_URL"] = db_uri
    env["FLASK_ENV"] = "development"

    # 1. Run flask db upgrade via subprocess for true standalone execution
    cmd = [sys.executable, "-m", "flask", "db", "upgrade"]
    proc = subprocess.run(cmd, env=env, cwd=str(base_dir), capture_output=True, text=True)
    assert proc.returncode == 0, f"Initial flask db upgrade failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"

    engine = create_engine(db_uri)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "users" in tables
    assert "delivery_requests" in tables
    assert "drones" in tables
    assert "alembic_version" in tables

    # 2. Insert test data to verify data preservation
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (full_name, email, password_hash, role, is_active, created_at) "
                 "VALUES (:name, :email, :pwd, :role, 1, :created_at)"),
            {"name": "Migration Test User", "email": "migtest@example.com", "pwd": "hash", "role": "REQUESTER",
             "created_at": now_str}
        )

    # 3. Re-run flask db upgrade to test idempotency and data preservation
    proc2 = subprocess.run(cmd, env=env, cwd=str(base_dir), capture_output=True, text=True)
    assert proc2.returncode == 0, f"Second flask db upgrade failed:\nSTDOUT: {proc2.stdout}\nSTDERR: {proc2.stderr}"

    with engine.connect() as conn:
        result = conn.execute(text("SELECT email FROM users WHERE email = 'migtest@example.com'")).scalar()
        assert result == "migtest@example.com"
