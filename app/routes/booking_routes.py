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

    return render_template(
        "booking/book.html",
        current_user=user,
        emergency_types=emergency_types,
        priorities=priorities,
        diversion_locations=diversions,
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

        results = DroneAvailabilityService.search_available_drones(
            requester_id=user.id,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            cargo_weight_kg=cargo_weight,
            cargo_category=cargo_category,
            priority=priority,
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

        booking = DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=quote_id,
            requester_id=user.id,
            weather_acknowledged=weather_ack,
            notes=notes,
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
    """Requester personal booking history."""
    user = AuthService.get_current_user()
    bookings = (
        DroneBooking.query.filter_by(requester_id=user.id)
        .order_by(DroneBooking.created_at.desc())
        .all()
    )
    return render_template(
        "booking/history.html",
        current_user=user,
        bookings=bookings,
    )
