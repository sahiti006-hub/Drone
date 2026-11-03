"""Routes for operational monitoring, performance analytics, and CSV exports."""

from datetime import datetime
from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models.delivery_request import EmergencyType, RequestPriority, RequestStatus
from app.models.user import UserRole
from app.extensions import csrf
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService, login_required, role_required

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@analytics_bp.route("")
@analytics_bp.route("/")
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def index():
    """Route optimization and algorithmic benchmarking analytics dashboard."""
    user = AuthService.get_current_user()
    metrics = AnalyticsService.get_dashboard_metrics(user)
    route_analytics = AnalyticsService.get_route_analytics_comparison()
    from app.services.prediction_service import FlightPredictionService
    ml_report = FlightPredictionService.get_evaluation_report()

    return render_template(
        "analytics/overview.html",
        user=user,
        metrics=metrics,
        analytics=route_analytics,
        ml_report=ml_report,
    )


@analytics_bp.route("/deliveries")
@login_required
def delivery_monitor():
    """Role-aware delivery monitoring console with filtering and multi-column triage sorting."""
    user = AuthService.get_current_user()

    status_filter = request.args.get("status", "ALL")
    priority_filter = request.args.get("priority", "ALL")
    emergency_type_filter = request.args.get("emergency_type", "ALL")
    search_query = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "created_desc")

    deliveries = AnalyticsService.get_delivery_monitoring_data(
        user=user,
        status_filter=status_filter,
        priority_filter=priority_filter,
        emergency_type_filter=emergency_type_filter,
        search_query=search_query,
        sort_by=sort_by,
    )

    metrics = AnalyticsService.get_dashboard_metrics(user)

    return render_template(
        "analytics/delivery_monitor.html",
        user=user,
        deliveries=deliveries,
        metrics=metrics,
        filters={
            "status": status_filter,
            "priority": priority_filter,
            "emergency_type": emergency_type_filter,
            "search": search_query,
            "sort_by": sort_by,
        },
        emergency_types=[e.value for e in EmergencyType],
        priorities=[p.value for p in RequestPriority],
        statuses=[s.value for s in RequestStatus],
    )


@analytics_bp.route("/export/deliveries.csv")
@login_required
def export_deliveries_csv():
    """Export delivery records to CSV with role-scoped authorization and sanitization."""
    user = AuthService.get_current_user()

    filters = {
        "status": request.args.get("status", "ALL"),
        "priority": request.args.get("priority", "ALL"),
        "emergency_type": request.args.get("emergency_type", "ALL"),
        "search": request.args.get("search", ""),
        "sort_by": request.args.get("sort_by", "created_desc"),
    }

    csv_data = AnalyticsService.export_deliveries_csv(user=user, filters=filters)

    filename = f"emergency_drone_deliveries_{user.role.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@analytics_bp.route("/api/summary", methods=["GET"])
@login_required
def api_summary():
    """JSON API returning high-level operational statistics and route performance data."""
    user = AuthService.get_current_user()
    metrics = AnalyticsService.get_dashboard_metrics(user)
    route_analytics = AnalyticsService.get_route_analytics_comparison()

    return jsonify({
        "success": True,
        "metrics": metrics,
        "route_analytics": route_analytics,
    }), 200


@analytics_bp.route("/api/ml-model/evaluation", methods=["GET"])
@login_required
def api_ml_evaluation():
    """JSON API returning model validation metrics (MAE, RMSE, R2) vs analytical baseline."""
    from app.services.prediction_service import FlightPredictionService
    report = FlightPredictionService.get_evaluation_report()
    return jsonify({
        "success": True,
        "evaluation_report": report,
    }), 200


@analytics_bp.route("/api/ml-model/predict", methods=["POST"])
@csrf.exempt
@login_required
def api_ml_predict():
    """JSON API generating advisory flight duration and energy predictions alongside baseline physics."""
    from app.services.prediction_service import FlightPredictionService
    data = request.get_json(silent=True) or {}

    try:
        distance_km = float(data.get("distance_km", 10.0))
        payload_weight_kg = float(data.get("payload_weight_kg", 2.0))
        wind_speed_mps = float(data.get("wind_speed_mps", 4.0))
        cruise_speed_kmh = float(data.get("cruise_speed_kmh", 60.0))

        if distance_km <= 0:
            return jsonify({"success": False, "error": "distance_km must be positive"}), 400
        if payload_weight_kg < 0:
            return jsonify({"success": False, "error": "payload_weight_kg cannot be negative"}), 400
        if wind_speed_mps < 0:
            return jsonify({"success": False, "error": "wind_speed_mps cannot be negative"}), 400
        if cruise_speed_kmh <= 0:
            return jsonify({"success": False, "error": "cruise_speed_kmh must be positive"}), 400

        prediction = FlightPredictionService.predict_flight(
            distance_km=distance_km,
            payload_weight_kg=payload_weight_kg,
            wind_speed_mps=wind_speed_mps,
            cruise_speed_kmh=cruise_speed_kmh,
        )

        return jsonify({
            "success": True,
            "prediction": prediction.to_dict(),
        }), 200

    except (ValueError, TypeError) as e:
        return jsonify({"success": False, "error": str(e)}), 400

