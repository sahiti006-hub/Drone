import os
from flask import Flask, redirect, url_for
from app.config import config_by_name
from app.extensions import db, migrate, csrf


class VercelServerlessMiddleware:
    """WSGI middleware ensuring correct PATH_INFO under Vercel serverless rewrites and proxies."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        matched_path = environ.get("HTTP_X_MATCHED_PATH")
        request_uri = environ.get("REQUEST_URI", "")
        path_info = environ.get("PATH_INFO", "")

        # If PATH_INFO is the script name (/api/index.py, /api/index, /wsgi.py, etc.)
        # restore the original requested path from x-matched-path or request_uri
        if path_info in ("/api/index.py", "/api/index", "/api", "/wsgi.py", "/wsgi") or path_info.startswith("/api/index.py/"):
            if matched_path and not matched_path.startswith("/api/index") and not matched_path.startswith("/wsgi"):
                environ["PATH_INFO"] = matched_path.split("?")[0]
            elif request_uri and not request_uri.startswith("/api/index") and not request_uri.startswith("/wsgi"):
                environ["PATH_INFO"] = request_uri.split("?")[0]
            else:
                environ["PATH_INFO"] = "/"

        # Ensure trailing query string is stripped from PATH_INFO
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
            "debug_headers": {k: v for k, v in request.headers.items()},
            "debug_environ": {k: str(v) for k, v in request.environ.items() if k.startswith(("HTTP_", "PATH_", "REQUEST_", "RAW_", "VERCEL_"))},
        }, 200

    @flask_app.route("/api/debug-vercel", methods=["GET"])
    @flask_app.route("/debug-vercel", methods=["GET"])
    def debug_vercel():
        from flask import request, jsonify
        return jsonify({
            "path": request.path,
            "url": request.url,
            "query_string": request.query_string.decode("utf-8", errors="ignore"),
            "environ": {
                k: str(v) for k, v in request.environ.items()
                if k.startswith(("HTTP_", "PATH_", "REQUEST_", "RAW_", "VERCEL_", "SCRIPT_"))
            }
        }), 200

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

    # Auto-initialize database schema & required demo accounts on startup (production & development)
    if config_name != "testing":
        try:
            from sqlalchemy import inspect
            with flask_app.app_context():
                inspector = inspect(db.engine)
                existing_tables = inspector.get_table_names()
                if "users" not in existing_tables:
                    flask_app.logger.info("Initializing database schema on startup...")
                    db.create_all()
                    try:
                        from flask_migrate import stamp
                        stamp(revision="head")
                    except Exception:
                        pass

                # Ensure baseline demonstration accounts are provisioned if database is fresh
                from app.models.user import User, UserRole
                initial_users = [
                    ("Dr. Elena Rostova (Admin)", "admin@emergencydrone.org", os.getenv("ADMIN_INITIAL_PASSWORD", "AdminSecurePassword123!"), UserRole.ADMIN.value),
                    ("Marcus Vance (Fleet Operator)", "operator@emergencydrone.org", os.getenv("OPERATOR_INITIAL_PASSWORD", "OperatorSecurePassword123!"), UserRole.OPERATOR.value),
                    ("Dr. Sarah Lin (City Hospital Requester)", "requester@hospital.org", os.getenv("REQUESTER_INITIAL_PASSWORD", "RequesterSecurePassword123!"), UserRole.REQUESTER.value),
                ]
                for full_name, email, pwd, role in initial_users:
                    if not User.query.filter_by(email=email).first():
                        db.session.add(User(full_name=full_name, email=email, password=pwd, role=role))
                db.session.commit()
        except Exception as startup_err:
            flask_app.logger.warning(f"Database startup verification deferred: {startup_err}")

    return flask_app
