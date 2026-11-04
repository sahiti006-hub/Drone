import pytest
from datetime import datetime, timezone
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.services.simulation_service import SimulationService
from app.services.drone_availability_service import DroneAvailabilityService
from app.extensions import db


@pytest.fixture
def test_booking(app):
    with app.app_context():
        user = User.query.filter_by(email="requester.live@example.com").first()
        if not user:
            user = User("Live Drone Tester", "requester.live@example.com", "Password123!", UserRole.REQUESTER.value)
            db.session.add(user)
            db.session.commit()

        drone = Drone.query.filter_by(drone_code="DRN-TEST-SIM").first()
        if not drone:
            drone = Drone("DRN-TEST-SIM", "Matrice 350 RTK", 4.5, 500.0, 500.0, 80.0, DroneStatus.AVAILABLE.value)
            drone.current_latitude = 12.9716
            drone.current_longitude = 77.5946
            db.session.add(drone)
            db.session.commit()

        search_res = DroneAvailabilityService.search_available_drones(
            pickup_lat=12.9716,
            pickup_lng=77.5946,
            dest_lat=13.0350,
            dest_lng=77.6500,
            cargo_weight_kg=1.2,
            cargo_category="DOCUMENTS_OFFICE",
            priority="HIGH",
            requester_id=user.id,
            delivery_direction="SEND",
        )
        assert len(search_res["available_drones"]) >= 1
        quote_id = search_res["available_drones"][0]["quote_id"]

        booking = DroneAvailabilityService.confirm_and_lock_booking(
            quote_id=quote_id,
            requester_id=user.id,
            weather_acknowledged=True,
            delivery_direction="SEND",
        )
        booking.status = BookingStatus.DISPATCHED.value
        db.session.commit()
        booking_id = booking.id

        yield booking_id


def test_get_or_create_simulation_for_booking(app, test_booking):
    with app.app_context():
        sim_run = SimulationService.get_or_create_simulation_for_booking(test_booking)
        assert sim_run is not None
        assert sim_run.assignment_id is not None
        assert sim_run.status in [SimulationStatus.CREATED.value, SimulationStatus.RUNNING.value, SimulationStatus.COMPLETED.value]


def test_simulation_tick_and_kinematics(app, test_booking):
    with app.app_context():
        sim_run = SimulationService.start_booking_simulation(test_booking)
        assert sim_run.status == SimulationStatus.RUNNING.value
        start_ts = sim_run.get_checkpoint().get("last_tick_timestamp") or (
            sim_run.start_time if sim_run.start_time.tzinfo else sim_run.start_time.replace(tzinfo=timezone.utc)
        ).timestamp()

        # Tick 1: Initial progression
        t1 = SimulationService.tick_simulation_for_booking(test_booking, start_ts + 10)
        assert t1 is not None
        assert t1["simulation_status"] == "RUNNING"
        assert t1["speed_multiplier"] == 1.0
        assert 0.0 <= t1["heading_deg"] <= 360.0
        assert t1["distance_travelled_km"] >= 0.0
        assert t1["progress_percentage"] >= 0.0
        assert t1["battery_percentage"] <= 100.0

        # Tick 2: Accelerated time tick
        t2 = SimulationService.tick_simulation_for_booking(test_booking, start_ts + 60)
        assert t2["distance_travelled_km"] > t1["distance_travelled_km"]
        assert t2["progress_percentage"] > t1["progress_percentage"]
        assert len(t2["completed_path"]) >= 1
        assert len(t2["remaining_path"]) >= 1


def test_simulation_controls_state_machine(app, test_booking):
    with app.app_context():
        # Start
        sim = SimulationService.start_booking_simulation(test_booking)
        assert sim.status == SimulationStatus.RUNNING.value

        # Speed Change
        sim = SimulationService.set_booking_simulation_speed(test_booking, 2.0)
        assert sim.speed_multiplier == 2.0

        # Pause
        sim = SimulationService.pause_booking_simulation(test_booking)
        assert sim.status == SimulationStatus.PAUSED.value

        # Resume
        sim = SimulationService.resume_booking_simulation(test_booking)
        assert sim.status == SimulationStatus.RUNNING.value

        # Reset
        sim = SimulationService.reset_booking_simulation(test_booking)
        assert sim.status == SimulationStatus.CREATED.value
        assert sim.distance_covered_km == 0.0


def test_simulation_completion_at_destination(app, test_booking):
    with app.app_context():
        sim = SimulationService.start_booking_simulation(test_booking)
        start_ts = sim.get_checkpoint().get("last_tick_timestamp") or (
            sim.start_time if sim.start_time.tzinfo else sim.start_time.replace(tzinfo=timezone.utc)
        ).timestamp()
        # Advance clock by 7200 seconds (2 hours, well beyond flight distance)
        telemetry = SimulationService.tick_simulation_for_booking(test_booking, start_ts + 7200)
        assert telemetry["simulation_status"] == SimulationStatus.COMPLETED.value
        assert telemetry["progress_percentage"] == 100.0
        assert telemetry["distance_remaining_km"] == 0.0


def test_telemetry_routes_api(client, app, test_booking):
    with app.app_context():
        booking = db.session.get(DroneBooking, test_booking)
        ref = booking.booking_reference
        user_email = booking.requester.email

    # Login
    client.post("/login", data={"email": user_email, "password": "Password123!"})

    # Telemetry endpoint
    resp = client.get(f"/booking/{test_booking}/telemetry")
    assert resp.status_code == 200
    res_json = resp.get_json()
    assert res_json["status"] == "success"
    data = res_json.get("data", res_json)
    assert "current_latitude" in data
    assert "heading_deg" in data
    assert "completed_path" in data

    # Controls via API
    resp_pause = client.post(f"/booking/{test_booking}/simulation/pause")
    assert resp_pause.status_code == 200
    assert resp_pause.get_json()["status"] == "success"

    resp_speed = client.post(f"/booking/{test_booking}/simulation/speed", json={"speed": 5.0})
    assert resp_speed.status_code == 200
    assert resp_speed.get_json()["speed"] == 5.0

    resp_reset = client.post(f"/booking/{test_booking}/simulation/reset")
    assert resp_reset.status_code == 200

    # Public tracking telemetry
    pub_resp = client.get(f"/booking/track/{ref}/telemetry")
    assert pub_resp.status_code == 200
    assert pub_resp.get_json()["status"] == "success"
