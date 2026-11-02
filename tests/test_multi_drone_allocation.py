"""Tests for Multi-Drone Batch Allocation and Bipartite Matching."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestPriority, RequestStatus, EmergencyType
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.services.drone_allocation_service import (
    DroneAllocationService,
    MultiDroneAllocationPlan,
    AllocationServiceError,
)


@pytest.fixture
def multi_alloc_setup(app):
    """Sets up users, multiple drones with varying capacities, and pending requests."""
    requester = User("Dr. Patel", "patel@hospital.org", "Pass12345!", UserRole.REQUESTER.value)
    operator = User("Operator Max", "max@dispatch.org", "Pass12345!", UserRole.OPERATOR.value)
    db.session.add_all([requester, operator])
    db.session.commit()

    # Fleet of 2 available drones
    drone_light = Drone(
        drone_code="UAV-LGT-01",
        model_name="Swift Courier",
        maximum_payload_kg=2.5,
        battery_capacity_wh=500.0,
        current_battery_wh=500.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.AVAILABLE.value,
    )
    drone_heavy = Drone(
        drone_code="UAV-HVY-01",
        model_name="Titan Lifter",
        maximum_payload_kg=7.0,
        battery_capacity_wh=1200.0,
        current_battery_wh=1200.0,
        cruise_speed_kmh=55.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add_all([drone_light, drone_heavy])
    db.session.commit()

    # Request 1: CRITICAL priority, light cargo (1.0 kg)
    req_critical = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.ANTIVENOM.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.420000,
        destination_longitude=78.470000,
        payload_weight_kg=1.0,
        priority=RequestPriority.CRITICAL.value,
    )
    # Request 2: MEDIUM priority, heavy cargo (4.5 kg) -> Requires heavy drone
    req_heavy = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.SURGICAL_KIT.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.430000,
        destination_longitude=78.460000,
        payload_weight_kg=4.5,
        priority=RequestPriority.MEDIUM.value,
    )
    # Request 3: LOW priority, standard cargo (2.0 kg) -> Competing for light drone
    req_low = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.410000,
        destination_longitude=78.490000,
        payload_weight_kg=2.0,
        priority=RequestPriority.LOW.value,
    )
    db.session.add_all([req_critical, req_heavy, req_low])
    db.session.commit()

    return {
        "requester": requester,
        "operator": operator,
        "drone_light": drone_light,
        "drone_heavy": drone_heavy,
        "req_critical": req_critical,
        "req_heavy": req_heavy,
        "req_low": req_low,
    }


def test_priority_best_fit_allocation(multi_alloc_setup):
    """Verify Priority-Driven Best-Fit matches critical requests and prevents capacity waste."""
    plan = DroneAllocationService.evaluate_multi_drone_allocation(
        algorithm_name="PRIORITY_BEST_FIT"
    )

    assert plan.total_evaluated_requests == 3
    assert plan.total_available_drones == 2
    assert len(plan.matches) == 2  # 2 drones available, so 2 matches
    assert len(plan.unmatched_requests) == 1

    matched_req_ids = [m.request_id for m in plan.matches]
    # Critical and heavy requests should be served
    assert multi_alloc_setup["req_critical"].id in matched_req_ids
    assert multi_alloc_setup["req_heavy"].id in matched_req_ids

    # Unmatched should be the LOW priority request
    unmatched_id = plan.unmatched_requests[0].request_id
    assert unmatched_id == multi_alloc_setup["req_low"].id
    assert plan.unmatched_requests[0].reason_code == "NO_AVAILABLE_DRONES"

    # Verify 1-to-1 unique drone matching (no drone assigned twice)
    matched_drone_ids = [m.drone_id for m in plan.matches]
    assert len(matched_drone_ids) == len(set(matched_drone_ids))


def test_fcfs_greedy_baseline_comparison(multi_alloc_setup):
    """Verify Baseline FCFS evaluates requests purely by order without priority weighting."""
    baseline_plan = DroneAllocationService.evaluate_multi_drone_allocation(
        algorithm_name="FCFS_GREEDY_BASELINE"
    )
    assert baseline_plan.algorithm_name == "FCFS_GREEDY_BASELINE"
    assert len(baseline_plan.matches) == 2
    assert len(baseline_plan.unmatched_requests) == 1


def test_insufficient_drone_capacity_scenario(app):
    """Verify requests with cargo heavier than any available drone are flagged as INSUFFICIENT_DRONE_CAPACITY."""
    requester = User("Dr. Heavy", "heavy@hospital.org", "Pass12345!", UserRole.REQUESTER.value)
    drone_small = Drone(
        drone_code="UAV-SML-01",
        model_name="Mini Flyer",
        maximum_payload_kg=2.0,
        battery_capacity_wh=400.0,
        current_battery_wh=400.0,
        cruise_speed_kmh=50.0,
        status=DroneStatus.AVAILABLE.value,
    )
    db.session.add_all([requester, drone_small])
    db.session.commit()

    # Request requires 5.0 kg cargo (exceeds drone capacity 2.0 kg)
    req_oversized = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.SURGICAL_KIT.value,
        pickup_latitude=17.385000,
        pickup_longitude=78.486000,
        destination_latitude=17.410000,
        destination_longitude=78.490000,
        payload_weight_kg=5.0,
        priority=RequestPriority.HIGH.value,
    )
    db.session.add(req_oversized)
    db.session.commit()

    plan = DroneAllocationService.evaluate_multi_drone_allocation(
        request_ids=[req_oversized.id],
        algorithm_name="PRIORITY_BEST_FIT",
    )

    assert len(plan.matches) == 0
    assert len(plan.unmatched_requests) == 1
    unmatched = plan.unmatched_requests[0]
    assert unmatched.reason_code == "INSUFFICIENT_DRONE_CAPACITY"
    assert "exceeds maximum capacity" in unmatched.explanation


def test_execute_batch_dispatch_atomicity(multi_alloc_setup):
    """Verify that execute_batch_dispatch persists routes and creates active assignments atomically."""
    plan = DroneAllocationService.evaluate_multi_drone_allocation(
        algorithm_name="PRIORITY_BEST_FIT"
    )
    assert len(plan.matches) == 2

    assignments = DroneAllocationService.execute_batch_dispatch(plan)
    assert len(assignments) == 2

    # Verify database state changes
    for asg in assignments:
        assert asg.status == AssignmentStatus.ACTIVE.value
        req = db.session.get(DeliveryRequest, asg.delivery_request_id)
        drone = db.session.get(Drone, asg.drone_id)
        assert req.status == RequestStatus.ASSIGNED.value
        assert drone.status == DroneStatus.IN_TRANSIT.value


def test_operator_multi_allocation_routes(client, multi_alloc_setup):
    """Verify the multi-allocation web endpoints are accessible to Operators."""
    operator = multi_alloc_setup["operator"]

    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    # GET console view
    resp = client.get("/operator/multi-allocation")
    assert resp.status_code == 200
    assert b"Multi-Drone Batch Allocation" in resp.data
    assert b"Priority Best-Fit Optimizer" in resp.data
    assert b"FCFS Greedy Baseline" in resp.data

    # POST dispatch execution
    post_resp = client.post(
        "/operator/multi-allocation/dispatch",
        data={"algorithm": "PRIORITY_BEST_FIT"},
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert b"Batch dispatch successful" in post_resp.data
