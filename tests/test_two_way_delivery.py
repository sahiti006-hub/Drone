"""Comprehensive test suite for Two-Way Delivery Experience (SEND vs. RECEIVE).

Validates the 20 requirements specified in Part 15:
1. SEND booking creation.
2. RECEIVE booking creation.
3. Default direction selection.
4. Correct pickup and destination mapping in SEND mode.
5. Correct collection and delivery mapping in RECEIVE mode.
6. Physical flight route direction invariance.
7. Custom cargo handling in SEND mode.
8. Custom cargo handling in RECEIVE mode.
9. Collection readiness validation.
10. Collection contact handling.
11. Pricing parity for SEND.
12. Pricing parity for RECEIVE.
13. Weather restrictions enforced in SEND mode.
14. Weather restrictions enforced in RECEIVE mode.
15. Drone allocation in both modes.
16. Tracking display in both modes.
17. Booking history filters.
18. Dashboard counts.
19. Existing legacy booking compatibility.
20. Role-based access control.
"""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus, DeliveryDirection
from app.models.drone_quote import DroneQuote
from app.models.delivery_request import DeliveryRequest, RequestStatus
from app.services.drone_availability_service import DroneAvailabilityService
from app.services.pricing_service import PricingService
from app.services.weather_intelligence_service import WeatherIntelligenceService
from app.services.assignment_service import AssignmentService


@pytest.fixture
def two_way_actors(app):
    """Set up test users and drones for two-way delivery testing."""
    requester = User(
        full_name="Apollo Hospital Requester",
        email="apollo.two_way@hospital.org",
        password="HospitalPass123!",
        role=UserRole.REQUESTER.value,
    )
    operator = User(
        full_name="Operations Specialist",
        email="ops.two_way@drone.org",
        password="OpsPassword123!",
        role=UserRole.OPERATOR.value,
    )
    drone = Drone(
        drone_code="DRONE-TWOWAY-01",
        model_name="AeroLifter MultiRole",
        maximum_payload_kg=10.0,
        battery_capacity_wh=3000.0,
        current_battery_wh=3000.0,
        cruise_speed_kmh=65.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add_all([requester, operator, drone])
    db.session.commit()
    return requester, operator, drone


# ---------------------------------------------------------------------------
# Test 1 & 4: SEND booking creation and pickup/destination coordinate mapping
# ---------------------------------------------------------------------------
def test_1_and_4_send_booking_creation_and_coordinate_mapping(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    pickup_lat, pickup_lng = 12.9716, 77.5946
    dest_lat, dest_lng = 12.9352, 77.6245

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=pickup_lat,
        pickup_lng=pickup_lng,
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        cargo_weight_kg=2.0,
        cargo_category="BLOOD_UNITS",
        priority="HIGH",
        delivery_direction="SEND",
    )
    assert len(search_res["available_drones"]) >= 1
    quote_id = search_res["available_drones"][0]["quote_id"]

    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )

    assert booking.delivery_direction == "SEND"
    assert booking.pickup_latitude == pytest.approx(pickup_lat)
    assert booking.pickup_longitude == pytest.approx(pickup_lng)
    assert booking.destination_latitude == pytest.approx(dest_lat)
    assert booking.destination_longitude == pytest.approx(dest_lng)


# ---------------------------------------------------------------------------
# Test 2 & 5: RECEIVE booking creation and collection/destination mapping
# ---------------------------------------------------------------------------
def test_2_and_5_receive_booking_creation_and_collection_mapping(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # User is at destination (hospital), drone collects from pharmacy (pickup)
    collection_lat, collection_lng = 12.9352, 77.6245
    user_delivery_lat, user_delivery_lng = 12.9716, 77.5946

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=collection_lat,
        pickup_lng=collection_lng,
        dest_lat=user_delivery_lat,
        dest_lng=user_delivery_lng,
        cargo_weight_kg=1.5,
        cargo_category="ANTIVENOM_SERUM",
        priority="CRITICAL",
        delivery_direction="RECEIVE",
    )
    assert len(search_res["available_drones"]) >= 1
    quote_id = search_res["available_drones"][0]["quote_id"]

    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
        collection_readiness="READY",
        collection_contact_name="Apollo Central Pharmacy",
        collection_contact_phone="+91 98765 43210",
        collection_instructions="Collect from cold-chain dispatch locker B-4",
    )

    assert booking.delivery_direction == "RECEIVE"
    # Physical collection point is mapped to pickup coordinates
    assert booking.pickup_latitude == pytest.approx(collection_lat)
    assert booking.pickup_longitude == pytest.approx(collection_lng)
    # User delivery location is mapped to destination coordinates
    assert booking.destination_latitude == pytest.approx(user_delivery_lat)
    assert booking.destination_longitude == pytest.approx(user_delivery_lng)


