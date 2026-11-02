from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.route import Route
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun
from app.models.analysis_log import AnalysisLog
from app.services.auth_service import AuthService, login_required, role_required
from app.services.analytics_service import AnalyticsService
from app.services.assignment_service import (
    AssignmentService,
    ConflictingAssignmentError,
    InfeasibleAssignmentError,
    AssignmentServiceError,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def index():
    """Direct authenticated users to their respective role-specific dashboard."""
    user = AuthService.get_current_user()
    if user.role == UserRole.ADMIN.value:
        return redirect(url_for("dashboard.admin_dashboard"))
    elif user.role == UserRole.OPERATOR.value:
        return redirect(url_for("dashboard.operator_dashboard"))
    else:
        return redirect(url_for("dashboard.requester_dashboard"))


# ==============================================================================
# ADMIN DASHBOARD
# ==============================================================================
@dashboard_bp.route("/admin/dashboard")
@login_required
@role_required(UserRole.ADMIN)
def admin_dashboard():
    """System-wide administration, telemetry, fleet oversight, and health audit."""
    user = AuthService.get_current_user()
    metrics = AnalyticsService.get_dashboard_metrics(user)

    total_users = User.query.count()

    recent_drones = Drone.query.order_by(Drone.created_at.desc()).limit(6).all()
    recent_requests = DeliveryRequest.query.order_by(DeliveryRequest.created_at.desc()).limit(6).all()
    recent_assignments = DroneAssignment.query.order_by(DroneAssignment.assigned_at.desc()).limit(6).all()
    recent_simulations = SimulationRun.query.order_by(SimulationRun.created_at.desc()).limit(5).all()
    recent_analysis = AnalysisLog.query.order_by(AnalysisLog.created_at.desc()).limit(5).all()

    return render_template(
        "dashboard/admin_dashboard.html",
        current_user=user,
        metrics=metrics,
        stats={
            "total_drones": metrics["total_active_drones"],
            "available_drones": metrics["available_drones"],
            "in_transit_drones": metrics["in_transit_drones"],
            "charging_drones": metrics["charging_drones"],
            "maintenance_drones": metrics["maintenance_drones"],
            "total_requests": metrics["total_requests"],
            "pending_requests": metrics["pending_requests"],
            "delivered_requests": metrics["completed_deliveries"],
            "active_assignments": metrics["assigned_deliveries"],
            "total_users": total_users,
        },
        recent_drones=recent_drones,
        recent_requests=recent_requests,
        recent_assignments=recent_assignments,
        recent_simulations=recent_simulations,
        recent_analysis=recent_analysis,
    )


# ==============================================================================
# OPERATOR DASHBOARD
# ==============================================================================
@dashboard_bp.route("/operator/dashboard")
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def operator_dashboard():
    """Operational console: dispatch eligible drones, monitor missions, and simulate."""
    user = AuthService.get_current_user()
    metrics = AnalyticsService.get_dashboard_metrics(user)

    # Requests that need assignment
    pending_requests = (
        DeliveryRequest.query.filter(
            DeliveryRequest.status.in_([RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value])
        )
        .order_by(DeliveryRequest.created_at.asc())
        .all()
    )

    # Drones ready for deployment
    available_drones = Drone.query.filter_by(
        status=DroneStatus.AVAILABLE.value,
        is_decommissioned=False,
    ).all()

    # Active missions in progress
    active_assignments = (
        DroneAssignment.query.filter_by(status=AssignmentStatus.ACTIVE.value)
        .order_by(DroneAssignment.assigned_at.desc())
        .all()
    )

    # Feasible routes available for assignment
    all_routes = Route.query.filter_by(feasibility_status="FEASIBLE").all()

    # Simulation runs
    recent_simulations = SimulationRun.query.order_by(SimulationRun.created_at.desc()).limit(5).all()

    return render_template(
        "dashboard/operator_dashboard.html",
        current_user=user,
        metrics=metrics,
        pending_requests=pending_requests,
        available_drones=available_drones,
        active_assignments=active_assignments,
        available_routes=all_routes,
        recent_simulations=recent_simulations,
    )


# ==============================================================================
# REQUESTER DASHBOARD
# ==============================================================================
@dashboard_bp.route("/requester/dashboard")
@login_required
@role_required(UserRole.ADMIN, UserRole.REQUESTER)
def requester_dashboard():
    """Requester portal: submit emergency orders and track personal dispatch history."""
    user = AuthService.get_current_user()
    metrics = AnalyticsService.get_dashboard_metrics(user)

    # Query only the authenticated requester's requests
    my_requests = (
        DeliveryRequest.query.filter_by(requester_id=user.id)
        .order_by(DeliveryRequest.created_at.desc())
        .all()
    )

    total_count = metrics["total_requests"]
    in_transit_count = sum(1 for r in my_requests if r.status in {RequestStatus.ASSIGNED.value, RequestStatus.IN_TRANSIT.value})
    delivered_count = metrics["completed_deliveries"]

    return render_template(
        "dashboard/requester_dashboard.html",
        current_user=user,
        metrics=metrics,
        my_requests=my_requests,
        total_count=total_count,
        in_transit_count=in_transit_count,
        delivered_count=delivered_count,
        emergency_types=[e.value for e in EmergencyType],
        priorities=[p.value for p in RequestPriority],
    )


# ==============================================================================
# REQUEST CREATION & DETAIL (WITH IDOR PROTECTION)
# ==============================================================================
@dashboard_bp.route("/requester/requests", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.REQUESTER)
def create_delivery_request():
    """Handle emergency delivery request submission by authenticated requesters."""
    user = AuthService.get_current_user()

    emergency_type = request.form.get("emergency_type", "").strip()
    priority = request.form.get("priority", RequestPriority.HIGH.value).strip()

    try:
        pickup_lat = float(request.form.get("pickup_latitude", 0))
        pickup_lng = float(request.form.get("pickup_longitude", 0))
        dest_lat = float(request.form.get("destination_latitude", 0))
        dest_lng = float(request.form.get("destination_longitude", 0))
        payload_weight = float(request.form.get("payload_weight_kg", 0))

        req = DeliveryRequest(
            requester_id=user.id,
            emergency_type=emergency_type,
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lng,
            destination_latitude=dest_lat,
            destination_longitude=dest_lng,
            payload_weight_kg=payload_weight,
            priority=priority,
            status=RequestStatus.PENDING.value,
        )

        db.session.add(req)
        db.session.commit()
        flash(f"Emergency Delivery Request #{req.id} created successfully.", "success")
        return redirect(url_for("dashboard.requester_dashboard"))

    except ValueError as val_err:
        db.session.rollback()
        flash(f"Validation error: {val_err}", "danger")
        return redirect(url_for("dashboard.requester_dashboard"))
    except Exception as exc:
        db.session.rollback()
        flash(f"Database error while creating request: {exc}", "danger")
        return redirect(url_for("dashboard.requester_dashboard"))


@dashboard_bp.route("/requests/<int:request_id>")
@login_required
def view_request_detail(request_id: int):
    """View details of a specific delivery request.

    Enforces Insecure Direct Object Reference (IDOR) protection:
    Requesters can ONLY view their own delivery requests.
    Admins and Operators can view any request.
    """
    user = AuthService.get_current_user()
    req = db.session.get(DeliveryRequest, request_id)

    if not req:
        abort(404, description=f"Delivery request #{request_id} not found.")

    # IDOR Protection: If user is REQUESTER, prevent access to another user's request
    if user.role == UserRole.REQUESTER.value and req.requester_id != user.id:
        abort(403, description="Access Denied: You do not have permission to view another user's delivery request.")

    return render_template(
        "dashboard/request_detail.html",
        current_user=user,
        req=req,
    )


# ==============================================================================
# OPERATOR DISPATCH ACTIONS
# ==============================================================================
@dashboard_bp.route("/operator/assign", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def assign_mission():
    """Dispatch an eligible drone to a delivery request and route."""
    try:
        request_id = int(request.form.get("delivery_request_id", 0))
        drone_id = int(request.form.get("drone_id", 0))
        route_id = int(request.form.get("route_id", 0))

        assignment = AssignmentService.create_assignment(request_id, drone_id, route_id)
        flash(
            f"Successfully assigned Drone #{assignment.drone_id} to Delivery Request #{assignment.delivery_request_id}!",
            "success",
        )
    except (ConflictingAssignmentError, InfeasibleAssignmentError, AssignmentServiceError) as err:
        flash(f"Assignment failed: {err}", "danger")
    except Exception as exc:
        flash(f"Unexpected error during assignment: {exc}", "danger")

    return redirect(url_for("dashboard.operator_dashboard"))


@dashboard_bp.route("/operator/assignments/<int:assignment_id>/complete", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def complete_mission(assignment_id: int):
    """Mark an active mission as completed."""
    try:
        assignment = AssignmentService.complete_assignment(assignment_id)
        flash(f"Assignment #{assignment.id} marked as COMPLETED. Drone returned to base.", "success")
    except Exception as exc:
        flash(f"Error completing assignment: {exc}", "danger")

    return redirect(url_for("dashboard.operator_dashboard"))


@dashboard_bp.route("/operator/assignments/<int:assignment_id>/abort", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def abort_mission(assignment_id: int):
    """Abort an active mission due to hazard or operator override."""
    try:
        assignment = AssignmentService.abort_assignment(assignment_id, reason="Aborted by operator")
        flash(f"Assignment #{assignment.id} ABORTED. Drone reassigned to Available.", "warning")
    except Exception as exc:
        flash(f"Error aborting assignment: {exc}", "danger")

    return redirect(url_for("dashboard.operator_dashboard"))
