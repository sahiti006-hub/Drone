import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.route import Route, FeasibilityStatus
from app.services.delivery_service import (
    DeliveryService,
    DeliveryServiceError,
    InvalidRequestStateError,
    DeliveryPermissionDeniedError,
)
from app.services.drone_service import (
    DroneService,
    DroneServiceError,
    InvalidDroneTransitionError,
)
from app.services.assignment_service import AssignmentService


@pytest.fixture
def test_users(app):
    """Fixture creating admin, operator, and two requester users."""
    admin = User("Admin User", "admin_mgm@test.org", "Pass12345!", UserRole.ADMIN)
    operator = User("Operator User", "operator_mgm@test.org", "Pass12345!", UserRole.OPERATOR)
    req1 = User("Requester One", "req1_mgm@test.org", "Pass12345!", UserRole.REQUESTER)
    req2 = User("Requester Two", "req2_mgm@test.org", "Pass12345!", UserRole.REQUESTER)
    db.session.add_all([admin, operator, req1, req2])
    db.session.commit()
    return {"admin": admin, "operator": operator, "req1": req1, "req2": req2}


def test_create_request_valid_and_invalid_coordinates(test_users):
    """Test coordinate boundary enforcement on delivery requests."""
    req1 = test_users["req1"]

    # Valid coordinates
    req = DeliveryService.create_request(
        requester_id=req1.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.0,
        priority=RequestPriority.CRITICAL.value,
        description="Fresh whole blood for surgery",
    )
    assert req.id is not None
    assert req.description == "Fresh whole blood for surgery"

    # Latitude out of bounds (> 90)
    with pytest.raises(ValueError, match="latitude must be between -90.0 and \\+90.0"):
        DeliveryService.create_request(
            requester_id=req1.id,
            emergency_type=EmergencyType.BLOOD_SUPPLY.value,
            pickup_latitude=95.0,
            pickup_longitude=77.5946,
            destination_latitude=12.9352,
            destination_longitude=77.6245,
            payload_weight_kg=2.0,
        )

    # Longitude out of bounds (< -180)
    with pytest.raises(ValueError, match="longitude must be between -180.0 and \\+180.0"):
        DeliveryService.create_request(
            requester_id=req1.id,
            emergency_type=EmergencyType.BLOOD_SUPPLY.value,
            pickup_latitude=12.9716,
            pickup_longitude=-185.0,
            destination_latitude=12.9352,
            destination_longitude=77.6245,
            payload_weight_kg=2.0,
        )


def test_invalid_payload_weight(test_users):
    """Ensure non-positive payload weights are strictly rejected."""
    req1 = test_users["req1"]
    with pytest.raises(ValueError, match="strictly positive"):
        DeliveryService.create_request(
            requester_id=req1.id,
            emergency_type=EmergencyType.ANTIVENOM.value,
            pickup_latitude=12.9716,
            pickup_longitude=77.5946,
            destination_latitude=12.9352,
            destination_longitude=77.6245,
            payload_weight_kg=-1.5,
        )


def test_delivery_request_role_scoping(test_users):
    """Ensure Requesters see only their own requests, while Operators and Admins see all."""
    req1 = test_users["req1"]
    req2 = test_users["req2"]
    operator = test_users["operator"]

    r1 = DeliveryService.create_request(req1.id, EmergencyType.BLOOD_SUPPLY.value, 12.97, 77.59, 12.93, 77.62, 2.0)
    r2 = DeliveryService.create_request(req2.id, EmergencyType.DEFIBRILLATOR.value, 12.97, 77.59, 12.93, 77.62, 3.5)

    # Requester 1 sees only r1
    req1_list = DeliveryService.get_requests_for_user(req1)
    assert len(req1_list) == 1
    assert req1_list[0].id == r1.id

    # Requester 2 sees only r2
    req2_list = DeliveryService.get_requests_for_user(req2)
    assert len(req2_list) == 1
    assert req2_list[0].id == r2.id

    # Operator sees both
    op_list = DeliveryService.get_requests_for_user(operator)
    assert len(op_list) >= 2


