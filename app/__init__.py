import os
from flask import Flask, redirect, url_for
from app.config import config_by_name
from app.extensions import db, migrate, csrf


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

    # Apply ProxyFix when running behind a reverse proxy (e.g., Nginx, Traefik, AWS ALB)
    if flask_app.config.get("USE_PROXY_FIX"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        flask_app.wsgi_app = ProxyFix(
            flask_app.wsgi_app,
            x_for=flask_app.config.get("PROXY_FIX_FOR", 1),
            x_proto=flask_app.config.get("PROXY_FIX_PROTO", 1),
            x_host=flask_app.config.get("PROXY_FIX_HOST", 1),
            x_prefix=flask_app.config.get("PROXY_FIX_PREFIX", 1),
        )

    # Initialize extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    csrf.init_app(flask_app)

    # Import models so SQLAlchemy and Alembic register all table metadata
    import app.models  # noqa: F401

    # Register blueprints
    from app.routes.health import health_bp
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.delivery_routes import delivery_bp
    from app.routes.drone_routes import drone_bp
    from app.routes.simulation_routes import simulation_bp
    from app.routes.analytics_routes import analytics_bp

    # Exempt health API from CSRF since it's a read-only telemetry API
    csrf.exempt(health_bp)

    flask_app.register_blueprint(health_bp, url_prefix="/api")
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(dashboard_bp)
    flask_app.register_blueprint(delivery_bp)
    flask_app.register_blueprint(drone_bp)
    flask_app.register_blueprint(simulation_bp)
    flask_app.register_blueprint(analytics_bp)

    # Root route: if browser request direct to dashboard/login, else API JSON metadata
    @flask_app.route("/", methods=["GET"])
    def root():
        from flask import request
        if "text/html" in request.headers.get("Accept", ""):
            from app.services.auth_service import AuthService
            user = AuthService.get_current_user()
            if user:
                return redirect(url_for("dashboard.index"))
            return redirect(url_for("auth.login"))

        return {
            "message": "Welcome to the Smart Emergency Drone Delivery System API",
            "documentation": "/api/health",
            "dashboard": "/dashboard",
            "login": "/login",
            "environment": flask_app.config["ENV"],
            "database_configured": bool(flask_app.config.get("SQLALCHEMY_DATABASE_URI")),
        }, 200

    # Security Headers Hook
    @flask_app.after_request
    def set_security_headers(response):
        """Inject strict defensive HTTP security headers into every response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://tile.openstreetmap.org; "
            "connect-src 'self'; "
            "font-src 'self';"
        )
        return response

    # Custom Error Handlers with JSON/HTML negotiation
    @flask_app.errorhandler(400)
    def bad_request_error(error):
        from flask import render_template, request, jsonify
        if request.path.startswith("/api") or "/api" in request.path or request.is_json:
            return jsonify({
                "success": False,
                "error": getattr(error, "description", "Bad Request"),
                "status": 400,
            }), 400
        return render_template("errors/400.html" if os.path.exists(flask_app.template_folder + "/errors/400.html") else "errors/404.html", error=error), 400

    @flask_app.errorhandler(403)
    def forbidden_error(error):
        from flask import render_template, request, jsonify
        if request.path.startswith("/api") or "/api" in request.path or request.is_json:
            return jsonify({
                "success": False,
                "error": getattr(error, "description", "Forbidden: Access Denied"),
                "status": 403,
            }), 403
        return render_template("errors/403.html", error=error), 403

    @flask_app.errorhandler(404)
    def not_found_error(error):
        from flask import render_template, request, jsonify
        if request.path.startswith("/api") or "/api" in request.path or request.is_json:
            return jsonify({
                "success": False,
                "error": getattr(error, "description", "Resource Not Found"),
                "status": 404,
            }), 404
        return render_template("errors/404.html", error=error), 404

    @flask_app.errorhandler(500)
    def internal_error(error):
        from flask import render_template, request, jsonify
        db.session.rollback()
        if request.path.startswith("/api") or "/api" in request.path or request.is_json:
            return jsonify({
                "success": False,
                "error": "Internal Server Error: Unexpected failure occurred.",
                "status": 500,
            }), 500
        return render_template("errors/500.html", error=error), 500

    return flask_app
