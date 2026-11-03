"""Automated unit and integration tests for the Dynamic Pricing and Invoicing Service."""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from app.extensions import db
from app.models.pricing_configuration import PricingConfiguration
from app.models.drone_quote import DroneQuote
from app.models.drone import Drone, DroneStatus
from app.models.user import User, UserRole
from app.models.delivery_request import RequestPriority, EmergencyType
from app.services.pricing_service import PricingService, QuoteExpiredError


@pytest.fixture
def sample_user(app):
    user = User(
        full_name="City Hospital EMS",
        email="hospital@health.org",
        password="Requester@123",
        role=UserRole.REQUESTER.value,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def sample_drone(app):
    drone = Drone(
        drone_code="DRONE-PRICE-01",
        model_name="SkyLifter Cargo X1",
        maximum_payload_kg=5.0,
        battery_capacity_wh=1000.0,
        current_battery_wh=1000.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add(drone)
    db.session.commit()
    return drone


def test_pricing_calculation_math(app):
    """Verify exact formula calculation."""
    PricingService.get_or_create_active_config()

    breakdown = PricingService.calculate_price_breakdown(
        flight_distance_km=10.0,
        cargo_weight_kg=2.0,
        priority=RequestPriority.CRITICAL.value,
    )

    # Base fare (100) + Distance (10 * 25 = 250) + Weight (2 * 15 = 30) + Priority (150) + Service (30) = 560.00
    assert breakdown["base_fare"] == 100.0
    assert breakdown["distance_charge"] == 250.0
    assert breakdown["weight_charge"] == 30.0
    assert breakdown["priority_charge"] == 150.0
    assert breakdown["service_fee"] == 30.0
    assert breakdown["subtotal"] == 560.0

    # Tax: 5% of 560 = 28.00
    assert breakdown["tax_amount"] == 28.00

    # Total: 560 + 28.00 = 588.00
    assert breakdown["total_price"] == 588.00


def test_pricing_clamping_minimum_and_maximum(app):
    """Verify price clamping against configured minimum and maximum limits."""
    # Test floor clamping
    breakdown_low = PricingService.calculate_price_breakdown(
        flight_distance_km=0.1,
        cargo_weight_kg=0.1,
        priority=RequestPriority.LOW.value,
    )
    assert breakdown_low["subtotal"] >= 150.0

    # Update max limit to 1000 for testing ceiling
    PricingService.update_pricing_config(maximum_fare="1000.00")
    breakdown_high = PricingService.calculate_price_breakdown(
        flight_distance_km=100.0,
        cargo_weight_kg=10.0,
        priority=RequestPriority.CRITICAL.value,
    )
    assert breakdown_high["subtotal"] == 1000.0
    # Total includes tax (5%) on clamped 1000: 1000 + 50 = 1050
    assert breakdown_high["total_price"] == 1050.0


def test_quote_creation_and_expiration(app, sample_user, sample_drone):
    """Test creating a quote snapshot and validating TTL expiration."""
    quote = PricingService.generate_and_persist_quote(
        requester_id=sample_user.id,
        drone_id=sample_drone.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.5,
        cargo_category=EmergencyType.EMERGENCY_MEDICINE.value,
        priority=RequestPriority.HIGH.value,
        corridor_name="DIRECT_GEODESIC",
        flight_distance_km=8.5,
        ferry_distance_km=0.0,
        estimated_pickup_duration_min=0.0,
        estimated_delivery_duration_min=10.0,
        estimated_energy_wh=120.0,
    )

    assert quote.id is not None
    assert quote.is_expired() is False
    assert quote.is_accepted is False

    # Simulate quote expiration
    quote.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.session.commit()

    assert quote.is_expired() is True
    with pytest.raises(QuoteExpiredError):
        PricingService.validate_quote(quote.id)
