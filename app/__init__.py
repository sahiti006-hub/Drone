import os
from flask import Flask
from app.config import config_by_name
from app.extensions import db, migrate


def create_app(config_name=None):
    """Application factory for the Flask application.

    Args:
        config_name (str, optional): Name of the configuration to load
            ('development', 'testing', 'production'). Defaults to None,
            which reads FLASK_ENV or falls back to 'development'.

    Returns:
        Flask: The configured Flask application instance.
    """
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development").lower()

    flask_app = Flask(__name__, instance_relative_config=True)

    # Ensure instance directory exists for local runtime databases or logs
    try:
        os.makedirs(flask_app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Load configuration
    config_class = config_by_name.get(config_name, config_by_name["default"])
    flask_app.config.from_object(config_class)
    flask_app.config["ENV"] = config_name

    # Initialize extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    # Import models so SQLAlchemy and Alembic register all table metadata
    import app.models  # noqa: F401

    # Register blueprints
    from app.routes.health import health_bp

    flask_app.register_blueprint(health_bp, url_prefix="/api")

    # Optional root route to guide users
    @flask_app.route("/", methods=["GET"])
    def root():
        return {
            "message": "Welcome to the Smart Emergency Drone Delivery System API",
            "documentation": "/api/health",
            "environment": flask_app.config["ENV"],
            "database_configured": bool(flask_app.config.get("SQLALCHEMY_DATABASE_URI")),
        }, 200

    return flask_app
