from datetime import datetime, timezone
from flask import Blueprint, jsonify, current_app

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Minimal public health check verifying service status and operational readiness.
    
    Returns high-level status only ('healthy' or 'degraded'). Raw database exceptions,
    connection parameters, hostnames, and internal table structures are strictly withheld.
    """
    is_healthy = True
    try:
        from app.extensions import db
        from sqlalchemy import text

        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        is_healthy = False
        current_app.logger.error(f"Public health check: database connectivity failure: {exc}", exc_info=True)

    return jsonify(
        {
            "status": "healthy" if is_healthy else "degraded",
            "service": "Smart Multipurpose Emergency Drone Delivery System",
            "version": "1.0.0-phase32",
            "environment": current_app.config.get("ENV", "development"),
            "simulation_mode": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ), (200 if is_healthy else 503)


@health_bp.route("/health/db", methods=["GET"])
def db_health_check():
    """Detailed database diagnostic endpoint restricted strictly to authenticated administrators."""
    from app.services.auth_service import AuthService
    from app.models.user import UserRole

    current_user = AuthService.get_current_user()
    if not current_user:
        return jsonify({
            "success": False,
            "error": "Authentication required to access system diagnostics."
        }), 401

    if current_user.role != UserRole.ADMIN.value:
        return jsonify({
            "success": False,
            "error": "Forbidden: Administrator privileges required."
        }), 403

    diag = {
        "connected": False,
        "engine_dialect": None,
        "database_name": None,
        "table_count": 0,
        "tables": [],
        "user_count": None,
        "status": "degraded",
    }

    try:
        from app.extensions import db
        from sqlalchemy import text, inspect
        from app.models.user import User

        engine = db.engine
        diag["engine_dialect"] = engine.dialect.name
        diag["database_name"] = engine.url.database or "in-memory"

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            diag["connected"] = True

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        diag["tables"] = tables
        diag["table_count"] = len(tables)
        if "users" in tables:
            diag["user_count"] = User.query.count()
        diag["status"] = "healthy"
    except Exception as exc:
        diag["connected"] = False
        diag["status"] = "degraded"
        current_app.logger.error(f"Admin database diagnostics error: {exc}", exc_info=True)

    return jsonify({
        "success": True,
        "diagnostics": diag,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), (200 if diag["connected"] else 503)
