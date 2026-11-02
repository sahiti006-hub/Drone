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

    return render_template(
        "analytics/overview.html",
        user=user,
        metrics=metrics,
        analytics=route_analytics,
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
