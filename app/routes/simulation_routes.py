"""Routes for interactive drone delivery simulation and Leaflet telemetry visualization."""

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.extensions import db
from app.models.delivery_request import DeliveryRequest
from app.models.drone_assignment import DroneAssignment
from app.models.simulation_run import SimulationRun
from app.services.auth_service import AuthService, login_required, role_required
from app.services.simulation_service import (
    DuplicateSimulationError,
    InvalidAssignmentStateError,
    InvalidSimulationStateTransitionError,
    SimulationService,
    SimulationServiceError,
)

simulation_bp = Blueprint("simulation", __name__, url_prefix="/simulation")


def _verify_simulation_access(sim: SimulationRun, user, require_operator: bool = False):
    """Verify that user has authorization to access or mutate this simulation."""
    if require_operator and user.role not in ("ADMIN", "OPERATOR"):
        abort(403, description="Simulation controls are restricted to Operators and Administrators.")

    if user.role == "REQUESTER":
        if not sim.assignment or not sim.assignment.delivery_request:
            abort(403, description="Permission denied.")
        if sim.assignment.delivery_request.requester_id != user.id:
            abort(403, description="Access denied: You can only view simulations for your own requests.")


@simulation_bp.route("/assignment/<int:assignment_id>")
@login_required
def view_by_assignment(assignment_id: int):
    """Entry point to launch or view the simulation console for a given assignment."""
    user = AuthService.get_current_user()
    assignment = db.session.get(DroneAssignment, assignment_id)
    if not assignment:
        flash("Drone assignment not found.", "danger")
        return redirect(url_for("delivery.list_requests"))

    # Role-based access check
    if user.role == "REQUESTER" and assignment.delivery_request.requester_id != user.id:
        flash("You do not have permission to view this assignment.", "danger")
        return redirect(url_for("delivery.list_requests"))

    try:
        sim = SimulationService.get_or_create_simulation(assignment.id)
        return redirect(url_for("simulation.view_simulation", simulation_id=sim.id))
    except (InvalidAssignmentStateError, SimulationServiceError) as e:
        flash(f"Simulation could not be launched: {e}", "warning")
        return redirect(url_for("delivery.request_detail", request_id=assignment.delivery_request_id))


@simulation_bp.route("/<int:simulation_id>")
@login_required
def view_simulation(simulation_id: int):
    """Renders the interactive Leaflet map simulation cockpit."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        flash("Simulation run not found.", "danger")
        return redirect(url_for("delivery.list_requests"))

    _verify_simulation_access(sim, user, require_operator=False)

    try:
        full_state = SimulationService.get_simulation_state(sim.id)
    except SimulationServiceError as e:
        flash(f"Error loading simulation state: {e}", "danger")
        return redirect(url_for("delivery.list_requests"))

    is_controller = user.role in ("ADMIN", "OPERATOR")
    return render_template(
        "simulation/view.html",
        simulation=sim,
        full_state=full_state,
        is_controller=is_controller,
        user=user,
    )


# -------------------------------------------------------------------------
# API Endpoints for State & Controls
# -------------------------------------------------------------------------


@simulation_bp.route("/api/<int:simulation_id>/state", methods=["GET"])
@login_required
def get_state_api(simulation_id: int):
    """JSON API to retrieve full simulation telemetry and corridor data."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=False)

    try:
        data = SimulationService.get_simulation_state(sim.id)
        return jsonify({"success": True, "data": data}), 200
    except SimulationServiceError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/start", methods=["POST"])
