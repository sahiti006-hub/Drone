"""Tests for discrete-time kinematic simulation engine, state machine, and APIs."""

import pytest
from app.extensions import db
from app.models.delivery_request import DeliveryRequest, EmergencyType, RequestPriority, RequestStatus
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.route_waypoint import RouteWaypoint
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.analysis_log import AnalysisLog
from app.models.user import User, UserRole
from app.services.simulation_service import (
    DuplicateSimulationError,
    InvalidAssignmentStateError,
    InvalidSimulationStateTransitionError,
    SimulationService,
    compute_bearing,
    interpolate_position,
)


@pytest.fixture
def sim_setup(app):
    """Sets up a complete mission environment with requester, operator, drone, request, and route."""
    requester = User("Requester One", "req1@hospital.org", "Pass123456!", UserRole.REQUESTER.value)
    other_requester = User("Requester Two", "req2@clinic.org", "Pass123456!", UserRole.REQUESTER.value)
    operator = User("Operator One", "op1@emergency.org", "Pass123456!", UserRole.OPERATOR.value)
    db.session.add_all([requester, other_requester, operator])
    db.session.commit()

    drone = Drone(
        drone_code="SIM-DRONE-01",
        model_name="SkyLifter X1",
        maximum_payload_kg=5.0,
        battery_capacity_wh=1000.0,
        current_battery_wh=1000.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.RESERVED.value,
    )
    db.session.add(drone)
    db.session.commit()

    # Request from requester 1
    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.0,
        priority=RequestPriority.CRITICAL.value,
        status=RequestStatus.ASSIGNED.value,
    )
    db.session.add(req)
    db.session.commit()

    # Feasible Route with 4 waypoints
    route = Route(
        delivery_request_id=req.id,
        algorithm_name="A_STAR_CORRIDOR",
        estimated_distance_km=5.85,
        estimated_duration_minutes=6.0,
        estimated_energy_wh=65.0,
        route_score=0.95,
        feasibility_status=FeasibilityStatus.FEASIBLE.value,
    )
    db.session.add(route)
    db.session.commit()

    wps = [
        RouteWaypoint(route.id, 0, 12.9716, 77.5946, 50.0),
        RouteWaypoint(route.id, 1, 12.9600, 77.6050, 60.0),
        RouteWaypoint(route.id, 2, 12.9480, 77.6150, 60.0),
        RouteWaypoint(route.id, 3, 12.9352, 77.6245, 25.0),
    ]
    db.session.add_all(wps)
    db.session.commit()

    # Active Assignment
    assignment = DroneAssignment(
        delivery_request_id=req.id,
        drone_id=drone.id,
        route_id=route.id,
        status=AssignmentStatus.ACTIVE.value,
    )
    db.session.add(assignment)
    db.session.commit()

    return {
        "requester": requester,
        "other_requester": other_requester,
        "operator": operator,
        "drone": drone,
        "request": req,
        "route": route,
        "assignment": assignment,
        "waypoints": wps,
    }


def test_waypoint_interpolation_and_bearing():
    """Test mathematical position interpolation and compass bearing calculation."""
    waypoints = [
        {"latitude": 10.0, "longitude": 10.0, "altitude_m": 50.0},
        {"latitude": 10.0, "longitude": 10.05, "altitude_m": 70.0},
        {"latitude": 10.0, "longitude": 10.10, "altitude_m": 30.0},
    ]

    # Bearing directly East should be 90 degrees
    bearing = compute_bearing(10.0, 10.0, 10.0, 10.05)
    assert 88.0 <= bearing <= 92.0

    # Interpolate at distance 0 km
    pos_start = interpolate_position(waypoints, 0.0)
    assert pos_start["latitude"] == 10.0
    assert pos_start["longitude"] == 10.0
    assert pos_start["altitude_m"] == 50.0
    assert pos_start["segment_index"] == 0

    # Interpolate at midpoint
    pos_mid = interpolate_position(waypoints, 5.5)  # roughly halfway across ~10.9km total
    assert pos_mid["latitude"] == 10.0
    assert 10.03 < pos_mid["longitude"] < 10.07

    # Interpolate past total distance: clamped to end waypoint
    pos_end = interpolate_position(waypoints, 999.0)
    assert pos_end["latitude"] == 10.0
    assert pos_end["longitude"] == 10.10
    assert pos_end["altitude_m"] == 30.0


def test_simulation_initialization_and_prevention_of_duplicates(sim_setup):
    """Test initializing a simulation run and ensuring no duplicate runs are created."""
    assignment = sim_setup["assignment"]

    sim1 = SimulationService.get_or_create_simulation(assignment.id)
    assert sim1.id is not None
    assert sim1.status == SimulationStatus.CREATED.value
    assert sim1.assignment_id == assignment.id
    assert sim1.current_progress_percent == 0.0
    assert sim1.distance_covered_km == 0.0
    assert sim1.remaining_distance_km > 0.0

    # Requesting simulation for the same assignment should return existing active instance
    sim2 = SimulationService.get_or_create_simulation(assignment.id)
    assert sim2.id == sim1.id


