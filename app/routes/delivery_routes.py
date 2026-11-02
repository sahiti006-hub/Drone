from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.user import UserRole
from app.services.auth_service import AuthService, login_required, role_required
from app.services.delivery_service import (
    DeliveryService,
    DeliveryServiceError,
    DeliveryRequestNotFoundError,
    InvalidRequestStateError,
    DeliveryPermissionDeniedError,
)

delivery_bp = Blueprint("delivery", __name__, url_prefix="/requests")


@delivery_bp.route("", methods=["GET"])
@login_required
def list_requests():
    """List delivery requests scoped to the authenticated user's role with filter options."""
    user = AuthService.get_current_user()

    priority = request.args.get("priority")
    status = request.args.get("status")
    emergency_type = request.args.get("emergency_type")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            pass

    requests_list = DeliveryService.get_requests_for_user(
        user=user,
        priority=priority,
        status=status,
        emergency_type=emergency_type,
        start_date=start_date,
        end_date=end_date,
    )

    return render_template(
        "delivery/list.html",
        current_user=user,
        requests=requests_list,
        filters={
            "priority": priority,
            "status": status,
            "emergency_type": emergency_type,
            "start_date": start_date_str,
            "end_date": end_date_str,
        },
        emergency_types=[e.value for e in EmergencyType],
        priorities=[p.value for p in RequestPriority],
        statuses=[s.value for s in RequestStatus],
    )


@delivery_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_request():
    """Create a new emergency delivery request."""
    user = AuthService.get_current_user()

    if request.method == "POST":
        emergency_type = request.form.get("emergency_type", "").strip()
        priority = request.form.get("priority", RequestPriority.HIGH.value).strip()
        description = request.form.get("description", "").strip()

        try:
            pickup_lat = float(request.form.get("pickup_latitude", 0))
            pickup_lng = float(request.form.get("pickup_longitude", 0))
            dest_lat = float(request.form.get("destination_latitude", 0))
            dest_lng = float(request.form.get("destination_longitude", 0))
            payload_weight = float(request.form.get("payload_weight_kg", 0))

            req = DeliveryService.create_request(
                requester_id=user.id,
                emergency_type=emergency_type,
                pickup_latitude=pickup_lat,
                pickup_longitude=pickup_lng,
                destination_latitude=dest_lat,
                destination_longitude=dest_lng,
                payload_weight_kg=payload_weight,
                priority=priority,
                description=description,
            )

            flash(f"Emergency Delivery Request #{req.id} created successfully.", "success")
            return redirect(url_for("delivery.view_detail", request_id=req.id))

        except (ValueError, DeliveryServiceError) as err:
            flash(f"Validation error: {err}", "danger")
            return render_template(
                "delivery/form.html",
                current_user=user,
                is_edit=False,
                form_data=request.form,
                emergency_types=[e.value for e in EmergencyType],
                priorities=[p.value for p in RequestPriority],
            ), 400

    return render_template(
        "delivery/form.html",
        current_user=user,
        is_edit=False,
        form_data={},
        emergency_types=[e.value for e in EmergencyType],
        priorities=[p.value for p in RequestPriority],
    )


@delivery_bp.route("/<int:request_id>", methods=["GET"])
@login_required
def view_detail(request_id: int):
    """View comprehensive delivery request details with IDOR protection."""
    user = AuthService.get_current_user()
    try:
        req = DeliveryService.get_request_by_id(request_id, user=user)
    except DeliveryRequestNotFoundError:
        abort(404, description=f"Delivery request #{request_id} not found.")
    except DeliveryPermissionDeniedError:
        abort(403, description="Access Denied: You do not have permission to view another user's delivery request.")

    return render_template(
        "delivery/detail.html",
        current_user=user,
        req=req,
    )


@delivery_bp.route("/<int:request_id>/edit", methods=["GET", "POST"])
@login_required
def edit_request(request_id: int):
    """Edit permitted properties of a pending delivery request."""
    user = AuthService.get_current_user()
    try:
        req = DeliveryService.get_request_by_id(request_id, user=user)
    except DeliveryRequestNotFoundError:
        abort(404)
    except DeliveryPermissionDeniedError:
        abort(403)

    if req.status not in {RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value}:
        flash(f"Cannot edit request #{req.id}: status is already '{req.status}'.", "warning")
        return redirect(url_for("delivery.view_detail", request_id=req.id))

    if request.method == "POST":
        emergency_type = request.form.get("emergency_type")
        priority = request.form.get("priority")
        description = request.form.get("description")

        try:
            payload_weight = float(request.form.get("payload_weight_kg", req.payload_weight_kg))
            pickup_lat = float(request.form.get("pickup_latitude", req.pickup_latitude))
            pickup_lng = float(request.form.get("pickup_longitude", req.pickup_longitude))
            dest_lat = float(request.form.get("destination_latitude", req.destination_latitude))
            dest_lng = float(request.form.get("destination_longitude", req.destination_longitude))

            DeliveryService.update_request(
                request_id=req.id,
                user=user,
                emergency_type=emergency_type,
                priority=priority,
                payload_weight_kg=payload_weight,
                description=description,
                pickup_latitude=pickup_lat,
                pickup_longitude=pickup_lng,
                destination_latitude=dest_lat,
                destination_longitude=dest_lng,
            )

            flash(f"Delivery Request #{req.id} updated successfully.", "success")
            return redirect(url_for("delivery.view_detail", request_id=req.id))

        except (ValueError, DeliveryServiceError) as err:
            flash(f"Update failed: {err}", "danger")
            return render_template(
                "delivery/form.html",
                current_user=user,
                is_edit=True,
                req=req,
                form_data=request.form,
                emergency_types=[e.value for e in EmergencyType],
                priorities=[p.value for p in RequestPriority],
            ), 400

    return render_template(
        "delivery/form.html",
        current_user=user,
        is_edit=True,
        req=req,
        form_data=req.to_dict(),
        emergency_types=[e.value for e in EmergencyType],
        priorities=[p.value for p in RequestPriority],
    )


@delivery_bp.route("/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_request(request_id: int):
    """Cancel a delivery request when its current state permits cancellation."""
    user = AuthService.get_current_user()
    reason = request.form.get("cancellation_reason", "Cancelled by user")

    try:
        req = DeliveryService.cancel_request(request_id, user=user, reason=reason)
        flash(f"Delivery Request #{req.id} has been CANCELLED.", "warning")
    except (DeliveryRequestNotFoundError, DeliveryPermissionDeniedError, InvalidRequestStateError) as err:
        flash(f"Cancellation error: {err}", "danger")

    return redirect(url_for("delivery.view_detail", request_id=request_id))
