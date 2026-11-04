from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from app.extensions import db
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
    CargoCategory,
    CARGO_CATEGORY_REGISTRY,
    normalize_cargo_category,
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
    """List delivery requests scoped to the authenticated user's role with filter, search, and pagination."""
    user = AuthService.get_current_user()

    priority = request.args.get("priority")
    status = request.args.get("status")
    emergency_type = request.args.get("emergency_type")
    delivery_direction = request.args.get("delivery_direction")
    search_query = request.args.get("search", "").strip() or None
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    page = request.args.get("page", 1, type=int)
    per_page = 15

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

    pagination = DeliveryService.get_requests_for_user(
        user=user,
        priority=priority,
        status=status,
        emergency_type=emergency_type,
        delivery_direction=delivery_direction,
        search_query=search_query,
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
    )

    requests_list = pagination.items if hasattr(pagination, "items") else pagination

    return render_template(
        "delivery/list.html",
        current_user=user,
        requests=requests_list,
        pagination=pagination,
        filters={
            "priority": priority,
            "status": status,
            "emergency_type": emergency_type,
            "delivery_direction": delivery_direction,
            "search": search_query or "",
            "start_date": start_date_str,
            "end_date": end_date_str,
        },
        emergency_types=[e.value for e in EmergencyType],
        cargo_categories=CARGO_CATEGORY_REGISTRY,
        priorities=[p.value for p in RequestPriority],
        statuses=[s.value for s in RequestStatus],
    )


@delivery_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_request():
    """Create a new universal multipurpose delivery request."""
    user = AuthService.get_current_user()

    if request.method == "POST":
        emergency_type = request.form.get("emergency_type", "").strip()
        priority = request.form.get("priority", RequestPriority.HIGH.value).strip()
        description = request.form.get("description", "").strip()
        delivery_direction = request.form.get("delivery_direction", "SEND").strip()

        custom_item_name = request.form.get("custom_item_name", "").strip() or None
        package_dimensions = request.form.get("package_dimensions", "").strip() or None
        package_count = request.form.get("package_count", 1, type=int)
        handling_instructions = request.form.get("handling_instructions", "").strip() or None
        pickup_contact_name = request.form.get("pickup_contact_name", "").strip() or None
        pickup_contact_phone = request.form.get("pickup_contact_phone", "").strip() or None
        delivery_contact_name = request.form.get("delivery_contact_name", "").strip() or None
        delivery_contact_phone = request.form.get("delivery_contact_phone", "").strip() or None
        special_instructions = request.form.get("special_instructions", "").strip() or None

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
                delivery_direction=delivery_direction,
                custom_item_name=custom_item_name,
                package_dimensions=package_dimensions,
                package_count=package_count,
                handling_instructions=handling_instructions,
                pickup_contact_name=pickup_contact_name,
                pickup_contact_phone=pickup_contact_phone,
                delivery_contact_name=delivery_contact_name,
                delivery_contact_phone=delivery_contact_phone,
                special_instructions=special_instructions,
            )

            flash(f"Delivery Request #{req.display_reference} registered successfully.", "success")
            return redirect(url_for("delivery.view_detail", request_id=req.id))

        except (ValueError, DeliveryServiceError) as err:
            flash(f"Validation error: {err}", "danger")
            return render_template(
                "delivery/form.html",
                current_user=user,
                is_edit=False,
                form_data=request.form,
                emergency_types=[e.value for e in EmergencyType],
                cargo_categories=CARGO_CATEGORY_REGISTRY,
                priorities=[p.value for p in RequestPriority],
            ), 400

    return render_template(
        "delivery/form.html",
        current_user=user,
        is_edit=False,
        form_data={},
        emergency_types=[e.value for e in EmergencyType],
        cargo_categories=CARGO_CATEGORY_REGISTRY,
        priorities=[p.value for p in RequestPriority],
    )


@delivery_bp.route("/<int:request_id>", methods=["GET"])
@login_required
def view_detail(request_id: int):
    """View comprehensive delivery request details with audit activity timeline and IDOR protection."""
    user = AuthService.get_current_user()
    try:
        req = DeliveryService.get_request_by_id(request_id, user=user)
    except DeliveryRequestNotFoundError:
        abort(404, description=f"Delivery request #{request_id} not found.")
    except DeliveryPermissionDeniedError:
        abort(403, description="Access Denied: You do not have permission to view another user's delivery request.")

    activities = req.activities.all()
    booking = req.booking
    routes = req.routes.all()

    return render_template(
        "delivery/detail.html",
        current_user=user,
        req=req,
        activities=activities,
        booking=booking,
        routes=routes,
        category_meta=req.cargo_category_meta,
    )