def test_simulation_lifecycle_pause_resume(sim_setup):
    """Test state machine: CREATED -> RUNNING -> PAUSED -> RUNNING."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)

    # Start
    sim = SimulationService.start_simulation(sim.id)
    assert sim.status == SimulationStatus.RUNNING.value
    assert sim.start_time is not None
    assert sim_setup["request"].status == RequestStatus.IN_TRANSIT.value
    assert sim_setup["drone"].status == DroneStatus.IN_TRANSIT.value

    # Pause
    sim = SimulationService.pause_simulation(sim.id)
    assert sim.status == SimulationStatus.PAUSED.value

    # Resume
    sim = SimulationService.resume_simulation(sim.id)
    assert sim.status == SimulationStatus.RUNNING.value


def test_invalid_state_transitions(sim_setup):
    """Test rejection of illegal simulation state transitions."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)

    # Cannot pause when CREATED
    with pytest.raises(InvalidSimulationStateTransitionError):
        SimulationService.pause_simulation(sim.id)

    # Cannot resume when CREATED
    with pytest.raises(InvalidSimulationStateTransitionError):
        SimulationService.resume_simulation(sim.id)

    # Cannot step when CREATED (must be RUNNING)
    with pytest.raises(InvalidSimulationStateTransitionError):
        SimulationService.step_simulation(sim.id, delta_sim_seconds=5.0)


def test_simulation_step_kinematics_and_battery(sim_setup):
    """Test advancing simulation kinematics in discrete steps."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)

    initial_battery = sim.current_battery_wh

    # Step forward 30 seconds at 1x speed
    res = SimulationService.step_simulation(sim.id, delta_sim_seconds=30.0, speed_multiplier=1.0)
    assert res["status"] == SimulationStatus.RUNNING.value
    assert res["distance_covered_km"] > 0.0
    assert res["progress_percent"] > 0.0
    assert res["current_battery_wh"] < initial_battery
    assert res["is_completed"] is False


def test_simulation_completion_and_analysis_logging(sim_setup):
    """Test full mission delivery completion, asset release, and analysis log persistence."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)

    # Advance large step to reach 100% completion
    res = SimulationService.step_simulation(sim.id, delta_sim_seconds=3600.0, speed_multiplier=1.0)
    assert res["is_completed"] is True
    assert res["status"] == SimulationStatus.COMPLETED.value
    assert res["progress_percent"] == 100.0

    # Verify assignment, request, and drone status updates
    assert assignment.status == AssignmentStatus.COMPLETED.value
    assert sim_setup["request"].status == RequestStatus.DELIVERED.value
    assert sim_setup["drone"].status == DroneStatus.AVAILABLE.value

    # Verify AnalysisLog was generated
    log = AnalysisLog.query.filter_by(simulation_run_id=sim.id).first()
    assert log is not None
    assert log.algorithm_name == sim_setup["route"].algorithm_name
    assert log.evaluation_status == "OPTIMAL"
    assert log.get_actual_metrics()["status"] == "DELIVERED"


def test_simulation_cancellation_and_drone_release(sim_setup):
    """Test aborting a simulation releases the drone and marks request cancelled."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)

    sim = SimulationService.cancel_simulation(sim.id, reason="Weather degradation abort")
    assert sim.status == SimulationStatus.CANCELLED.value
    assert assignment.status == AssignmentStatus.ABORTED.value
    assert sim_setup["request"].status == RequestStatus.CANCELLED.value
    assert sim_setup["drone"].status == DroneStatus.AVAILABLE.value


def test_simulation_recovery_and_checkpoint_sync(sim_setup):
    """Test checkpoint persistence and recovery without resetting progress on page reload."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)

    # Client syncs smooth progress checkpoint
    SimulationService.sync_checkpoint(
        simulation_id=sim.id,
        progress_percent=45.5,
        latitude=12.9550,
        longitude=77.6100,
        altitude_m=58.0,
        elapsed_seconds=160.0,
        distance_covered_km=2.65,
        remaining_distance_km=3.20,
        current_battery_wh=970.0,
        speed_multiplier=2.0,
        extra_data={"heading_deg": 135.0},
    )

    # Simulate reload
    state = SimulationService.get_simulation_state(sim.id)
    assert state["progress_percent"] == 45.5
    assert state["telemetry"]["latitude"] == 12.955
    assert state["telemetry"]["distance_covered_km"] == 2.65
    assert state["telemetry"]["remaining_distance_km"] == 3.20
    assert state["telemetry"]["current_battery_wh"] == 970.0
    assert state["status"] == SimulationStatus.RUNNING.value


def test_simulation_api_authorization_and_idor(client, sim_setup):
    """Test API endpoint authentication and role-based permissions."""
    assignment = sim_setup["assignment"]
    sim = SimulationService.get_or_create_simulation(assignment.id)

    # 1. Unauthenticated request to state API -> redirect to login
    res = client.get(f"/simulation/api/{sim.id}/state")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    # 2. Requester Two (IDOR test: attempts to view Requester One's simulation)
    client.post("/login", data={"email": "req2@clinic.org", "password": "Pass123456!"}, follow_redirects=True)
    res_idor = client.get(f"/simulation/api/{sim.id}/state")
    assert res_idor.status_code == 403

    # Requester cannot control simulation (start)
    res_ctrl = client.post(f"/simulation/api/{sim.id}/start")
    assert res_ctrl.status_code == 403
    client.get("/logout")

    # 3. Operator can access state and trigger simulation controls
    client.post("/login", data={"email": "op1@emergency.org", "password": "Pass123456!"}, follow_redirects=True)
    res_op = client.get(f"/simulation/api/{sim.id}/state")
    assert res_op.status_code == 200
    data = res_op.get_json()
    assert data["success"] is True
    assert data["data"]["simulation"]["id"] == sim.id

    # Operator starts simulation
    res_start = client.post(f"/simulation/api/{sim.id}/start")
    assert res_start.status_code == 200
    assert res_start.get_json()["status"] == SimulationStatus.RUNNING.value
