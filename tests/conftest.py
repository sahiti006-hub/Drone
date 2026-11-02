import pytest
from app import create_app
from app.extensions import db


@pytest.fixture(scope="session")
def app():
    """Create and configure a Flask application instance for automated testing."""
    app_instance = create_app("testing")
    with app_instance.app_context():
        yield app_instance


@pytest.fixture(scope="function", autouse=True)
def clean_db(app):
    """Ensure each test runs with a clean, isolated database and fresh session."""
    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="function")
def client(app):
    """Provide a test client for executing HTTP requests against endpoints."""
    return app.test_client()


@pytest.fixture(scope="function")
def runner(app):
    """Provide a test CLI runner for invoking Click / Flask CLI commands."""
    return app.test_cli_runner()