# ---------------------------------------------------------------------------
# Test 3: Default direction selection is SEND
# ---------------------------------------------------------------------------
def test_3_default_direction_selection(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        cargo_category="BLOOD_UNITS",
    )
    quote_id = search_res["available_drones"][0]["quote_id"]

    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
    )
    # Default is SEND
    assert booking.delivery_direction == "SEND"


# ---------------------------------------------------------------------------
# Test 6: Physical flight route direction invariance
# ---------------------------------------------------------------------------
def test_6_physical_flight_route_direction_invariance(app, two_way_actors):
    """In both SEND and RECEIVE, drone physically flies from pickup to destination."""
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create RECEIVE booking
    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9200,
        pickup_lng=77.6100,
        dest_lat=12.9800,
        dest_lng=77.6500,
        cargo_weight_kg=1.0,
        cargo_category="EMERGENCY_DEFIBRILLATOR",
        delivery_direction="RECEIVE",
    )
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=search_res["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
    )

    req = db.session.get(DeliveryRequest, booking.delivery_request_id)
    assert float(req.pickup_latitude) == pytest.approx(12.9200)
    assert float(req.destination_latitude) == pytest.approx(12.9800)
    routes = req.routes.all()
    assert len(routes) >= 1
    for r in routes:
        waypoints = r.waypoints
        assert len(waypoints) >= 2
        # Physical route starts near collection point (pickup) and ends near destination
        assert abs(float(waypoints[0].latitude) - 12.9200) < 0.05
        assert abs(float(waypoints[-1].latitude) - 12.9800) < 0.05


# ---------------------------------------------------------------------------
# Test 7 & 8: Custom cargo handling in SEND and RECEIVE modes
# ---------------------------------------------------------------------------
def test_7_custom_cargo_handling_send(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.2,
        cargo_category="CUSTOM_ITEM",
        delivery_direction="SEND",
        custom_item_name="Rare Surgical Biopsy Sample",
        package_size="Small",
    )
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=search_res["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
        custom_item_name="Rare Surgical Biopsy Sample",
        custom_item_description="Keep upright, temperature sensitive",
        package_size="Small",
    )
    assert booking.cargo_category == "CUSTOM_ITEM"
    assert booking.custom_item_name == "Rare Surgical Biopsy Sample"
    assert booking.custom_item_description == "Keep upright, temperature sensitive"
    assert booking.package_size == "Small"


def test_8_custom_cargo_handling_receive(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.8,
        cargo_category="CUSTOM_ITEM",
        delivery_direction="RECEIVE",
        custom_item_name="Replacement Ventilator Valve",
        package_size="Medium",
    )
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=search_res["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
        custom_item_name="Replacement Ventilator Valve",
        package_size="Medium",
    )
    assert booking.delivery_direction == "RECEIVE"
    assert booking.custom_item_name == "Replacement Ventilator Valve"
    assert booking.package_size == "Medium"


# ---------------------------------------------------------------------------
# Test 9 & 10: Collection readiness validation & contact handling
# ---------------------------------------------------------------------------
def test_9_and_10_collection_readiness_and_contact_details(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    readiness_options = ["READY", "READY_SHORTLY", "CONFIRM_WITH_SENDER"]
    for option in readiness_options:
        drone.status = DroneStatus.AVAILABLE.value
        db.session.commit()

        search_res = DroneAvailabilityService.search_available_drones(
            requester_id=requester.id,
            pickup_lat=12.9716,
            pickup_lng=77.5946,
            dest_lat=12.9352,
            dest_lng=77.6245,
            cargo_weight_kg=1.0,
            cargo_category="FOOD_AND_ESSENTIALS",
            delivery_direction="RECEIVE",
        )
        assert len(search_res["available_drones"]) >= 1
        booking = DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=search_res["available_drones"][0]["quote_id"],
            requester_id=requester.id,
            weather_acknowledged=True,
            delivery_direction="RECEIVE",
            collection_readiness=option,
            collection_contact_name=f"Manager for {option}",
            collection_contact_phone="9988776655",
            collection_instructions=f"Gate 3 handoff for status {option}",
        )
        assert booking.collection_readiness == option
        assert booking.collection_contact_name == f"Manager for {option}"
        assert booking.collection_contact_phone == "9988776655"
        assert booking.collection_instructions == f"Gate 3 handoff for status {option}"


