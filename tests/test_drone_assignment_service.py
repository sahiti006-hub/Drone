import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus, EmergencyType
from app.models.route import Route, FeasibilityStatus
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.services.assignment_service import (
    AssignmentService,
    ConflictingAssignmentError,
    InfeasibleAssignmentError,
    AssignmentServiceError,
)


@pytest.fixture
def setup_dispatch_environment(app):
    """Set up baseline user, drone, request, and route."""
    user = User("Hospital Staff", "dispatch@hospital.org", "Pass12345!", UserRole.REQUESTER)
    db.session.add(user)
    db.session.flush()

    drone = Drone(
        drone_code="DRONE-DISPATCH-01",
        model_name="SkyMedic Hexacopter",
        maximum_payload_kg=5.0,
        battery_capacity_wh=850.0,
        current_battery_wh=850.0,
        cruise_speed_kmh=65.0,
    )
    db.session.add(drone)
    db.session.flush()

    req = DeliveryRequest(
        requester_id=user.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.5,
    )
    db.session.add(req)
    db.session.flush()

    route = Route(
        delivery_request_id=req.id,
        algorithm_name="A_STAR_OPTIMIZED",
        estimated_distance_km=6.0,
        estimated_duration_minutes=6.5,
        estimated_energy_wh=70.0,
        feasibility_status=FeasibilityStatus.FEASIBLE,
    )
    db.session.add(route)
    db.session.commit()

    return {"user": user, "drone": drone, "request": req, "route": route}


def test_successful_drone_assignment(app, setup_dispatch_environment):
    """Test standard transactional assignment of a drone to a request."""
    env = setup_dispatch_environment
    drone = env["drone"]
    req = env["request"]
    route = env["route"]

    assignment = AssignmentService.create_assignment(req.id, drone.id, route.id)

    assert assignment.id is not None
    assert assignment.status == AssignmentStatus.ACTIVE.value
    assert drone.status == DroneStatus.IN_TRANSIT.value
    assert req.status == RequestStatus.ASSIGNED.value


def test_conflict_prevention_same_drone(app, setup_dispatch_environment):
    """Ensure a drone with an active assignment cannot be assigned to another request."""
    env = setup_dispatch_environment
    drone = env["drone"]
    req1 = env["request"]
    route1 = env["route"]

    # First assignment succeeds
    AssignmentService.create_assignment(req1.id, drone.id, route1.id)

    # Create a second request and route
    req2 = DeliveryRequest(
        requester_id=env["user"].id,
        emergency_type=EmergencyType.ANTIVENOM,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=1.0,
    )
    db.session.add(req2)
    db.session.flush()
    route2 = Route(
        delivery_request_id=req2.id,
        algorithm_name="A_STAR",
        estimated_distance_km=4.0,
        estimated_duration_minutes=4.0,
        estimated_energy_wh=45.0,
    )
    db.session.add(route2)
    db.session.commit()

    # Attempting to assign the busy drone must fail with ConflictingAssignmentError
    with pytest.raises(ConflictingAssignmentError, match="already assigned"):
        AssignmentService.create_assignment(req2.id, drone.id, route2.id)


def test_infeasible_assignment_payload_exceeded(app, setup_dispatch_environment):
    """Ensure overweight payloads are rejected before assignment."""
    env = setup_dispatch_environment
    drone = env["drone"]  # max payload is 5.0 kg
    user = env["user"]

    heavy_req = DeliveryRequest(
        requester_id=user.id,
        emergency_type=EmergencyType.DISASTER_RELIEF,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=9.5,  # Exceeds 5.0 kg!
    )
    db.session.add(heavy_req)
    db.session.flush()

    route = Route(
        delivery_request_id=heavy_req.id,
        algorithm_name="A_STAR",
        estimated_distance_km=5.0,
        estimated_duration_minutes=5.0,
        estimated_energy_wh=50.0,
    )
    db.session.add(route)
    db.session.commit()

    with pytest.raises(InfeasibleAssignmentError, match="cannot carry payload weight"):
        AssignmentService.create_assignment(heavy_req.id, drone.id, route.id)


def test_complete_and_abort_assignment_lifecycle(app, setup_dispatch_environment):
    """Test full completion and abort transitions."""
    env = setup_dispatch_environment
    drone = env["drone"]
    req = env["request"]
    route = env["route"]

    assignment = AssignmentService.create_assignment(req.id, drone.id, route.id)

    # Complete assignment
    AssignmentService.complete_assignment(assignment.id)
    assert assignment.status == AssignmentStatus.COMPLETED.value
    assert assignment.completed_at is not None
    assert req.status == RequestStatus.DELIVERED.value
    assert drone.status == DroneStatus.AVAILABLE.value
    # Energy deducted
    assert float(drone.current_battery_wh) == (850.0 - 70.0)
