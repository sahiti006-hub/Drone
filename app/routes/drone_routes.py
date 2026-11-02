from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models.drone import Drone, DroneStatus
from app.models.user import UserRole
from app.services.auth_service import AuthService, login_required, role_required
from app.services.drone_service import (
    DroneService,
    DroneServiceError,
    InvalidDroneTransitionError,
    DroneNotFoundError,
)

drone_bp = Blueprint("drone", __name__, url_prefix="/drones")


@drone_bp.route("", methods=["GET"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def list_drones():
    """List drone fleet inventory with filtering by status and payload capacity."""
    user = AuthService.get_current_user()

    status_filter = request.args.get("status")
    min_payload = request.args.get("min_payload")
    include_decom = request.args.get("include_decommissioned") == "1"

    drones = DroneService.get_drones(
        status=status_filter,
        min_payload=float(min_payload) if min_payload else None,
        include_decommissioned=include_decom,
    )

    return render_template(
        "drones/list.html",
        current_user=user,
        drones=drones,
        filters={
            "status": status_filter,
            "min_payload": min_payload,
            "include_decommissioned": include_decom,
        },
        statuses=[s.value for s in DroneStatus],
    )


@drone_bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def new_drone():
    """Register a new drone hardware unit in the fleet."""
    user = AuthService.get_current_user()

    if request.method == "POST":
        drone_code = request.form.get("drone_code", "").strip()
        model_name = request.form.get("model_name", "").strip()

        try:
            max_payload = float(request.form.get("maximum_payload_kg", 0))
            battery_cap = float(request.form.get("battery_capacity_wh", 0))
            current_batt = request.form.get("current_battery_wh")
            current_batt_val = float(current_batt) if current_batt else battery_cap
            cruise_speed = float(request.form.get("cruise_speed_kmh", 60.0))

            drone = DroneService.register_drone(
                drone_code=drone_code,
                model_name=model_name,
                maximum_payload_kg=max_payload,
                battery_capacity_wh=battery_cap,
                current_battery_wh=current_batt_val,
                cruise_speed_kmh=cruise_speed,
            )

            flash(f"Drone {drone.drone_code} successfully registered in inventory.", "success")
            return redirect(url_for("drone.view_detail", drone_id=drone.id))

        except (ValueError, DroneServiceError) as err:
            flash(f"Registration failed: {err}", "danger")
            return render_template(
                "drones/form.html",
                current_user=user,
                is_edit=False,
                form_data=request.form,
            ), 400

    return render_template(
        "drones/form.html",
        current_user=user,
        is_edit=False,
        form_data={},
    )


@drone_bp.route("/<int:drone_id>", methods=["GET"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def view_detail(drone_id: int):
    """View drone hardware specifications, battery status, and mission history."""
    user = AuthService.get_current_user()
    try:
        drone = DroneService.get_drone_by_id(drone_id)
    except DroneNotFoundError:
        abort(404, description=f"Drone #{drone_id} not found.")

    return render_template(
        "drones/detail.html",
        current_user=user,
        drone=drone,
        statuses=[s.value for s in DroneStatus],
    )


@drone_bp.route("/<int:drone_id>/edit", methods=["GET", "POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def edit_drone(drone_id: int):
    """Edit permitted drone specifications."""
    user = AuthService.get_current_user()
    try:
        drone = DroneService.get_drone_by_id(drone_id)
    except DroneNotFoundError:
        abort(404)

    if request.method == "POST":
        model_name = request.form.get("model_name")
        try:
            max_payload = float(request.form.get("maximum_payload_kg", drone.maximum_payload_kg))
            battery_cap = float(request.form.get("battery_capacity_wh", drone.battery_capacity_wh))
            current_batt = float(request.form.get("current_battery_wh", drone.current_battery_wh))
            cruise_speed = float(request.form.get("cruise_speed_kmh", drone.cruise_speed_kmh))

            DroneService.update_drone(
                drone_id=drone.id,
                model_name=model_name,
                maximum_payload_kg=max_payload,
                battery_capacity_wh=battery_cap,
                current_battery_wh=current_batt,
                cruise_speed_kmh=cruise_speed,
            )

            flash(f"Drone {drone.drone_code} hardware specifications updated.", "success")
            return redirect(url_for("drone.view_detail", drone_id=drone.id))

        except (ValueError, DroneServiceError) as err:
            flash(f"Update failed: {err}", "danger")
            return render_template(
                "drones/form.html",
                current_user=user,
                is_edit=True,
                drone=drone,
                form_data=request.form,
            ), 400

    return render_template(
        "drones/form.html",
        current_user=user,
        is_edit=True,
        drone=drone,
        form_data=drone.to_dict(),
    )


@drone_bp.route("/<int:drone_id>/status", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def change_status(drone_id: int):
    """Change drone status (maintenance, charging, available) subject to transition rules."""
    target_status = request.form.get("status")
    try:
        drone = DroneService.update_drone_status(drone_id, target_status)
        flash(f"Drone {drone.drone_code} status transitioned to '{drone.status}'.", "success")
    except (DroneNotFoundError, InvalidDroneTransitionError, DroneServiceError) as err:
        flash(f"Status transition failed: {err}", "danger")

    return redirect(url_for("drone.view_detail", drone_id=drone_id))


@drone_bp.route("/<int:drone_id>/decommission", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def decommission(drone_id: int):
    """Decommission drone unit safely without breaking historical delivery records."""
    try:
        drone = DroneService.decommission_drone(drone_id)
        flash(f"Drone {drone.drone_code} has been retired/decommissioned.", "warning")
    except (DroneNotFoundError, DroneServiceError) as err:
        flash(f"Decommission failed: {err}", "danger")

    return redirect(url_for("drone.view_detail", drone_id=drone_id))