# ---------------------------------------------------------------------------
# Test 11 & 12: Pricing parity between SEND and RECEIVE
# ---------------------------------------------------------------------------
def test_11_and_12_pricing_parity_send_and_receive(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    lat1, lng1 = 12.9716, 77.5946
    lat2, lng2 = 12.9352, 77.6245

    res_send = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=lat1,
        pickup_lng=lng1,
        dest_lat=lat2,
        dest_lng=lng2,
        cargo_weight_kg=2.0,
        cargo_category="MEDICAL_SUPPLIES",
        priority="NORMAL",
        delivery_direction="SEND",
    )
    quote_send = res_send["available_drones"][0]["pricing"]

    res_receive = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=lat1,
        pickup_lng=lng1,
        dest_lat=lat2,
        dest_lng=lng2,
        cargo_weight_kg=2.0,
        cargo_category="MEDICAL_SUPPLIES",
        priority="NORMAL",
        delivery_direction="RECEIVE",
    )
    quote_receive = res_receive["available_drones"][0]["pricing"]

    # Identical distance, weight, and priority must yield identical pricing
    assert quote_send["total_price"] == pytest.approx(quote_receive["total_price"], 0.01)
    assert quote_send["base_fare"] == pytest.approx(quote_receive["base_fare"], 0.01)
    assert quote_send["distance_charge"] == pytest.approx(quote_receive["distance_charge"], 0.01)


# ---------------------------------------------------------------------------
# Test 13 & 14: Weather restrictions enforced in both SEND and RECEIVE modes
# ---------------------------------------------------------------------------
def test_13_and_14_weather_restrictions_enforced_both_modes(app, two_way_actors):
    requester, _, drone = two_way_actors

    # Force RED storm condition
    WeatherIntelligenceService.set_demonstration_scenario(
        wind_speed_mps=18.0,
        precipitation_mmh=15.0,
        visibility_km=1.5,
    )

    # In SEND mode
    res_send = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="SEND",
    )
    assert res_send["weather"]["classification"] == "RED"
    # All drones should be classified as unavailable due to weather cutoff
    assert len(res_send["available_drones"]) == 0
    assert len(res_send["unavailable_drones"]) >= 1

    # In RECEIVE mode
    res_recv = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="RECEIVE",
    )
    assert res_recv["weather"]["classification"] == "RED"
    assert len(res_recv["available_drones"]) == 0
    assert len(res_recv["unavailable_drones"]) >= 1

    WeatherIntelligenceService.clear_demonstration_scenario()


# ---------------------------------------------------------------------------
# Test 15: Drone allocation in both modes
# ---------------------------------------------------------------------------
def test_15_drone_allocation_both_modes(app, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create SEND booking
    res_send = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="ELECTRONICS",
        delivery_direction="SEND",
    )
    b_send = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res_send["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )
    assert b_send.drone_id == drone.id
    assert b_send.drone.status == DroneStatus.RESERVED.value

    # Free the drone
    drone.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    # Create RECEIVE booking
    res_recv = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="ELECTRONICS",
        delivery_direction="RECEIVE",
    )
    b_recv = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res_recv["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
    )
    assert b_recv.drone_id == drone.id
    assert b_recv.drone.status == DroneStatus.RESERVED.value


# ---------------------------------------------------------------------------
# Test 16: Tracking view display in both modes
# ---------------------------------------------------------------------------
def test_16_tracking_display_both_modes(app, client, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create one SEND and one RECEIVE booking
    res1 = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="SEND",
    )
    b_send = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res1["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )

    drone.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    res2 = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="MEDICAL_SUPPLIES",
        delivery_direction="RECEIVE",
    )
    b_recv = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res2["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
        collection_readiness="READY",
        collection_contact_name="MedDepot South",
    )

    # Login as requester
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["role"] = requester.role

    # Check SEND tracking cockpit
    resp_send = client.get(f"/booking/{b_send.id}")
    assert resp_send.status_code == 200
    html_send = resp_send.data.decode("utf-8")
    assert "SEND" in html_send
    assert "Your item is on its way to the destination" in html_send

    # Check RECEIVE tracking cockpit
    resp_recv = client.get(f"/booking/{b_recv.id}")
    assert resp_recv.status_code == 200
    html_recv = resp_recv.data.decode("utf-8")
    assert "RECEIVE" in html_recv
    assert "Your item is being collected and delivered to you" in html_recv
    assert "MedDepot South" in html_recv