def test_delivery_request_cancellation_rules(test_users):
    """Verify request cancellation rules based on state."""
    req1 = test_users["req1"]
    r = DeliveryService.create_request(req1.id, EmergencyType.ANTIVENOM.value, 12.97, 77.59, 12.93, 77.62, 1.2)

    # Can cancel PENDING request
    cancelled = DeliveryService.cancel_request(r.id, user=req1, reason="Patient stabilized")
    assert cancelled.status == RequestStatus.CANCELLED.value
    assert "Patient stabilized" in cancelled.description

    # Delivered request cannot be cancelled
    r2 = DeliveryService.create_request(req1.id, EmergencyType.BLOOD_SUPPLY.value, 12.97, 77.59, 12.93, 77.62, 2.0)
    r2.status = RequestStatus.DELIVERED.value
    db.session.commit()

    with pytest.raises(InvalidRequestStateError, match="already COMPLETED"):
        DeliveryService.cancel_request(r2.id, user=req1)


def test_drone_registration_validation(test_users):
    """Test duplicate drone codes, payload bounds, and battery limits."""
    d1 = DroneService.register_drone("DRONE-DUP-01", "Model X", 5.0, 800.0, 800.0, 60.0)
    assert d1.id is not None

    # Duplicate code rejected
    with pytest.raises(DroneServiceError, match="already exists"):
        DroneService.register_drone("DRONE-DUP-01", "Model Y", 4.0, 700.0)

    # Negative payload rejected
    with pytest.raises(ValueError, match="payload capacity must be positive"):
        DroneService.register_drone("DRONE-BAD-01", "Model Y", -2.0, 700.0)

    # Current battery > capacity rejected
    with pytest.raises(ValueError, match="between 0 and maximum battery"):
        DroneService.register_drone("DRONE-BAD-02", "Model Y", 5.0, 500.0, current_battery_wh=600.0)


def test_active_drone_cannot_be_casually_marked_available(test_users):
    """An actively assigned drone cannot be transitioned to AVAILABLE without completing or aborting the mission."""
    operator = test_users["operator"]
    drone = DroneService.register_drone("DRONE-ACTIVE-01", "Model Alpha", 6.0, 900.0, 900.0)
    req = DeliveryService.create_request(test_users["req1"].id, EmergencyType.BLOOD_SUPPLY.value, 12.97, 77.59, 12.93, 77.62, 2.0)

    route = Route(
        delivery_request_id=req.id,
        algorithm_name="A_STAR",
        estimated_distance_km=5.0,
        estimated_duration_minutes=5.0,
        estimated_energy_wh=60.0,
        feasibility_status=FeasibilityStatus.FEASIBLE,
    )
    db.session.add(route)
    db.session.commit()

    # Assign drone
    AssignmentService.create_assignment(req.id, drone.id, route.id)
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # Attempting to manually switch drone to AVAILABLE must fail
    with pytest.raises(DroneServiceError, match="assigned to Active Mission"):
        DroneService.update_drone_status(drone.id, DroneStatus.AVAILABLE)


def test_drone_eligibility_check(test_users):
    """Test checking drone eligibility against cargo weight and energy constraints."""
    drone = DroneService.register_drone("DRONE-ELIGIBLE-01", "Medic Drone", 4.0, 600.0, 600.0)

    # Eligible for 2.5 kg cargo
    eligible, msg = DroneService.check_drone_eligibility(drone.id, payload_weight_kg=2.5, estimated_energy_wh=100.0)
    assert eligible is True

    # Ineligible for 5.0 kg cargo (exceeds 4.0 kg capacity)
    overweight, msg = DroneService.check_drone_eligibility(drone.id, payload_weight_kg=5.0)
    assert overweight is False
    assert "Payload exceeds drone capacity" in msg

    # Ineligible when in MAINTENANCE
    DroneService.update_drone_status(drone.id, DroneStatus.MAINTENANCE)
    maint, msg = DroneService.check_drone_eligibility(drone.id, payload_weight_kg=2.0)
    assert maint is False
    assert "MAINTENANCE" in msg


def test_requester_cannot_access_drone_inventory_routes(client, test_users):
    """Requesters must be forbidden from accessing drone management pages (403)."""
    # Log in as Requester
    client.post("/login", data={"email": test_users["req1"].email, "password": "Pass12345!"})

    resp_list = client.get("/drones")
    assert resp_list.status_code == 403

    resp_new = client.get("/drones/new")
    assert resp_new.status_code == 403
