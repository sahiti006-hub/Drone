import os
from flask import Flask, redirect, url_for
from app.config import config_by_name
from app.extensions import db, migrate, csrf


class VercelServerlessMiddleware:
    """WSGI middleware ensuring correct PATH_INFO under Vercel serverless rewrites and proxies."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        import urllib.parse

        # 1. Check if route was forwarded by Vercel rewrite (__route query parameter)
        query_string = environ.get("QUERY_STRING", "")
        if "__route=" in query_string:
            parsed_params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
            if "__route" in parsed_params:
                raw_route = parsed_params.pop("__route")[0]
                if not raw_route.startswith("/"):
                    raw_route = "/" + raw_route

                # Handle if raw_route embedded query parameters
                if "?" in raw_route:
                    route_path, route_qs = raw_route.split("?", 1)
                    environ["PATH_INFO"] = route_path
                    embedded = urllib.parse.parse_qs(route_qs, keep_blank_values=True)
                    for k, vals in embedded.items():
                        parsed_params.setdefault(k, []).extend(vals)
                else:
                    environ["PATH_INFO"] = raw_route

                environ["QUERY_STRING"] = urllib.parse.urlencode(parsed_params, doseq=True)

        # 2. Check for Vercel edge matched path or request URI fallback
        elif environ.get("HTTP_X_MATCHED_PATH"):
            matched_path = environ["HTTP_X_MATCHED_PATH"]
            if not matched_path.startswith("/api/index") and not matched_path.startswith("/wsgi"):
                environ["PATH_INFO"] = matched_path.split("?")[0]
        elif environ.get("REQUEST_URI"):
            request_uri = environ["REQUEST_URI"]
            if not request_uri.startswith("/api/index") and not request_uri.startswith("/wsgi"):
                environ["PATH_INFO"] = request_uri.split("?")[0]

        # 3. Clean up any trailing query strings in PATH_INFO
        if "?" in environ.get("PATH_INFO", ""):
            parts = environ["PATH_INFO"].split("?", 1)
            environ["PATH_INFO"] = parts[0]
            if not environ.get("QUERY_STRING"):
                environ["QUERY_STRING"] = parts[1]

        return self.wsgi_app(environ, start_response)


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

    # Wrap WSGI app with VercelServerlessMiddleware for serverless rewrites
    flask_app.wsgi_app = VercelServerlessMiddleware(flask_app.wsgi_app)

    # Ensure instance directory exists for local runtime databases or logs
    try:
        os.makedirs(flask_app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Load configuration
    config_class = config_by_name.get(config_name, config_by_name["default"])
    if config_name == "production" or (isinstance(config_class, type) and issubclass(config_class, config_by_name["production"])):
        from app.config import validate_production_environment
        validate_production_environment(config_class)
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
    from app.routes.booking_routes import booking_bp
    from app.routes.api_extensions import api_ext_bp

    # Exempt health and JSON search APIs from CSRF if requested as pure APIs
    csrf.exempt(health_bp)

    flask_app.register_blueprint(health_bp, url_prefix="/api")
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(dashboard_bp)
    flask_app.register_blueprint(delivery_bp)
    flask_app.register_blueprint(drone_bp)
    flask_app.register_blueprint(simulation_bp)
    flask_app.register_blueprint(analytics_bp)
    flask_app.register_blueprint(booking_bp)
    flask_app.register_blueprint(api_ext_bp)

    # Root route: if browser request direct to dashboard/login, else safe API JSON metadata
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
            "status": "online",
            "version": "1.0.0-phase32",
        }, 200

    # Register context processors to ensure current_user is unconditionally available to all templates
    @flask_app.context_processor
    def inject_template_globals():
        from app.services.auth_service import AuthService
        from flask import g
        user = getattr(g, "current_user", None) or AuthService.get_current_user()
        return {"current_user": user, "user": user}

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
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
            "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://unpkg.com; "
            "connect-src 'self' https://nominatim.openstreetmap.org; "
            "font-src 'self' https://fonts.gstatic.com;"
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
