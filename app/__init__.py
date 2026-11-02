import os
from flask import Flask
from app.config import config_by_name
from app.extensions import db


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

    app = Flask(__name__)

    # Load configuration
    config_class = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_class)
    app.config["ENV"] = config_name

    # Initialize extensions
    # In testing mode or when explicitly enabled, bind the db extension
    if app.config.get("TESTING"):
        db.init_app(app)

    # Register blueprints
    from app.routes.health import health_bp

    app.register_blueprint(health_bp, url_prefix="/api")

    # Optional root route to guide users
    @app.route("/", methods=["GET"])
    def root():
        return {
            "message": "Welcome to the Smart Emergency Drone Delivery System API",
            "documentation": "/api/health",
        }, 200

    return app
