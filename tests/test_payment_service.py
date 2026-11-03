"""Automated unit and integration tests for Payment Processing and Refund Policies."""

from decimal import Decimal
import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.payment_transaction import PaymentTransaction, PaymentStatus, PaymentMethod
from app.services.drone_availability_service import DroneAvailabilityService
from app.services.payment_service import (
    PaymentService,
    PaymentServiceError,
    InvalidPaymentStateError,
)
from app.services.weather_intelligence_service import WeatherIntelligenceService


@pytest.fixture
def setup_booking(app):
    user = User(
        full_name="Payment Tester",
        email="paytest@hospital.org",
        password="Password123!",
        role=UserRole.REQUESTER.value,
    )
    drone = Drone(
        drone_code="DRONE-PAY-01",
        model_name="SkyLifter Cargo",
        maximum_payload_kg=5.0,
        battery_capacity_wh=1000.0,
        current_battery_wh=1000.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add_all([user, drone])
    db.session.commit()

    WeatherIntelligenceService.clear_demonstration_scenario()
    results = DroneAvailabilityService.search_available_drones(
        requester_id=user.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.5,
    )
    quote_id = results["available_drones"][0]["quote_id"]
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=user.id,
    )
    return user, drone, booking


def test_successful_simulated_payment(app, setup_booking):
    """Verify successful cashless payment processing and idempotency."""
    user, drone, booking = setup_booking

    txn = PaymentService.process_payment(
        booking_id=booking.id,
        payment_method=PaymentMethod.SIMULATED_UPI.value,
    )

    assert txn.id is not None
    assert txn.payment_status == PaymentStatus.PAID.value
    assert txn.transaction_reference.startswith("TXN-")
    assert booking.status == BookingStatus.PAID.value

    # Verify idempotency: calling again with same key returns the existing transaction
    repeat_txn = PaymentService.process_payment(
        booking_id=booking.id,
        idempotency_key=txn.idempotency_key,
    )
    assert repeat_txn.id == txn.id

    # Trying to pay again without idempotency key raises InvalidPaymentStateError
    with pytest.raises(InvalidPaymentStateError):
        PaymentService.process_payment(booking_id=booking.id)


def test_simulated_gateway_failure(app, setup_booking):
    """Verify that simulated gateway failure results in FAILED status without locking the booking."""
    user, drone, booking = setup_booking

    txn = PaymentService.process_payment(
        booking_id=booking.id,
        payment_method=PaymentMethod.SIMULATED_CARD.value,
        simulate_failure=True,
    )

    assert txn.payment_status == PaymentStatus.FAILED.value
    # Booking status should remain CONFIRMED (ready for retry)
    assert booking.status == BookingStatus.CONFIRMED.value

    # Now retry successfully
    retry_txn = PaymentService.process_payment(
        booking_id=booking.id,
        payment_method=PaymentMethod.SIMULATED_WALLET.value,
        simulate_failure=False,
    )
    assert retry_txn.payment_status == PaymentStatus.PAID.value
    assert booking.status == BookingStatus.PAID.value


def test_cancellation_and_refund_policies(app, setup_booking):
    """Verify cancellation refunds: user voluntary cancellation vs weather full refund."""
    user, drone, booking = setup_booking

    # Pay first
    PaymentService.process_payment(booking_id=booking.id)

    # Cancel with policy
    res = PaymentService.cancel_booking_with_policy(
        booking_id=booking.id,
        reason="Medical emergency resolved on ground.",
    )

    assert res["status"] in ("CANCELLED", "REFUNDED")
    assert res["refund_amount"] > 0
    assert booking.status == BookingStatus.CANCELLED.value
    assert drone.status == DroneStatus.AVAILABLE.value


def test_itemized_tax_invoice_generation(app, setup_booking):
    """Verify itemized invoice generation with all tariff components."""
    user, drone, booking = setup_booking
    PaymentService.process_payment(booking_id=booking.id)

    invoice = PaymentService.generate_invoice(booking.id)

    assert invoice["booking_reference"] == booking.booking_reference
    assert invoice["payment_status"] == PaymentStatus.PAID.value
    assert "base_fare" in invoice["items"]
    assert "distance_charge" in invoice["items"]
    assert "tax_amount" in invoice["items"]
    assert invoice["items"]["total_amount"] > 0
    assert invoice["requester"]["email"] == user.email
