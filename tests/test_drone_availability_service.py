"""Automated unit and integration tests for Drone Availability and Concurrency Locking."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.weather_intelligence import WeatherClassification
from app.services.drone_availability_service import (
    DroneAvailabilityService,
    ConcurrencyLockError,
    InfeasibleBookingError,
)
from app.services.weather_intelligence_service import WeatherIntelligenceService


@pytest.fixture
def sample_requester(app):
    user = User(
        full_name="Hospital Emergency Unit",
        email="ems@hospital.org",
        password="RequesterPass1!",
        role=UserRole.REQUESTER.value,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def setup_fleet(app):
    """Setup drones with different payload and battery characteristics."""
    # Drone 1: High capacity, full battery -> AVAILABLE
    d1 = Drone(
        drone_code="DRONE-ALPHA-01",
        model_name="SkyLifter Heavy",
        maximum_payload_kg=10.0,
        battery_capacity_wh=2000.0,
        current_battery_wh=2000.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.AVAILABLE.value,
    )
    # Drone 2: Light payload limit -> UNAVAILABLE for heavy cargo
    d2 = Drone(
        drone_code="DRONE-BETA-02",
        model_name="MicroScout Light",
        maximum_payload_kg=1.0,
        battery_capacity_wh=500.0,
        current_battery_wh=500.0,
        cruise_speed_kmh=45.0,
        status=DroneStatus.AVAILABLE.value,
    )
    # Drone 3: Very low battery -> UNAVAILABLE (cannot meet reserve)
    d3 = Drone(
        drone_code="DRONE-GAMMA-03",
        model_name="SkyLifter Mid",
        maximum_payload_kg=5.0,
        battery_capacity_wh=1000.0,
        current_battery_wh=100.0,  # 10% battery
        cruise_speed_kmh=50.0,
        status=DroneStatus.AVAILABLE.value,
    )
    # Drone 4: In maintenance -> UNAVAILABLE
    d4 = Drone(
        drone_code="DRONE-DELTA-04",
        model_name="SkyLifter Mid",
        maximum_payload_kg=5.0,
        battery_capacity_wh=1000.0,
        current_battery_wh=1000.0,
        cruise_speed_kmh=50.0,
        status=DroneStatus.MAINTENANCE.value,
    )
    db.session.add_all([d1, d2, d3, d4])
    db.session.commit()
    return d1, d2, d3, d4


def test_drone_availability_search_categorization(app, sample_requester, setup_fleet):
    """Verify fleet search classifies drones correctly based on payload, battery, and status."""
    WeatherIntelligenceService.clear_demonstration_scenario()

    results = DroneAvailabilityService.search_available_drones(
        requester_id=sample_requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=3.5,  # Exceeds Drone 2's 1.0kg limit
        cargo_category="BLOOD_UNITS",
        priority="CRITICAL",
    )

    available = results["available_drones"]
    limited = results["limited_drones"]
    unavailable = results["unavailable_drones"]

    available_codes = [c["drone_code"] for c in available]
    unavailable_codes = [c["drone_code"] for c in unavailable]

    # DRONE-ALPHA-01 should be available
    assert "DRONE-ALPHA-01" in available_codes

    # DRONE-BETA-02 (payload 1.0kg < 3.5kg) should be unavailable
    assert "DRONE-BETA-02" in unavailable_codes

    # DRONE-DELTA-04 (status MAINTENANCE) should be unavailable
    assert "DRONE-DELTA-04" in unavailable_codes


def test_concurrency_locking_and_booking_confirmation(app, sample_requester, setup_fleet):
    """Verify atomic booking confirmation, drone status transition to RESERVED, and double-booking rejection."""
    WeatherIntelligenceService.clear_demonstration_scenario()

    results = DroneAvailabilityService.search_available_drones(
        requester_id=sample_requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        priority="HIGH",
    )

    # Pick the quote for DRONE-ALPHA-01
    alpha_card = next(c for c in results["available_drones"] if c["drone_code"] == "DRONE-ALPHA-01")
    quote_id = alpha_card["quote_id"]

    # Confirm booking
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=sample_requester.id,
        weather_acknowledged=False,
    )

    assert booking.id is not None
    assert booking.status == BookingStatus.CONFIRMED.value
    assert booking.drone.status == DroneStatus.RESERVED.value

    # Simulate another requester attempting to confirm another quote for the same locked drone
    # Search again to get a second quote for the same drone
    d1 = Drone.query.filter_by(drone_code="DRONE-ALPHA-01").first()
    # If the drone is already RESERVED, confirming any quote targeting it must fail with ConcurrencyLockError
    # Create a dummy quote targeting d1
    from app.services.pricing_service import PricingService
    q2 = PricingService.generate_and_persist_quote(
        requester_id=sample_requester.id,
        drone_id=d1.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        cargo_category="EMERGENCY_MEDICINE",
        priority="HIGH",
        corridor_name="DIRECT_GEODESIC",
        flight_distance_km=5.0,
        ferry_distance_km=0.0,
        estimated_pickup_duration_min=0.0,
        estimated_delivery_duration_min=5.0,
        estimated_energy_wh=50.0,
    )

    with pytest.raises(ConcurrencyLockError):
        DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=q2.id,
            requester_id=sample_requester.id,
        )


def test_weather_hazard_blocks_booking(app, sample_requester, setup_fleet):
    """Verify that RED weather condition strictly blocks booking confirmation."""
    results = DroneAvailabilityService.search_available_drones(
        requester_id=sample_requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        priority="HIGH",
    )
    quote_id = results["available_drones"][0]["quote_id"]

    # Inject severe storm (RED weather)
    WeatherIntelligenceService.set_demonstration_scenario(
        wind_speed_mps=18.0,
        precipitation_mmh=25.0,
        visibility_km=1.0,
    )

    with pytest.raises(InfeasibleBookingError):
        DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=quote_id,
            requester_id=sample_requester.id,
        )

    WeatherIntelligenceService.clear_demonstration_scenario()