@login_required
def start_api(simulation_id: int):
    """Transition simulation to RUNNING."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    try:
        updated = SimulationService.start_simulation(sim.id)
        return jsonify({
            "success": True,
            "status": updated.status,
            "message": "Simulation started successfully.",
        }), 200
    except (InvalidSimulationStateTransitionError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/pause", methods=["POST"])
@login_required
def pause_api(simulation_id: int):
    """Pause an active simulation."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    try:
        updated = SimulationService.pause_simulation(sim.id)
        return jsonify({
            "success": True,
            "status": updated.status,
            "message": "Simulation paused.",
        }), 200
    except (InvalidSimulationStateTransitionError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/resume", methods=["POST"])
@login_required
def resume_api(simulation_id: int):
    """Resume a paused simulation."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    try:
        updated = SimulationService.resume_simulation(sim.id)
        return jsonify({
            "success": True,
            "status": updated.status,
            "message": "Simulation resumed.",
        }), 200
    except (InvalidSimulationStateTransitionError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/cancel", methods=["POST"])
@login_required
def cancel_api(simulation_id: int):
    """Cancel and abort a simulation."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason", "Operator manual cancellation")

    try:
        updated = SimulationService.cancel_simulation(sim.id, reason=reason)
        return jsonify({
            "success": True,
            "status": updated.status,
            "message": f"Simulation cancelled: {reason}",
        }), 200
    except (InvalidSimulationStateTransitionError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/step", methods=["POST"])
@login_required
def step_api(simulation_id: int):
    """Advance simulation kinematics forward by discrete seconds."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    data = request.get_json(silent=True) or {}
    try:
        delta_sim_seconds = float(data.get("delta_sim_seconds", 1.0))
        speed_multiplier = float(data.get("speed_multiplier", 1.0))
        result = SimulationService.step_simulation(
            simulation_id=sim.id,
            delta_sim_seconds=delta_sim_seconds,
            speed_multiplier=speed_multiplier,
        )
        return jsonify({"success": True, "telemetry": result}), 200
    except (ValueError, InvalidSimulationStateTransitionError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/checkpoint", methods=["POST"])
@login_required
def checkpoint_api(simulation_id: int):
    """Sync client-calculated smooth waypoint interpolation checkpoint."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    data = request.get_json(silent=True) or {}
    try:
        progress_pct = float(data.get("progress_percent", sim.current_progress_percent))
        lat = float(data.get("latitude", sim.current_latitude or 0.0))
        lon = float(data.get("longitude", sim.current_longitude or 0.0))
        alt = float(data.get("altitude_m", sim.current_altitude_m or 50.0))
        elapsed = float(data.get("elapsed_seconds", sim.elapsed_sim_seconds))
        dist_covered = float(data.get("distance_covered_km", sim.distance_covered_km))
        dist_remaining = float(data.get("remaining_distance_km", sim.remaining_distance_km))
        battery = float(data.get("current_battery_wh", sim.current_battery_wh or 0.0))
        speed_mult = float(data.get("speed_multiplier", sim.speed_multiplier))
        extra = data.get("extra_data")

        res = SimulationService.sync_checkpoint(
            simulation_id=sim.id,
            progress_percent=progress_pct,
            latitude=lat,
            longitude=lon,
            altitude_m=alt,
            elapsed_seconds=elapsed,
            distance_covered_km=dist_covered,
            remaining_distance_km=dist_remaining,
            current_battery_wh=battery,
            speed_multiplier=speed_mult,
            extra_data=extra,
        )
        return jsonify({"success": True, "checkpoint": res}), 200
    except (ValueError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@simulation_bp.route("/api/<int:simulation_id>/reroute", methods=["POST"])
@login_required
def reroute_api(simulation_id: int):
    """Dynamically evaluate and execute in-flight route replacement."""
    user = AuthService.get_current_user()
    sim = db.session.get(SimulationRun, simulation_id)
    if not sim:
        return jsonify({"success": False, "error": "Simulation not found"}), 404

    _verify_simulation_access(sim, user, require_operator=True)

    data = request.get_json(silent=True) or {}
    try:
        from app.services.weather_service import WeatherData
        wind = float(data.get("wind_speed_mps", 4.0))
        precip = float(data.get("precipitation_mmh", 0.0))
        vis = float(data.get("visibility_km", 10.0))
        summary = str(data.get("weather_summary", "In-flight environmental update"))
        policy = str(data.get("policy", "SAFETY_MANDATED"))
        min_improvement = float(data.get("min_improvement_pct", 5.0))
        reason = str(data.get("reason", "Operator dynamic reroute request"))

        weather = WeatherData(
            wind_speed_mps=wind,
            precipitation_mmh=precip,
            visibility_km=vis,
            weather_summary=summary,
        )

        res = SimulationService.evaluate_and_reroute(
            simulation_id=sim.id,
            updated_weather=weather,
            policy_name=policy,
            min_improvement_pct=min_improvement,
            reason=reason,
        )
        return jsonify({"success": True, "reroute": res.to_dict()}), 200
    except (ValueError, SimulationServiceError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
