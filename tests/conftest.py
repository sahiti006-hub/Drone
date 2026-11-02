import pytest
from app import create_app
from app.extensions import db


@pytest.fixture(scope="session")
def app():
    """Create and configure a Flask application for automated tests."""
    app_instance = create_app("testing")

    with app_instance.app_context():
        # Create all tables in the in-memory SQLite test database
        db.create_all()
        yield app_instance
        # Drop all tables after testing session finishes
        db.drop_all()


@pytest.fixture(scope="function")
def client(app):
    """Provide a test client for executing HTTP requests against endpoints."""
    return app.test_client()


@pytest.fixture(scope="function")
def runner(app):
    """Provide a test CLI runner for invoking Click / Flask CLI commands."""
    return app.test_cli_runner()
