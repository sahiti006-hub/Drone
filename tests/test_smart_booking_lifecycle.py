"""Comprehensive end-to-end integration test for the Uber/Rapido-style drone booking lifecycle."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus
from app.models.payment_transaction import PaymentStatus
from app.models.notification import Notification
from app.services.drone_availability_service import DroneAvailabilityService
from app.services.payment_service import PaymentService
from app.services.weather_intelligence_service import WeatherIntelligenceService
from app.services.assignment_service import AssignmentService
from app.services.simulation_service import SimulationService


@pytest.fixture
def lifecycle_actors(app):
    requester = User(
        full_name="Apollo Hospital Requester",
        email="dispatch@apollo.org",
        password="HospitalPass123!",
        role=UserRole.REQUESTER.value,
    )
    operator = User(
        full_name="Flight Controller One",
        email="ops1@dronenet.org",
        password="OpsPassword123!",
        role=UserRole.OPERATOR.value,
    )
    drone = Drone(
        drone_code="DRONE-LIFE-01",
        model_name="SkyLifter Heavy Duty",
        maximum_payload_kg=8.0,
        battery_capacity_wh=2500.0,
        current_battery_wh=2500.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add_all([requester, operator, drone])
    db.session.commit()
    return requester, operator, drone


def test_full_successful_booking_to_delivery_lifecycle(app, lifecycle_actors):
    """End-to-end flow: Search -> Quote -> Lock -> Pay -> Dispatch -> Simulate Delivery -> Invoice."""
    requester, operator, drone = lifecycle_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # STEP 1: Search available fleet
    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=2.5,
        cargo_category="ANTIVENOM_SERUM",
        priority="CRITICAL",
    )
    assert len(search_res["available_drones"]) >= 1
    selected_card = search_res["available_drones"][0]
    quote_id = selected_card["quote_id"]

    # STEP 2: Atomic confirmation & locking
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
        weather_acknowledged=True,
        notes="Urgent snake bite antivenom transit.",
    )
    assert booking.id is not None
    assert booking.status == BookingStatus.CONFIRMED.value
    assert booking.drone.status == DroneStatus.RESERVED.value
    assert booking.delivery_request_id is not None

    # Verify notification created
    notifs = Notification.query.filter_by(booking_id=booking.id).all()
    assert len(notifs) >= 1
    assert any(n.notification_type == "BOOKING_CONFIRMED" for n in notifs)

    # STEP 3: Cashless simulated payment
    pay_txn = PaymentService.process_payment(
        booking_id=booking.id,
        payment_method="SIMULATED_UPI",
    )
    assert pay_txn.payment_status == PaymentStatus.PAID.value
    assert booking.status == BookingStatus.PAID.value

    # STEP 4: Dispatch by operator
    # Link route to delivery request
    del_req = db.session.get(DeliveryRequest, booking.delivery_request_id)
    routes = del_req.routes.all()
    assert len(routes) >= 1
    chosen_route = routes[0]

    assignment = AssignmentService.create_assignment(
        delivery_request_id=del_req.id,
        drone_id=drone.id,
        route_id=chosen_route.id,
    )
    assert assignment.id is not None
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # STEP 5: Start and step flight simulation to completion
    sim = SimulationService.get_or_create_simulation(assignment_id=assignment.id)
    sim = SimulationService.start_simulation(simulation_id=sim.id)
    assert sim.status == "RUNNING"

    # Step large delta to reach 100% progress
    step_res = SimulationService.step_simulation(
        simulation_id=sim.id,
        delta_sim_seconds=600.0,
        speed_multiplier=5.0,
    )
    assert step_res["is_completed"] is True

    # STEP 6: Verify final post-delivery state
    db.session.refresh(booking)
    assert booking.status == BookingStatus.DELIVERED.value
    assert del_req.status == RequestStatus.DELIVERED.value

    # STEP 7: Verify final tax invoice
    invoice = PaymentService.generate_invoice(booking.id)
    assert invoice["payment_status"] == PaymentStatus.PAID.value
    assert invoice["mission"]["status"] == BookingStatus.DELIVERED.value
    assert invoice["itemized_charges"]["gross_total"] > 0


def test_in_flight_weather_hazard_triggers_safety_action(app, lifecycle_actors):
    """Verify that in-flight severe RED weather triggers dynamic safety action on the active booking."""
    requester, operator, drone = lifecycle_actors
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Create and pay booking
    search_res = DroneAvailabilityService.search_available_drones(
        requester_id=requester.id,
        pickup_lat=12.9716,
        pickup_lng=77.5946,
        dest_lat=12.9352,
        dest_lng=77.6245,
        cargo_weight_kg=1.0,
    )
    quote_id = search_res["available_drones"][0]["quote_id"]
    booking = DroneAvailabilityService.confirm_and_lock_booking(
        quote_id=quote_id,
        requester_id=requester.id,
    )
    PaymentService.process_payment(booking_id=booking.id)

    # Dispatch
    del_req = db.session.get(DeliveryRequest, booking.delivery_request_id)
    routes = del_req.routes.all()
    assignment = AssignmentService.create_assignment(
        delivery_request_id=del_req.id,
        drone_id=drone.id,
        route_id=routes[0].id,
    )

    # Start simulation
    sim = SimulationService.get_or_create_simulation(assignment_id=assignment.id)
    sim = SimulationService.start_simulation(simulation_id=sim.id)

    # Step partially along the corridor (e.g. 50 seconds)
    step1 = SimulationService.step_simulation(sim.id, delta_sim_seconds=30.0, speed_multiplier=1.0)
    assert step1["is_completed"] is False

    # Inject severe storm (RED weather)
    WeatherIntelligenceService.set_demonstration_scenario(
        wind_speed_mps=18.0,
        precipitation_mmh=25.0,
        visibility_km=1.0,
        summary="Severe squall squall line encountered during flight",
    )

    # Step simulation again with severe weather present
    step2 = SimulationService.step_simulation(sim.id, delta_sim_seconds=10.0, speed_multiplier=1.0)
    safety = step2["weather_safety"]
    assert safety is not None
    assert safety["classification"] == "RED"
    assert safety["action_taken"] in ("DYNAMIC_REROUTE_EXECUTED", "EMERGENCY_DIVERSION_INITIATED", "SEVERE_WEATHER_HAZARD")

    WeatherIntelligenceService.clear_demonstration_scenario()
