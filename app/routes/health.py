from datetime import datetime, timezone
from flask import Blueprint, jsonify, current_app

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint to verify server status, operational readiness, and database connectivity."""
    db_info = {
        "configured": bool(current_app.config.get("SQLALCHEMY_DATABASE_URI")),
        "connected": False,
        "engine_dialect": None,
        "host": None,
        "database_name": None,
        "error": None,
        "tables": [],
        "user_count": None,
    }

    try:
        from app.extensions import db
        from sqlalchemy import text, inspect
        from app.models.user import User

        engine = db.engine
        db_info["engine_dialect"] = engine.dialect.name
        db_info["host"] = engine.url.host
        db_info["database_name"] = engine.url.database

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_info["connected"] = True

        inspector = inspect(engine)
        db_info["tables"] = inspector.get_table_names()
        if "users" in db_info["tables"]:
            db_info["user_count"] = User.query.count()
    except Exception as exc:
        db_info["connected"] = False
        db_info["error"] = str(exc)
        current_app.logger.warning(f"Database health check warning: {exc}")

    is_healthy = db_info["connected"]
    return jsonify(
        {
            "status": "healthy" if is_healthy else "degraded",
            "service": "Smart Multipurpose Emergency Drone Delivery System",
            "version": "1.0.0-phase31",
            "environment": current_app.config.get("ENV", "development"),
            "simulation_mode": True,
            "database": db_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ), (200 if is_healthy else 503)


@health_bp.route("/health/db", methods=["GET"])
def db_health_check():
    """Targeted database diagnostic endpoint."""
    return health_check()