@delivery_bp.route("/<int:request_id>/approve", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def approve_request(request_id: int):
    """Operator approves a submitted delivery request."""
    user = AuthService.get_current_user()
    notes = request.form.get("notes", "Approved by operator")
    try:
        req = DeliveryService.approve_request(request_id, operator_user=user, notes=notes)
        flash(f"Request #{req.display_reference} APPROVED.", "success")
    except Exception as exc:
        flash(f"Approval failed: {exc}", "danger")
    return redirect(url_for("delivery.view_detail", request_id=request_id))


@delivery_bp.route("/<int:request_id>/reject", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def reject_request(request_id: int):
    """Operator rejects a delivery request with recorded reason."""
    user = AuthService.get_current_user()
    reason = request.form.get("rejection_reason", "Operational or safety infeasibility")
    try:
        req = DeliveryService.reject_request(request_id, operator_user=user, reason=reason)
        flash(f"Request #{req.display_reference} REJECTED: {reason}", "warning")
    except Exception as exc:
        flash(f"Rejection failed: {exc}", "danger")
    return redirect(url_for("delivery.view_detail", request_id=request_id))


@delivery_bp.route("/<int:request_id>/complete", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def complete_request(request_id: int):
    """Operator manually marks a delivery request as completed."""
    user = AuthService.get_current_user()
    try:
        req = DeliveryService.complete_delivery(request_id, operator_user=user)
        flash(f"Request #{req.display_reference} marked as DELIVERED.", "success")
    except Exception as exc:
        flash(f"Completion failed: {exc}", "danger")
    return redirect(url_for("delivery.view_detail", request_id=request_id))


@delivery_bp.route("/<int:request_id>/rebook", methods=["GET"])
@login_required
def rebook_request(request_id: int):
    """Prefill new booking screen using details from a prior delivery request."""
    user = AuthService.get_current_user()
    req = DeliveryService.get_request_by_id(request_id, user=user)

    return redirect(url_for(
        "booking.new_booking",
        direction=req.delivery_direction,
        pickup_lat=float(req.pickup_latitude),
        pickup_lng=float(req.pickup_longitude),
        dest_lat=float(req.destination_latitude),
        dest_lng=float(req.destination_longitude),
        cargo_category=req.emergency_type,
        cargo_weight_kg=float(req.payload_weight_kg),
        priority=req.priority,
        custom_item_name=req.custom_item_name or "",
    ))


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

    if req.status not in {RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value, RequestStatus.SUBMITTED.value}:
        flash(f"Cannot edit request #{req.id}: status is already '{req.status}'.", "warning")
        return redirect(url_for("delivery.view_detail", request_id=req.id))

    if request.method == "POST":
        emergency_type = request.form.get("emergency_type")
        priority = request.form.get("priority")
        description = request.form.get("description")
        custom_item_name = request.form.get("custom_item_name")
        handling_instructions = request.form.get("handling_instructions")
        special_instructions = request.form.get("special_instructions")

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
                custom_item_name=custom_item_name,
                handling_instructions=handling_instructions,
                special_instructions=special_instructions,
            )

            flash(f"Delivery Request #{req.display_reference} updated successfully.", "success")
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
                cargo_categories=CARGO_CATEGORY_REGISTRY,
                priorities=[p.value for p in RequestPriority],
            ), 400

    return render_template(
        "delivery/form.html",
        current_user=user,
        is_edit=True,
        req=req,
        form_data=req.to_dict(),
        emergency_types=[e.value for e in EmergencyType],
        cargo_categories=CARGO_CATEGORY_REGISTRY,
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
        flash(f"Delivery Request #{req.display_reference} has been CANCELLED.", "warning")
    except (DeliveryRequestNotFoundError, DeliveryPermissionDeniedError, InvalidRequestStateError) as err:
        flash(f"Cancellation error: {err}", "danger")

    return redirect(url_for("delivery.view_detail", request_id=request_id))


@delivery_bp.route("/<int:request_id>/optimize", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def optimize_routes(request_id: int):
    """Generate and evaluate candidate routes for a delivery request."""
    from app.services.drone_allocation_service import DroneAllocationService

    algorithm = request.form.get("algorithm", "WEIGHTED_MULTI_OBJECTIVE")
    include_return = request.form.get("include_return_trip") == "1"

    try:
        opt_result, selected_route = DroneAllocationService.generate_and_persist_routes(
            delivery_request_id=request_id,
            algorithm_name=algorithm,
            include_return_trip=include_return,
        )
        if opt_result.is_feasible and selected_route:
            flash(
                f"Generated {opt_result.candidate_count} flight corridors ({opt_result.feasible_count} feasible). "
                f"Optimal corridor selected: Route #{selected_route.id} ({selected_route.estimated_distance_km} km, "
                f"{selected_route.estimated_energy_wh} Wh).",
                "success",
            )
        else:
            flash(
                f"Evaluation completed: {opt_result.summary_message}",
                "warning",
            )
    except Exception as exc:
        flash(f"Route optimization failed: {exc}", "danger")

    return redirect(url_for("delivery.view_detail", request_id=request_id))
