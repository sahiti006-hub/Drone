"""Automated test suite for UI/UX redesign, saved locations, ratings, and sidebar persistence."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.saved_location import SavedLocation
from app.models.delivery_rating import DeliveryRating
from app.services.drone_availability_service import DroneAvailabilityService
from app.services.weather_intelligence_service import WeatherIntelligenceService


@pytest.fixture
def auth_users(app):
    admin = User("Admin Chief", "chief_admin@dispatch.org", "ChiefAdminPass123!", UserRole.ADMIN)
    operator = User("Ops Controller", "ops_controller@dispatch.org", "OpsPass123!", UserRole.OPERATOR)
    requester = User("Dr. Requester", "doctor@hospital.org", "DoctorPass123!", UserRole.REQUESTER)
    db.session.add_all([admin, operator, requester])
    db.session.commit()
    return {"admin": admin, "operator": operator, "requester": requester}


@pytest.fixture
def sample_drone(app):
    drone = Drone(
        drone_code="TEST-DRN-099",
        model_name="DJI Matrice 350 RTK",
        maximum_payload_kg=5.0,
        battery_capacity_wh=2000.0,
        current_battery_wh=2000.0,
        cruise_speed_kmh=65.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add(drone)
    db.session.commit()
    return drone


def test_saved_locations_crud(client, auth_users):
    """Test creating, listing, and deleting saved delivery locations."""
    requester = auth_users["requester"]
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = requester.role

    # 1. List locations (seeds defaults if empty)
    res = client.get("/api/saved-locations")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["locations"]) >= 1

    # 2. Create custom saved location
    new_loc_payload = {
        "label": "St. Philomena Trauma Helipad",
        "location_type": "HOSPITAL",
        "address": "Viveka Nagar, Bangalore",
        "latitude": 12.9550,
        "longitude": 77.6180,
    }
    create_res = client.post("/api/saved-locations", json=new_loc_payload)
    assert create_res.status_code == 201
    created_data = create_res.get_json()
    assert created_data["status"] == "success"
    loc_id = created_data["location"]["id"]
    assert created_data["location"]["label"] == "St. Philomena Trauma Helipad"

    # 3. Delete saved location
    del_res = client.delete(f"/api/saved-locations/{loc_id}")
    assert del_res.status_code == 200
    assert del_res.get_json()["status"] == "success"

    # Verify deleted
    check_loc = db.session.get(SavedLocation, loc_id)
    assert check_loc is None


def test_location_search_autocomplete(client):
    """Test geocode autocomplete returns verified medical landmarks."""
    res = client.get("/api/locations/search?q=victoria")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["results"]) >= 1
    first_match = data["results"][0]
    assert "victoria" in first_match["name"].lower()
    assert first_match["lat"] > 0
    assert first_match["lng"] > 0


def test_quick_fare_and_duration_estimator(client):
    """Test quick price estimator without reserving fleet assets."""
    payload = {
        "pickup_latitude": 12.9716,
        "pickup_longitude": 77.5946,
        "destination_latitude": 12.9352,
        "destination_longitude": 77.6245,
        "cargo_weight_kg": 1.5,
        "priority": "HIGH",
    }
    res = client.post("/api/booking/estimate", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["distance_km"] > 0
    assert data["estimated_duration_min"] > 0
    assert data["estimated_price"] > 0
    assert "base_fare" in data["price_breakdown"]


def test_public_tracking_view(client, auth_users, sample_drone):
    """Test public live tracking endpoint without user login."""
    requester = auth_users["requester"]
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Search & Confirm a booking
    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="EMERGENCY_MEDICINE",
        priority="HIGH",
    )
    quote_id = search_res["available_drones"][0]["quote_id"]
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
    )

    # Access public tracking HUD without session/cookies
    public_res = client.get(f"/booking/track/{booking.booking_reference}")
    assert public_res.status_code == 200
    assert booking.booking_reference.encode() in public_res.data
    assert b"DroneDispatch Live Tracker" in public_res.data
    assert b"Flight Progress Milestones" in public_res.data


def test_post_delivery_rating_submission(client, auth_users, sample_drone):
    """Test submitting post-delivery 5-star customer feedback."""
    requester = auth_users["requester"]
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = requester.role

    # Create and mark booking as DELIVERED
    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_SUPPLY",
        priority="CRITICAL",
    )
    quote_id = search_res["available_drones"][0]["quote_id"]
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
    )
    booking.status = BookingStatus.DELIVERED.value
    db.session.commit()

    # Submit 5-star feedback
    rate_res = client.post(
        f"/booking/{booking.id}/rate",
        json={
            "rating": 5,
            "feedback_text": "Exceptional drone response time. Life-saving blood units received in minutes.",
            "booking_experience_score": 5,
            "speed_score": 5,
        },
    )
    assert rate_res.status_code == 200
    assert rate_res.get_json()["status"] == "success"

    # Verify saved to database
    saved_rating = DeliveryRating.query.filter_by(booking_id=booking.id).first()
    assert saved_rating is not None
    assert saved_rating.rating == 5
    assert "Life-saving" in saved_rating.feedback_text


def test_sidebar_persistence_on_delivery_monitor(client, auth_users):
    """Verify sidebar navigation links are fully preserved across all roles on /analytics/deliveries."""
    for role_name in ["admin", "operator", "requester"]:
        user = auth_users[role_name]
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["user_role"] = user.role

        resp = client.get("/analytics/deliveries")
        assert resp.status_code == 200
        # Check that sidebar navigation exists and has links
        assert b"DroneDispatch" in resp.data
        assert b"sidebar-nav" in resp.data
        assert b"Book Drone" in resp.data
        assert b"Dashboard" in resp.data
        assert b"Delivery Monitor" in resp.data or b"Track Deliveries" in resp.data


def test_new_booking_page_renders_5_steps(client, auth_users):
    """Ensure the new Uber/Rapido-style booking page loads with all 5 workflow steps."""
    requester = auth_users["requester"]
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = requester.role

    resp = client.get("/booking/new")
    assert resp.status_code == 200
    assert b"Where should we pick up your package?" in resp.data
    assert b"Where should we deliver it?" in resp.data
    assert b"What are we sending?" in resp.data
    assert b"Delivery Urgency" in resp.data
    assert b"FIND AVAILABLE DRONES" in resp.data
    assert b"bookingMap" in resp.data
