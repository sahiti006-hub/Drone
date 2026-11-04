"""Uber/Rapido-style drone booking, real-time availability, and cashless payment routes."""

from decimal import Decimal
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    abort,
)
from app.extensions import db
from app.models.user import UserRole
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.drone_quote import DroneQuote
from app.models.delivery_request import EmergencyType, RequestPriority
from app.services.auth_service import AuthService, login_required, role_required
from app.services.drone_availability_service import (
    DroneAvailabilityService,
    DroneAvailabilityError,
    ConcurrencyLockError,
    InfeasibleBookingError,
)
from app.services.pricing_service import PricingService, QuoteExpiredError
from app.services.payment_service import (
    PaymentService,
    PaymentServiceError,
    InvalidPaymentStateError,
)
from app.services.weather_intelligence_service import WeatherIntelligenceService

booking_bp = Blueprint("booking", __name__, url_prefix="/booking")


@booking_bp.route("/new", methods=["GET"])
@login_required
def new_booking():
    """Interactive Uber/Rapido-style drone booking cockpit."""
    user = AuthService.get_current_user()
    emergency_types = [e.value for e in EmergencyType]
    priorities = [p.value for p in RequestPriority]
    diversions = WeatherIntelligenceService.get_or_seed_diversion_locations()
    saved_locs = user.saved_locations.all() if hasattr(user, "saved_locations") else []
    recent_bookings = (
        DroneBooking.query.filter_by(requester_id=user.id)
        .order_by(DroneBooking.created_at.desc())
        .limit(5)
        .all()
    )

    prefill = {
        "direction": request.args.get("direction", "SEND").upper(),
        "pickup_lat": request.args.get("pickup_lat", ""),
        "pickup_lng": request.args.get("pickup_lng", ""),
        "dest_lat": request.args.get("dest_lat", ""),
        "dest_lng": request.args.get("dest_lng", ""),
        "cargo_category": request.args.get("cargo_category", ""),
        "cargo_weight_kg": request.args.get("cargo_weight_kg", "1.0"),
        "priority": request.args.get("priority", "HIGH"),
        "pickup_name": request.args.get("pickup_name", ""),
        "dest_name": request.args.get("dest_name", ""),
        "custom_item_name": request.args.get("custom_item_name", ""),
        "package_size": request.args.get("package_size", "SMALL"),
    }

    from app.models.delivery_request import CARGO_CATEGORY_REGISTRY
    return render_template(
        "booking/book.html",
        current_user=user,
        emergency_types=emergency_types,
        cargo_categories=CARGO_CATEGORY_REGISTRY,
        priorities=priorities,
        diversion_locations=diversions,
        saved_locations=saved_locs,
        recent_bookings=recent_bookings,
        prefill=prefill,
    )


@booking_bp.route("/search", methods=["POST"])
@login_required
def search_drones():
    """AJAX endpoint for real-time fleet availability, corridor generation, and transparent pricing."""
    user = AuthService.get_current_user()
    data = request.get_json(silent=True) or request.form

    try:
        pickup_lat = float(data.get("pickup_latitude", 0))
        pickup_lng = float(data.get("pickup_longitude", 0))
        dest_lat = float(data.get("destination_latitude", 0))
        dest_lng = float(data.get("destination_longitude", 0))
        cargo_weight = float(data.get("cargo_weight_kg", 1.0))
        cargo_category = data.get("cargo_category", EmergencyType.EMERGENCY_MEDICINE.value)
        priority = data.get("priority", RequestPriority.HIGH.value)
        delivery_direction = data.get("delivery_direction", "SEND").upper()
        custom_item_name = data.get("custom_item_name", "")
        package_size = data.get("package_size", "SMALL")

        results = DroneAvailabilityService.search_available_drones(
            requester_id=user.id,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            cargo_weight_kg=cargo_weight,
            cargo_category=cargo_category,
            priority=priority,
            delivery_direction=delivery_direction,
            custom_item_name=custom_item_name,
            package_size=package_size,
        )
        return jsonify({"status": "success", "data": results}), 200

    except DroneAvailabilityError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Invalid numerical inputs: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Availability search failed: {str(e)}"}), 500


