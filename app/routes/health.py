from datetime import datetime, timezone
from flask import Blueprint, jsonify, current_app

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint to verify server status and operational readiness."""
    return jsonify(
        {
            "status": "healthy",
            "service": "Smart Multipurpose Emergency Drone Delivery System",
            "version": "1.0.0-phase1",
            "environment": current_app.config.get("ENV", "development"),
            "simulation_mode": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ), 200
