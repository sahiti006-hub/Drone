import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestPriority, RequestStatus, EmergencyType
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.services.simulation_service import SimulationService


def test_security_headers_present_on_all_responses(client):
    """Verify that essential defensive HTTP headers are attached to responses."""
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "1; mode=block" in resp.headers.get("X-XSS-Protection", "")
    assert "default-src 'self'" in resp.headers.get("Content-Security-Policy", "")
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_api_error_handler_returns_json_and_prevents_leakage(client):
    """Ensure API requests to invalid endpoints yield clean JSON error payloads without stack traces."""
    resp = client.get("/api/nonexistent-route", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    data = resp.get_json()
    assert data is not None
    assert "error" in data
    assert "not found" in data["error"].lower()
    assert "traceback" not in data


def test_password_hashing_security():
    """Verify passwords are strongly hashed and plaintext is never stored."""
    user = User("Doctor Alice", "alice@hospital.org", "SuperSecretPass!123", UserRole.REQUESTER)
    assert user.password_hash != "SuperSecretPass!123"
    assert len(user.password_hash) >= 40
    assert user.check_password("SuperSecretPass!123") is True
    assert user.check_password("WrongPass") is False


def test_sql_injection_attempt_in_login(client):
    """Ensure SQL injection strings cannot bypass authentication or manipulate queries."""
    user = User("Admin User", "admin@rescue.org", "Pass12345!", UserRole.ADMIN)
    db.session.add(user)
    db.session.commit()

    injection_email = "' OR '1'='1"
    resp = client.post("/login", data={"email": injection_email, "password": "any"}, follow_redirects=True)
    assert resp.status_code in (200, 401)
    assert b"Invalid email or password" in resp.data

    with client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_idor_requester_cannot_access_other_users_request(client):
    """Verify Insecure Direct Object Reference (IDOR) protection: Requesters cannot view another user's request."""
    user_a = User("Requester A", "user_a@domain.com", "Password123!", UserRole.REQUESTER)
    user_b = User("Requester B", "user_b@domain.com", "Password123!", UserRole.REQUESTER)
    db.session.add_all([user_a, user_b])
    db.session.commit()

    req_b = DeliveryRequest(
        requester_id=user_b.id,
        emergency_type=EmergencyType.EMERGENCY_MEDICINE.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.439930,
        destination_longitude=78.390830,
        payload_weight_kg=2.5,
        priority=RequestPriority.HIGH.value,
    )
    db.session.add(req_b)
    db.session.commit()

    # Login as User A
    with client.session_transaction() as sess:
        sess["user_id"] = user_a.id
        sess["user_role"] = UserRole.REQUESTER.value

    # Attempt to view User B's request
    resp = client.get(f"/requests/{req_b.id}")
    assert resp.status_code == 403


def test_role_authorization_drone_inventory_restricted(client):
    """Ensure Requesters cannot access administrative drone management routes."""
    requester = User("Requester User", "requester@domain.com", "Password123!", UserRole.REQUESTER)
    db.session.add(requester)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = UserRole.REQUESTER.value

    # Requesters trying to view drone creation route
    resp = client.get("/drones/new")
    assert resp.status_code == 403


def test_identical_pickup_destination_rejected():
    """Verify geospatial input validation prevents identical pickup and destination coordinates."""
    with pytest.raises(ValueError, match="Pickup and destination cannot be identical locations"):
        DeliveryRequest(
            requester_id=1,
            emergency_type=EmergencyType.BLOOD_SUPPLY.value,
            pickup_latitude=17.385000,
            pickup_longitude=78.486000,
            destination_latitude=17.385000,
            destination_longitude=78.486000,
            payload_weight_kg=1.5,
            priority=RequestPriority.CRITICAL.value,
        )


def test_payload_exceeding_safety_limit_rejected():
    """Verify input validation rejects cargo payloads greater than 100kg."""
    with pytest.raises(ValueError, match="Payload weight exceeds maximum supported emergency drone payload"):
        DeliveryRequest(
            requester_id=1,
            emergency_type=EmergencyType.BLOOD_SUPPLY.value,
            pickup_latitude=17.385000,
            pickup_longitude=78.486000,
            destination_latitude=17.440000,
            destination_longitude=78.390000,
            payload_weight_kg=120.0,
            priority=RequestPriority.CRITICAL.value,
        )


def test_negative_drone_cruise_speed_rejected():
    """Verify drone hardware model rejects non-positive cruise speeds."""
    with pytest.raises(ValueError, match="Cruise speed must be greater than zero"):
        Drone(
            drone_code="FAIL-DRONE",
            model_name="Faulty Model",
            maximum_payload_kg=5.0,
            battery_capacity_wh=500.0,
            cruise_speed_kmh=0.0,
        )


def test_simulation_authorization_and_checkpoint_validation(client):
    """Verify simulation routes enforce Operator authorization and reject invalid kinematic telemetry."""
    operator = User("Operator Jane", "op_jane@rescue.org", "Pass12345!", UserRole.OPERATOR.value)
    requester = User("Requester Bob", "req_bob@rescue.org", "Pass12345!", UserRole.REQUESTER.value)
    drone = Drone(
        drone_code="DRONE-SEC-01",
        model_name="Lifeline Hexa",
        maximum_payload_kg=5.0,
        battery_capacity_wh=600.0,
        cruise_speed_kmh=60.0,
    )
    db.session.add_all([operator, requester, drone])
    db.session.commit()

    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.439930,
        destination_longitude=78.390830,
        payload_weight_kg=2.0,
        priority=RequestPriority.HIGH.value,
    )
    db.session.add(req)
    db.session.commit()

    route = Route(
        delivery_request_id=req.id,
        algorithm_name="A_STAR",
        estimated_distance_km=12.5,
        estimated_duration_minutes=12.5,
        estimated_energy_wh=60.0,
        feasibility_status=FeasibilityStatus.FEASIBLE.value,
    )
    db.session.add(route)
    db.session.commit()

    wps = [
        RouteWaypoint(route.id, 0, 17.385044, 78.486671, 50.0),
        RouteWaypoint(route.id, 1, 17.439930, 78.390830, 25.0),
    ]
    db.session.add_all(wps)
    db.session.commit()

    assignment = DroneAssignment(
        delivery_request_id=req.id,
        drone_id=drone.id,
        route_id=route.id,
        status=AssignmentStatus.ACTIVE.value,
    )
    db.session.add(assignment)
    db.session.commit()

    sim = SimulationService.get_or_create_simulation(assignment.id)
    sim = SimulationService.start_simulation(sim.id)

    # 1. Requester attempting to pause receives 403
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = UserRole.REQUESTER.value

    resp = client.post(f"/simulation/api/{sim.id}/pause")
    assert resp.status_code == 403

    # 2. Operator sending out-of-bounds latitude (999.0) receives 400 Bad Request
    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    bad_resp = client.post(
        f"/simulation/api/{sim.id}/checkpoint",
        json={
            "latitude": 999.0,  # Invalid
            "longitude": 78.486,
            "altitude_m": 50.0,
            "progress_percent": 10.0,
        },
        headers={"Accept": "application/json"}
    )
    assert bad_resp.status_code == 400
    bad_data = bad_resp.get_json()
    assert bad_data["success"] is False
    assert "Must be between -90 and +90" in bad_data["error"]