@booking_bp.route("/quote/<int:quote_id>", methods=["GET"])
@login_required
def get_quote_details(quote_id: int):
    """Retrieve detailed itemized price quote."""
    quote = db.session.get(DroneQuote, quote_id)
    if not quote:
        return jsonify({"status": "error", "message": f"Quote #{quote_id} not found."}), 404

    return jsonify({"status": "success", "quote": quote.to_dict()}), 200


@booking_bp.route("/confirm", methods=["POST"])
@login_required
def confirm_booking():
    """Atomically confirm booking, acquire concurrency locks on drone, and return booking reference."""
    user = AuthService.get_current_user()
    data = request.get_json(silent=True) or request.form

    try:
        quote_id = int(data.get("quote_id", 0))
        weather_ack = str(data.get("weather_acknowledged", "false")).lower() in ("true", "1", "yes")
        notes = data.get("notes", "")
        delivery_direction = data.get("delivery_direction")
        collection_contact_name = data.get("collection_contact_name")
        collection_contact_phone = data.get("collection_contact_phone")
        collection_readiness = data.get("collection_readiness")
        collection_instructions = data.get("collection_instructions")
        custom_item_name = data.get("custom_item_name")
        custom_item_description = data.get("custom_item_description")
        package_size = data.get("package_size")
        package_dimensions = data.get("package_dimensions")
        package_count = int(data.get("package_count", 1) or 1)
        handling_instructions = data.get("handling_instructions")
        pickup_contact_name = data.get("pickup_contact_name")
        pickup_contact_phone = data.get("pickup_contact_phone")
        delivery_contact_name = data.get("delivery_contact_name")
        delivery_contact_phone = data.get("delivery_contact_phone")
        special_instructions = data.get("special_instructions")

        booking = DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=quote_id,
            requester_id=user.id,
            weather_acknowledged=weather_ack,
            notes=notes,
            delivery_direction=delivery_direction,
            collection_contact_name=collection_contact_name,
            collection_contact_phone=collection_contact_phone,
            collection_readiness=collection_readiness,
            collection_instructions=collection_instructions,
            custom_item_name=custom_item_name,
            custom_item_description=custom_item_description,
            package_size=package_size,
            package_dimensions=package_dimensions,
            package_count=package_count,
            handling_instructions=handling_instructions,
            pickup_contact_name=pickup_contact_name,
            pickup_contact_phone=pickup_contact_phone,
            delivery_contact_name=delivery_contact_name,
            delivery_contact_phone=delivery_contact_phone,
            special_instructions=special_instructions,
        )

        flash(
            f"Drone booking confirmed successfully! Reference: {booking.booking_reference}. Please proceed to payment.",
            "success",
        )

        if request.is_json:
            return jsonify({
                "status": "success",
                "booking_id": booking.id,
                "booking_reference": booking.booking_reference,
                "redirect_url": url_for("booking.view_booking", booking_id=booking.id),
            }), 201

        return redirect(url_for("booking.view_booking", booking_id=booking.id))

    except ConcurrencyLockError as e:
        if request.is_json:
            return jsonify({"status": "conflict", "message": str(e)}), 409
        flash(str(e), "danger")
        return redirect(url_for("booking.new_booking"))
    except (InfeasibleBookingError, QuoteExpiredError, DroneAvailabilityError) as e:
        if request.is_json:
            return jsonify({"status": "error", "message": str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for("booking.new_booking"))
    except Exception as e:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Confirmation failed: {str(e)}"}), 500
        flash(f"Confirmation failed: {str(e)}", "danger")
        return redirect(url_for("booking.new_booking"))


@booking_bp.route("/<int:booking_id>", methods=["GET"])
@login_required
def view_booking(booking_id: int):
    """View real-time booking cockpit, live telemetry HUD, route, and payment status."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        abort(404)

    # Permission check: Requester can only view their own bookings; Admins & Operators can view all
    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        abort(403)

    quote = booking.quote
    latest_payment = booking.latest_payment
    weather_alerts = booking.weather_alerts.order_by(db.desc("created_at")).all()
    refunds = booking.refund_transactions.all()

    # Link simulation run if assignment exists
    sim_run = None
    if booking.delivery_request and booking.delivery_request.assignments.first():
        assign = booking.delivery_request.assignments.first()
        sim_run = assign.simulation_runs.first()

    return render_template(
        "booking/detail.html",
        current_user=user,
        booking=booking,
        quote=quote,
        payment=latest_payment,
        alerts=weather_alerts,
        refunds=refunds,
        simulation=sim_run,
    )


@booking_bp.route("/<int:booking_id>/pay", methods=["POST"])
@login_required
def process_payment(booking_id: int):
    """Process simulated cashless payment for a confirmed booking."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        abort(404)

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        abort(403)

    data = request.get_json(silent=True) or request.form
    payment_method = data.get("payment_method", "SIMULATED_UPI")
    simulate_fail = str(data.get("simulate_failure", "false")).lower() in ("true", "1", "yes")

    try:
        txn = PaymentService.process_payment(
            booking_id=booking.id,
            payment_method=payment_method,
            simulate_failure=simulate_fail,
        )

        if txn.payment_status == "PAID":
            flash(
                f"Simulated payment of ₹{float(txn.final_amount):.2f} processed successfully! Reference: {txn.transaction_reference}.",
                "success",
            )
        else:
            flash(f"Payment failed: {txn.reason_for_adjustment}. Please retry.", "danger")

        if request.is_json:
            return jsonify({
                "status": "success" if txn.payment_status == "PAID" else "failed",
                "transaction": txn.to_dict(),
            }), 200

        return redirect(url_for("booking.view_booking", booking_id=booking.id))

    except (PaymentServiceError, InvalidPaymentStateError) as e:
        if request.is_json:
            return jsonify({"status": "error", "message": str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for("booking.view_booking", booking_id=booking.id))


@booking_bp.route("/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id: int):
    """Cancel booking and apply configured refund policy."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        abort(404)

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        abort(403)

    data = request.get_json(silent=True) or request.form
    reason = data.get("reason", "Cancelled by user.")

    try:
        res = PaymentService.cancel_booking_with_policy(booking_id=booking.id, reason=reason)
        flash(f"Booking cancelled. Outcome: {res['status']}. Refund issued: ₹{res.get('refund_amount', 0):.2f}.", "info")

        if request.is_json:
            return jsonify({"status": "success", "result": res}), 200

        return redirect(url_for("booking.view_booking", booking_id=booking.id))

    except PaymentServiceError as e:
        if request.is_json:
            return jsonify({"status": "error", "message": str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for("booking.view_booking", booking_id=booking.id))


@booking_bp.route("/<int:booking_id>/invoice", methods=["GET"])
@login_required
def view_invoice(booking_id: int):
    """Display final itemized delivery invoice."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        abort(404)

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        abort(403)

    invoice_data = PaymentService.generate_invoice(booking.id)
    return render_template(
        "booking/invoice.html",
        current_user=user,
        booking=booking,
        invoice=invoice_data,
    )


@booking_bp.route("/history", methods=["GET"])
@login_required
def booking_history():
    """Universal booking and mission history ledger with multi-variable filters and pagination."""
    user = AuthService.get_current_user()
    direction_filter = request.args.get("direction", "ALL").upper()
    status_filter = request.args.get("status", "ALL").upper()
    category_filter = request.args.get("category", "ALL").upper()
    search_query = request.args.get("search", "").strip() or None
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    page = request.args.get("page", 1, type=int)

    query = DroneBooking.query
    if user.role == UserRole.REQUESTER.value:
        query = query.filter(DroneBooking.requester_id == user.id)

    if direction_filter in ["SEND", "RECEIVE"]:
        query = query.filter(DroneBooking.delivery_direction == direction_filter)

    if status_filter == "ACTIVE":
        query = query.filter(
            DroneBooking.status.in_([
                BookingStatus.CONFIRMED.value,
                BookingStatus.PAID.value,
                BookingStatus.DISPATCHED.value,
                BookingStatus.IN_FLIGHT.value,
                BookingStatus.WEATHER_CAUTION.value,
                BookingStatus.REROUTED.value,
            ])
        )
    elif status_filter == "COMPLETED":
        query = query.filter(DroneBooking.status == BookingStatus.DELIVERED.value)
    elif status_filter == "CANCELLED":
        query = query.filter(DroneBooking.status == BookingStatus.CANCELLED.value)
    elif status_filter == "DIVERTED":
        query = query.filter(DroneBooking.status == BookingStatus.DIVERTED.value)

    if category_filter and category_filter != "ALL":
        from app.models.delivery_request import normalize_cargo_category
        norm_cat = normalize_cargo_category(category_filter)
        query = query.join(DroneQuote, DroneBooking.quote_id == DroneQuote.id).filter(
            (DroneQuote.cargo_category == category_filter) | (DroneQuote.cargo_category == norm_cat)
        )

    if search_query:
        term = f"%{search_query}%"
        query = query.filter(
            (DroneBooking.booking_reference.ilike(term)) |
            (DroneBooking.custom_item_name.ilike(term)) |
            (DroneBooking.notes.ilike(term))
        )

    if start_date_str:
        try:
            s_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            query = query.filter(DroneBooking.created_at >= s_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            e_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(DroneBooking.created_at <= e_date)
        except ValueError:
            pass

    pagination = query.order_by(DroneBooking.created_at.desc()).paginate(page=page, per_page=15, error_out=False)
    bookings = pagination.items

    from app.models.delivery_request import CARGO_CATEGORY_REGISTRY
    return render_template(
        "booking/history.html",
        current_user=user,
        bookings=bookings,
        pagination=pagination,
        direction_filter=direction_filter,
        status_filter=status_filter,
        category_filter=category_filter,
        search_query=search_query or "",
        start_date=start_date_str or "",
        end_date=end_date_str or "",
        cargo_categories=CARGO_CATEGORY_REGISTRY,
    )


@booking_bp.route("/<int:booking_id>/rate", methods=["POST"])
@login_required
def rate_booking(booking_id: int):
    """Submit post-delivery customer rating and experience feedback."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        abort(404)

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        abort(403)

    if booking.status != BookingStatus.DELIVERED.value:
        if request.is_json:
            return jsonify({
                "status": "error",
                "message": "Ratings can only be submitted for completed deliveries.",
            }), 400
        flash("Ratings can only be submitted for completed deliveries.", "warning")
        return redirect(url_for("booking.view_booking", booking_id=booking.id))

    data = request.get_json(silent=True) or request.form
    try:
        rating_val = int(data.get("rating", 5))
        rating_val = max(1, min(5, rating_val))
    except (ValueError, TypeError):
        rating_val = 5

    feedback = data.get("feedback_text", "").strip()
    booking_score = int(data.get("booking_experience_score", 5)) if data.get("booking_experience_score") else None
    speed_score = int(data.get("speed_score", 5)) if data.get("speed_score") else None

    from app.models.delivery_rating import DeliveryRating
    existing_rating = DeliveryRating.query.filter_by(booking_id=booking.id).first()
    if existing_rating:
        existing_rating.rating = rating_val
        existing_rating.feedback_text = feedback
        existing_rating.booking_experience_score = booking_score
        existing_rating.speed_score = speed_score
    else:
        new_rating = DeliveryRating(
            booking_id=booking.id,
            user_id=user.id,
            rating=rating_val,
            feedback_text=feedback,
            booking_experience_score=booking_score,
            speed_score=speed_score,
        )
        db.session.add(new_rating)

    db.session.commit()
    flash("Thank you! Your delivery experience feedback has been recorded.", "success")

    if request.is_json:
        return jsonify({"status": "success", "message": "Feedback submitted successfully."}), 200

    return redirect(url_for("booking.view_booking", booking_id=booking.id))


@booking_bp.route("/track/<string:reference>", methods=["GET"])
def public_tracking(reference: str):
    """Public shareable live tracking HUD (Uber ride share link style, no sensitive medical details)."""
    booking = DroneBooking.query.filter_by(booking_reference=reference).first()
    if not booking:
        abort(404)

    drone = booking.drone
    alerts = booking.weather_alerts.order_by(db.desc("created_at")).all()
    quote = booking.quote

    # Link simulation run if assignment exists
    sim_run = None
    if booking.delivery_request and booking.delivery_request.assignments.first():
        assign = booking.delivery_request.assignments.first()
        sim_run = assign.simulation_runs.first()

    return render_template(
        "booking/public_tracking.html",
        booking=booking,
        drone=drone,
        alerts=alerts,
        quote=quote,
        simulation=sim_run,
    )


# ==============================================================================
# LIVE DRONE MOVEMENT & SIMULATION TELEMETRY ENDPOINTS
# ==============================================================================

@booking_bp.route("/<int:booking_id>/telemetry", methods=["GET"])
@login_required
def get_booking_telemetry(booking_id: int):
    """Retrieve real-time drone telemetry and tick forward simulation position."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        telemetry = SimulationService.tick_simulation_for_booking(booking_id)
        return jsonify({"status": "success", "data": telemetry}), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Simulation tick failed: {str(exc)}"}), 500


@booking_bp.route("/<int:booking_id>/simulation/start", methods=["POST"])
@login_required
def start_booking_flight(booking_id: int):
    """Start or dispatch continuous drone flight simulation."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        sim = SimulationService.start_booking_simulation(booking_id)
        telemetry = SimulationService.tick_simulation_for_booking(booking_id)
        return jsonify({
            "status": "success",
            "message": "Flight simulation started.",
            "data": telemetry,
        }), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Start failed: {str(exc)}"}), 500


@booking_bp.route("/<int:booking_id>/simulation/pause", methods=["POST"])
@login_required
def pause_booking_flight(booking_id: int):
    """Pause in-flight drone simulation."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        sim = SimulationService.pause_booking_simulation(booking_id)
        telemetry = SimulationService.tick_simulation_for_booking(booking_id)
        return jsonify({
            "status": "success",
            "message": "Flight simulation paused.",
            "data": telemetry,
        }), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400


@booking_bp.route("/<int:booking_id>/simulation/resume", methods=["POST"])
@login_required
def resume_booking_flight(booking_id: int):
    """Resume in-flight drone simulation."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        sim = SimulationService.resume_booking_simulation(booking_id)
        telemetry = SimulationService.tick_simulation_for_booking(booking_id)
        return jsonify({
            "status": "success",
            "message": "Flight simulation resumed.",
            "data": telemetry,
        }), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400


@booking_bp.route("/<int:booking_id>/simulation/speed", methods=["POST"])
@login_required
def set_booking_simulation_speed(booking_id: int):
    """Set simulation speed multiplier (1x, 2x, 5x)."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    data = request.get_json(silent=True) or request.form
    try:
        speed = float(data.get("speed", 1.0))
    except (ValueError, TypeError):
        speed = 1.0

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        sim = SimulationService.set_booking_simulation_speed(booking_id, speed)
        return jsonify({
            "status": "success",
            "message": f"Simulation speed set to {speed}x.",
            "speed": sim.speed_multiplier,
        }), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400


@booking_bp.route("/<int:booking_id>/simulation/reset", methods=["POST"])
@login_required
def reset_booking_flight(booking_id: int):
    """Reset simulation back to start for demonstration purposes."""
    user = AuthService.get_current_user()
    booking = db.session.get(DroneBooking, booking_id)
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    if user.role == UserRole.REQUESTER.value and booking.requester_id != user.id:
        return jsonify({"status": "error", "message": "Access denied."}), 403

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        sim = SimulationService.reset_booking_simulation(booking_id)
        telemetry = SimulationService.tick_simulation_for_booking(booking_id)
        return jsonify({
            "status": "success",
            "message": "Flight simulation reset.",
            "data": telemetry,
        }), 200
    except SimulationServiceError as err:
        return jsonify({"status": "error", "message": str(err)}), 400


@booking_bp.route("/track/<string:reference>/telemetry", methods=["GET"])
def public_tracking_telemetry(reference: str):
    """Anonymous public tracking telemetry stream."""
    booking = DroneBooking.query.filter_by(booking_reference=reference).first()
    if not booking:
        return jsonify({"status": "error", "message": "Booking not found."}), 404

    from app.services.simulation_service import SimulationService, SimulationServiceError
    try:
        telemetry = SimulationService.tick_simulation_for_booking(booking.id)
        return jsonify({"status": "success", "data": telemetry}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