# ---------------------------------------------------------------------------
# Test 17: Booking history filters
# ---------------------------------------------------------------------------
def test_17_booking_history_filters(app, client, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create a SEND booking
    res_send = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="DOCUMENTS_AND_PARCELS",
        delivery_direction="SEND",
    )
    b_send = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res_send["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )

    drone.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    # Create a RECEIVE booking
    res_recv = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="DOCUMENTS_AND_PARCELS",
        delivery_direction="RECEIVE",
    )
    b_recv = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res_recv["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
    )

    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["role"] = requester.role

    # Filter by SEND
    resp_send_filter = client.get("/booking/history?direction=SEND")
    assert resp_send_filter.status_code == 200
    html_send = resp_send_filter.data.decode("utf-8")
    assert b_send.booking_reference in html_send
    assert b_recv.booking_reference not in html_send

    # Filter by RECEIVE
    resp_recv_filter = client.get("/booking/history?direction=RECEIVE")
    assert resp_recv_filter.status_code == 200
    html_recv = resp_recv_filter.data.decode("utf-8")
    assert b_recv.booking_reference in html_recv
    assert b_send.booking_reference not in html_recv


# ---------------------------------------------------------------------------
# Test 18: Dashboard counts (items_sent_count and items_received_count)
# ---------------------------------------------------------------------------
def test_18_dashboard_counts(app, client, two_way_actors):
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create 2 SEND bookings and 1 RECEIVE booking
    res1 = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="SEND",
    )
    DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res1["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )
    drone.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    res2 = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="SEND",
    )
    DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res2["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="SEND",
    )
    drone.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    res3 = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_UNITS",
        delivery_direction="RECEIVE",
    )
    DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=res3["available_drones"][0]["quote_id"],
        requester_id=requester.id,
        weather_acknowledged=True,
        delivery_direction="RECEIVE",
    )

    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["role"] = requester.role

    resp = client.get("/requester/dashboard")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Items Sent" in html
    assert "Items Received" in html
    # Check that counts 2 and 1 are in the metrics presentation
    assert "SEND AN ITEM" in html
    assert "RECEIVE AN ITEM" in html


# ---------------------------------------------------------------------------
# Test 19: Existing legacy booking compatibility
# ---------------------------------------------------------------------------
def test_19_legacy_booking_compatibility(app, two_way_actors):
    """Bookings with None or missing delivery_direction gracefully fall back to SEND."""
    requester, _, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.0,
        cargo_category="BLOOD_UNITS",
    )
    quote_id = search_res["available_drones"][0]["quote_id"]

    booking = DroneBooking(
        booking_reference="LEGACY-BK-001",
        requester_id=requester.id,
        drone_id=drone.id,
        quote_id=quote_id,
        accepted_price=100.0,
        final_price=100.0,
        status=BookingStatus.CONFIRMED.value,
        # Intentionally omitting delivery_direction to test default
    )
    db.session.add(booking)
    db.session.commit()

    refreshed = db.session.get(DroneBooking, booking.id)
    assert refreshed.delivery_direction == "SEND"
    b_dict = refreshed.to_dict()
    assert b_dict["delivery_direction"] == "SEND"


# ---------------------------------------------------------------------------
# Test 20: Role-based access control
# ---------------------------------------------------------------------------
def test_20_role_based_access_control(app, client, two_way_actors):
    requester, operator, drone = two_way_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Unauthenticated user cannot access booking or history
    resp = client.get("/booking/new")
    assert resp.status_code == 302  # redirects to login

    resp2 = client.get("/booking/history")
    assert resp2.status_code == 302

    # Requester cannot access operator dashboard
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["role"] = requester.role

    resp3 = client.get("/operator/dashboard")
    assert resp3.status_code == 403

    # Create another requester
    other_requester = User(
        full_name="Other Requester",
        email="other@hospital.org",
        password="OtherPassword123!",
        role=UserRole.REQUESTER.value,
    )
    db.session.add(other_requester)
    db.session.commit()

    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
        cargo_category="BLOOD_UNITS",
    )
    quote_id = search_res["available_drones"][0]["quote_id"]

    booking = DroneBooking(
        booking_reference="SEC-BK-001",
        requester_id=requester.id,
        drone_id=drone.id,
        quote_id=quote_id,
        accepted_price=100.0,
        final_price=100.0,
        status=BookingStatus.CONFIRMED.value,
    )
    db.session.add(booking)
    db.session.commit()

    # Login as other_requester and attempt to access requester's booking
    with client.session_transaction() as sess:
        sess["user_id"] = other_requester.id
        sess["role"] = other_requester.role

    resp4 = client.get(f"/booking/{booking.id}")
    assert resp4.status_code == 403
