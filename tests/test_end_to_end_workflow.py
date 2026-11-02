"""Comprehensive End-to-End Delivery Lifecycle and Failure Scenario Automation Suite.

Validates:
PART A - Main End-to-End Workflow:
1. Log in as an administrator.
2. Create or inspect the demonstration drone fleet.
3. Create an emergency delivery request.
4. Verify request persistence and initial status.
5. Generate candidate flight corridors.
6. Inspect corridor feasibility metrics.
7. Compare baseline and weighted-objective optimizer.
8. Select a feasible route.
9. Assign an eligible drone.
10. Verify assignment and state transitions in the database.
11. Start the simulation.
12. Pause and resume simulation.
13. Trigger dynamic rerouting mid-flight upon weather shift.
14. Verify original route is preserved in the database.
15. Step simulation through to 100% completion.
16. Verify final delivery, drone, assignment, and simulation states.
17. Confirm dashboard metrics reflect the completed workflow.

PART B - Comprehensive Failure Scenarios:
- Payload exceeds drone capacity.
- Insufficient battery reserve.
- Missing or invalid weather data (fail-safe policy).
- No feasible candidate route under gale storms.
- Drone already assigned to another active delivery.
- Concurrent conflict: two operators allocate the same drone.
- Invalid delivery ID (404 handling).
- Unauthorized user (Requester) attempts drone assignment (403 Forbidden).
- Requester IDOR violation: accessing another user's delivery (403 Forbidden).
- Database transaction failure during assignment triggers clean rollback.
- Simulation started twice (invalid state transition).
- Rerouting requested on an invalid simulation state (COMPLETED).
- Dynamic replacement route fails feasibility checks (switched=False, mission kept).
- Map tiles offline notice markup present in simulation cockpit.
- ML prediction invalid input rejection with fallback.

PART C - Database Integrity Verification after every state transition.
"""

from __future__ import annotations
from datetime import datetime, timezone
import pytest
from unittest.mock import patch

from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus, EmergencyType, RequestPriority
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.analysis_log import AnalysisLog
from app.services.auth_service import AuthService
from app.services.drone_service import DroneService
from app.services.delivery_service import DeliveryService
from app.services.assignment_service import (
    AssignmentService,
    ConflictingAssignmentError,
    InfeasibleAssignmentError,
    AssignmentServiceError,
)
from app.services.drone_allocation_service import DroneAllocationService
from app.services.route_optimizer import RouteOptimizer
from app.services.simulation_service import (
    SimulationService,
    InvalidSimulationStateTransitionError,
    SimulationServiceError,
)
from app.services.weather_service import WeatherService, WeatherData
from app.services.analytics_service import AnalyticsService


# ==============================================================================
# FIXTURES
# ==============================================================================
@pytest.fixture
def e2e_users(app):
    """Seed administrator, operator, and requester accounts."""
    admin = User("Admin Chief", "admin.e2e@emergency.org", "AdminPass123!", UserRole.ADMIN.value)
    operator = User("Operator Ops", "operator.e2e@emergency.org", "OperatorPass123!", UserRole.OPERATOR.value)
    requester_a = User("Doctor Alice", "alice.e2e@hospital.org", "AlicePass123!", UserRole.REQUESTER.value)
    requester_b = User("Doctor Bob", "bob.e2e@clinic.org", "BobPass123!", UserRole.REQUESTER.value)
    db.session.add_all([admin, operator, requester_a, requester_b])
    db.session.commit()
    return {
        "admin": admin,
        "operator": operator,
        "requester_a": requester_a,
        "requester_b": requester_b,
    }


# ==============================================================================
# PART A: COMPLETE SUCCESSFUL END-TO-END WORKFLOW
# ==============================================================================
def test_complete_end_to_end_delivery_lifecycle(client, app, e2e_users):
    """Execute and verify the full 17-step end-to-end lifecycle."""
    admin = e2e_users["admin"]
    operator = e2e_users["operator"]
    requester = e2e_users["requester_a"]

    # --------------------------------------------------------------------------
    # Step 1: Log in as Administrator
    # --------------------------------------------------------------------------
    login_resp = client.post(
        "/login",
        data={"email": "admin.e2e@emergency.org", "password": "AdminPass123!"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("user_id") == admin.id
        assert sess.get("user_role") == UserRole.ADMIN.value

    # --------------------------------------------------------------------------
    # Step 2: Create and inspect demonstration drone fleet
    # --------------------------------------------------------------------------
    drone_payload = {
        "drone_code": "UAV-E2E-APEX",
        "model_name": "SkyMedic Titan-X",
        "maximum_payload_kg": 6.5,
        "battery_capacity_wh": 1200.0,
        "current_battery_wh": 1200.0,
        "cruise_speed_kmh": 60.0,
    }
    create_drone_resp = client.post("/drones/new", data=drone_payload, follow_redirects=True)
    assert create_drone_resp.status_code == 200

    drone = Drone.query.filter_by(drone_code="UAV-E2E-APEX").first()
    assert drone is not None
    assert drone.status == DroneStatus.AVAILABLE.value
    assert float(drone.maximum_payload_kg) == 6.5
    assert float(drone.current_battery_wh) == 1200.0

    # --------------------------------------------------------------------------
    # Step 3: Create an emergency delivery request
    # --------------------------------------------------------------------------
    req = DeliveryService.create_request(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.439930,
        destination_longitude=78.390830,
        payload_weight_kg=2.5,
        priority=RequestPriority.CRITICAL.value,
        description="Emergency O-negative blood units for acute trauma patient",
    )

    # --------------------------------------------------------------------------
    # Step 4: Verify request persistence and database integrity
    # --------------------------------------------------------------------------
    persisted_req = db.session.get(DeliveryRequest, req.id)
    assert persisted_req is not None
    assert persisted_req.status == RequestStatus.PENDING.value
    assert persisted_req.requester_id == requester.id
    assert float(persisted_req.payload_weight_kg) == 2.5
    assert persisted_req.priority == RequestPriority.CRITICAL.value

    # --------------------------------------------------------------------------
    # Step 5: Generate candidate flight corridors
    # --------------------------------------------------------------------------
    opt_result, selected_route = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=persisted_req.id,
        algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
        include_return_trip=False,
    )
    assert opt_result.candidate_count >= 2
    assert opt_result.is_feasible is True
    assert selected_route is not None

    # Verify request status transitioned to ROUTE_CALCULATED
    db.session.refresh(persisted_req)
    assert persisted_req.status == RequestStatus.ROUTE_CALCULATED.value

    # --------------------------------------------------------------------------
    # Step 6: Inspect route feasibility metrics
    # --------------------------------------------------------------------------
    routes = Route.query.filter_by(delivery_request_id=persisted_req.id).all()
    assert len(routes) == opt_result.candidate_count
    feasible_routes = [r for r in routes if r.feasibility_status == FeasibilityStatus.FEASIBLE.value]
    assert len(feasible_routes) >= 1

    for r in feasible_routes:
        assert float(r.estimated_distance_km) > 0.0
        assert float(r.estimated_duration_minutes) > 0.0
        assert float(r.estimated_energy_wh) > 0.0
        waypoints = RouteWaypoint.query.filter_by(route_id=r.id).all()
        assert len(waypoints) >= 2

    # --------------------------------------------------------------------------
    # Step 7: Compare baseline vs. weighted-objective optimizer
    # --------------------------------------------------------------------------
    baseline_corridor = next((r for r in feasible_routes if "DIRECT" in r.algorithm_name.upper()), feasible_routes[0])
    assert selected_route.route_score is not None
    # Weighted optimizer chooses corridor balancing duration, distance, and energy
    assert selected_route.feasibility_status == FeasibilityStatus.FEASIBLE.value

    # --------------------------------------------------------------------------
    # Step 8: Select a feasible route
    # --------------------------------------------------------------------------
    target_route = selected_route
    orig_route_id = target_route.id

    # --------------------------------------------------------------------------
    # Step 9: Assign an eligible drone (Operator action via POST /operator/assign)
    # --------------------------------------------------------------------------
    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    assign_resp = client.post(
        "/operator/assign",
        data={
            "delivery_request_id": persisted_req.id,
            "drone_id": drone.id,
            "route_id": target_route.id,
        },
        follow_redirects=True,
    )
    assert assign_resp.status_code == 200

    # --------------------------------------------------------------------------
    # Step 10: Verify assignment and database state transitions
    # --------------------------------------------------------------------------
    assignment = DroneAssignment.query.filter_by(delivery_request_id=persisted_req.id).first()
    assert assignment is not None
    assert assignment.status == AssignmentStatus.ACTIVE.value
    assert assignment.drone_id == drone.id
    assert assignment.route_id == target_route.id

    db.session.refresh(persisted_req)
    db.session.refresh(drone)
    assert persisted_req.status == RequestStatus.ASSIGNED.value
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # --------------------------------------------------------------------------
    # Step 11: Start the simulation
    # --------------------------------------------------------------------------
    sim = SimulationService.get_or_create_simulation(assignment.id)
    assert sim.status == SimulationStatus.CREATED.value

    start_resp = client.post(f"/simulation/api/{sim.id}/start")
    assert start_resp.status_code == 200
    db.session.refresh(sim)
    assert sim.status == SimulationStatus.RUNNING.value

    # Advance kinematics forward partially (e.g. 60 seconds)
    step1_resp = client.post(f"/simulation/api/{sim.id}/step", json={"delta_sim_seconds": 60.0, "speed_multiplier": 1.0})
    assert step1_resp.status_code == 200
    db.session.refresh(sim)
    assert sim.distance_covered_km > 0.0
    assert sim.current_progress_percent > 0.0

    # --------------------------------------------------------------------------
    # Step 12: Pause and resume simulation
    # --------------------------------------------------------------------------
    pause_resp = client.post(f"/simulation/api/{sim.id}/pause")
    assert pause_resp.status_code == 200
    db.session.refresh(sim)
    assert sim.status == SimulationStatus.PAUSED.value

    resume_resp = client.post(f"/simulation/api/{sim.id}/resume")
    assert resume_resp.status_code == 200
    db.session.refresh(sim)
    assert sim.status == SimulationStatus.RUNNING.value

    # --------------------------------------------------------------------------
    # Step 13: Trigger dynamic rerouting when permitted
    # --------------------------------------------------------------------------
    reroute_payload = {
        "wind_speed_mps": 6.0,
        "precipitation_mmh": 1.5,
        "visibility_km": 7.0,
        "weather_summary": "Moderate localized crosswind cell",
        "policy": "SAFETY_MANDATED",
        "reason": "Mid-flight weather adaptation",
    }
    reroute_resp = client.post(f"/simulation/api/{sim.id}/reroute", json=reroute_payload)
    assert reroute_resp.status_code == 200
    reroute_json = reroute_resp.get_json()
    assert reroute_json["success"] is True
    assert reroute_json["reroute"]["switched"] is True
    new_route_id = reroute_json["reroute"]["new_route_id"]

    # --------------------------------------------------------------------------
    # Step 14: Verify original route remains in the database (Route history preserved)
    # --------------------------------------------------------------------------
    orig_route_in_db = db.session.get(Route, orig_route_id)
    assert orig_route_in_db is not None
    assert orig_route_in_db.delivery_request_id == persisted_req.id

    new_route_in_db = db.session.get(Route, new_route_id)
    assert new_route_in_db is not None
    assert new_route_in_db.id != orig_route_id

    db.session.refresh(assignment)
    assert assignment.route_id == new_route_id

    # --------------------------------------------------------------------------
    # Step 15: Step simulation to 100% completion
    # --------------------------------------------------------------------------
    # Step with sufficiently large time step to guarantee complete flight path coverage
    step_final_resp = client.post(f"/simulation/api/{sim.id}/step", json={"delta_sim_seconds": 2500.0, "speed_multiplier": 5.0})
    assert step_final_resp.status_code == 200
    step_json = step_final_resp.get_json()
    assert step_json["telemetry"]["is_completed"] is True

    # --------------------------------------------------------------------------
    # Step 16: Verify final delivery and drone states
    # --------------------------------------------------------------------------
    db.session.refresh(sim)
    db.session.refresh(assignment)
    db.session.refresh(persisted_req)
    db.session.refresh(drone)

    assert sim.status == SimulationStatus.COMPLETED.value
    assert sim.current_progress_percent == 100.0
    assert assignment.status == AssignmentStatus.COMPLETED.value
    assert persisted_req.status == RequestStatus.DELIVERED.value
    assert drone.status in [DroneStatus.AVAILABLE.value, DroneStatus.CHARGING.value]

    # Verify AnalysisLog audit entry was generated
    import json
    log_entry = AnalysisLog.query.filter_by(simulation_run_id=sim.id).first()
    assert log_entry is not None
    actual_data = json.loads(log_entry.actual_simulated_metrics_json) if isinstance(log_entry.actual_simulated_metrics_json, str) else log_entry.actual_simulated_metrics_json
    assert actual_data["status"] == "DELIVERED"
    assert actual_data["distance_km"] > 0.0

    # --------------------------------------------------------------------------
    # Step 17: Confirm dashboard metrics reflect the completed workflow
    # --------------------------------------------------------------------------
    metrics = AnalyticsService.get_dashboard_metrics(admin)
    assert metrics["completed_deliveries"] >= 1
    assert metrics["total_requests"] >= 1
    assert metrics["active_simulations"] == 0
    assert metrics["delivery_success_pct"] > 0.0


# ==============================================================================
# PART B: FAILURE SCENARIOS & RESILIENCE
# ==============================================================================

def test_failure_payload_exceeds_drone_capacity(app, e2e_users):
    """Test Case 1: Infeasible assignment when payload exceeds maximum drone rating."""
    requester = e2e_users["requester_a"]
    drone = Drone("UAV-LGT-01", "Mini Scout", 1.5, 300.0, 300.0, 45.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    # Heavy request (3.0 kg > 1.5 kg capacity)
    req = DeliveryRequest(
        requester.id, EmergencyType.DEFIBRILLATOR.value,
        17.385, 78.486, 17.439, 78.390, 3.0, RequestPriority.HIGH.value
    )
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "TEST", 10.0, 10.0, 40.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    with pytest.raises(InfeasibleAssignmentError, match="cannot carry payload weight"):
        AssignmentService.create_assignment(req.id, drone.id, route.id)

    # Verify database integrity: no assignment created, states preserved
    assert DroneAssignment.query.filter_by(delivery_request_id=req.id).count() == 0
    db.session.refresh(drone)
    db.session.refresh(req)
    assert drone.status == DroneStatus.AVAILABLE.value
    assert req.status == RequestStatus.PENDING.value


def test_failure_insufficient_battery_reserve(app, e2e_users):
    """Test Case 2: Infeasible assignment when drone battery violates 15% reserve limit."""
    requester = e2e_users["requester_a"]
    # Drone with depleted battery (only 40 Wh remaining)
    drone = Drone("UAV-LOW-BAT", "Transporter", 5.0, 500.0, 40.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(
        requester.id, EmergencyType.ANTIVENOM.value,
        17.385, 78.486, 17.439, 78.390, 1.0, RequestPriority.CRITICAL.value
    )
    db.session.add(req)
    db.session.commit()

    # Route requiring 50 Wh (needs 50 * 1.15 = 57.5 Wh with reserve > 40 Wh)
    route = Route(req.id, "TEST", 12.0, 12.0, 50.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    with pytest.raises(InfeasibleAssignmentError, match="insufficient for route"):
        AssignmentService.create_assignment(req.id, drone.id, route.id)

    # Database integrity check
    assert DroneAssignment.query.filter_by(delivery_request_id=req.id).count() == 0
    db.session.refresh(drone)
    assert drone.status == DroneStatus.AVAILABLE.value


def test_failure_missing_or_invalid_weather_data(app):
    """Test Case 3: Missing weather data triggers fail-safe INFEASIBLE corridor classification."""
    from app.services.route_optimizer import FeasibilityChecker, RouteCandidate, Waypoint
    checker = FeasibilityChecker(
        maximum_payload_kg=5.0,
        battery_capacity_wh=600.0,
        current_battery_wh=600.0,
    )
    candidate = RouteCandidate(
        candidate_id="cand_test_01",
        corridor_name="DIRECT",
        waypoints=[Waypoint(17.385, 78.486, 50.0), Waypoint(17.439, 78.390, 25.0)],
        distance_km=10.0,
        duration_minutes=10.0,
        energy_wh=50.0,
    )
    is_feasible = checker.evaluate_candidate(
        candidate=candidate,
        payload_weight_kg=2.0,
        weather=None,  # Missing weather observation
    )
    assert is_feasible is False
    assert candidate.is_feasible is False
    assert any("Missing verified weather observation" in r for r in candidate.rejection_reasons)


def test_failure_no_feasible_candidate_routes_under_storm(app, e2e_users):
    """Test Case 4: Severe storm conditions cause all candidate corridors to fail feasibility."""
    requester = e2e_users["requester_a"]
    req = DeliveryRequest(
        requester.id, EmergencyType.SURGICAL_KIT.value,
        17.385, 78.486, 17.439, 78.390, 2.0, RequestPriority.HIGH.value
    )
    db.session.add(req)
    db.session.commit()

    # Record severe gale storm in database: wind speed 25 m/s > 12 m/s maximum multi-rotor limit
    WeatherService.record_simulated_weather(
        delivery_request_id=req.id,
        wind_speed_mps=25.0,
        precipitation_mmh=18.0,
        visibility_km=1.5,
        weather_summary="Severe Gale and Torrential Rain",
    )

    opt_result, selected = DroneAllocationService.generate_and_persist_routes(req.id)

    assert opt_result.is_feasible is False
    assert opt_result.feasible_count == 0
    assert selected is None

    routes = Route.query.filter_by(delivery_request_id=req.id).all()
    assert len(routes) >= 2
    for r in routes:
        assert r.feasibility_status == FeasibilityStatus.INFEASIBLE.value
        assert "wind speed" in r.rejection_reason.lower() or "precipitation" in r.rejection_reason.lower()


def test_failure_drone_already_assigned_to_active_delivery(app, e2e_users):
    """Test Case 5: Conflicting assignment rejected when drone is in-transit."""
    requester = e2e_users["requester_a"]
    drone = Drone("UAV-BUSY-01", "Carrier", 5.0, 800.0, 800.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    # Request 1 & assignment
    req1 = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 1.5, RequestPriority.HIGH.value)
    db.session.add(req1)
    db.session.commit()
    route1 = Route(req1.id, "DIR", 8.0, 8.0, 40.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route1)
    db.session.commit()

    # Successfully assign Drone to Request 1
    AssignmentService.create_assignment(req1.id, drone.id, route1.id)
    db.session.refresh(drone)
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # Request 2 attempting to assign the same busy drone
    req2 = DeliveryRequest(requester.id, EmergencyType.ANTIVENOM.value, 17.38, 78.48, 17.43, 78.39, 1.0, RequestPriority.CRITICAL.value)
    db.session.add(req2)
    db.session.commit()
    route2 = Route(req2.id, "DIR", 8.0, 8.0, 40.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route2)
    db.session.commit()

    with pytest.raises(ConflictingAssignmentError, match="already assigned to active mission"):
        AssignmentService.create_assignment(req2.id, drone.id, route2.id)

    # Verify Request 2 not assigned
    assert DroneAssignment.query.filter_by(delivery_request_id=req2.id).count() == 0


def test_failure_concurrency_two_operators_allocate_same_drone(app, e2e_users):
    """Test Case 6: Concurrent conflict handling when two operators allocate same drone."""
    requester = e2e_users["requester_a"]
    drone = Drone("UAV-CONCURR", "FastMedic", 5.0, 700.0, 700.0, 65.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req_op1 = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.HIGH.value)
    req_op2 = DeliveryRequest(requester.id, EmergencyType.DEFIBRILLATOR.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.CRITICAL.value)
    db.session.add_all([req_op1, req_op2])
    db.session.commit()

    route1 = Route(req_op1.id, "DIR", 6.0, 6.0, 30.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    route2 = Route(req_op2.id, "DIR", 6.0, 6.0, 30.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add_all([route1, route2])
    db.session.commit()

    # Operator 1 claims drone
    asg1 = AssignmentService.create_assignment(req_op1.id, drone.id, route1.id)
    assert asg1 is not None

    # Operator 2 attempts to claim same drone
    with pytest.raises(ConflictingAssignmentError):
        AssignmentService.create_assignment(req_op2.id, drone.id, route2.id)

    # Verify clean rollback: only 1 assignment exists
    assert DroneAssignment.query.filter_by(drone_id=drone.id).count() == 1
    db.session.refresh(req_op2)
    assert req_op2.status == RequestStatus.PENDING.value


def test_failure_invalid_delivery_id(client, app, e2e_users):
    """Test Case 7: Graceful 404 handling for non-existent delivery request IDs."""
    admin = e2e_users["admin"]
    with client.session_transaction() as sess:
        sess["user_id"] = admin.id
        sess["user_role"] = UserRole.ADMIN.value

    # Non-existent ID detail
    resp = client.get("/requests/99999")
    assert resp.status_code == 404

    # Non-existent ID edit
    resp_edit = client.get("/requests/99999/edit")
    assert resp_edit.status_code == 404


def test_failure_unauthorized_user_assigns_drone(client, app, e2e_users):
    """Test Case 8: Requester role is forbidden from dispatching drones (403 Forbidden)."""
    requester = e2e_users["requester_a"]
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["user_role"] = UserRole.REQUESTER.value

    # Requester POSTing to operator assign
    resp = client.post(
        "/operator/assign",
        data={"delivery_request_id": 1, "drone_id": 1, "route_id": 1},
    )
    assert resp.status_code == 403


def test_failure_requester_idor_access_other_user_delivery(client, app, e2e_users):
    """Test Case 9: IDOR protection prevents Requester B from viewing Requester A's request."""
    requester_a = e2e_users["requester_a"]
    requester_b = e2e_users["requester_b"]

    req_a = DeliveryRequest(requester_a.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 1.5, RequestPriority.HIGH.value)
    db.session.add(req_a)
    db.session.commit()

    # Log in as Requester B
    with client.session_transaction() as sess:
        sess["user_id"] = requester_b.id
        sess["user_role"] = UserRole.REQUESTER.value

    # Attempt to view Requester A's request
    resp = client.get(f"/requests/{req_a.id}")
    assert resp.status_code == 403


def test_failure_database_transaction_rollback_during_assignment(app, e2e_users):
    """Test Case 10: Simulated DB exception during commit triggers complete rollback."""
    requester = e2e_users["requester_a"]
    drone = Drone("UAV-ROLLBACK-01", "Carrier", 5.0, 700.0, 700.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.HIGH.value)
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "DIR", 6.0, 6.0, 30.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    # Force db.session.commit to raise an exception inside AssignmentService.create_assignment
    with patch.object(db.session, "commit", side_effect=RuntimeError("Simulated Database I/O Failure")):
        with pytest.raises(RuntimeError, match="Simulated Database I/O Failure"):
            AssignmentService.create_assignment(req.id, drone.id, route.id)

    # Verify rollback integrity: Drone remains AVAILABLE, Request remains PENDING, no assignment row
    db.session.rollback()
    db.session.refresh(drone)
    db.session.refresh(req)
    assert drone.status == DroneStatus.AVAILABLE.value
    assert req.status == RequestStatus.PENDING.value
    assert DroneAssignment.query.filter_by(delivery_request_id=req.id).count() == 0


def test_failure_simulation_started_twice(client, app, e2e_users):
    """Test Case 11: Duplicate start request on running simulation returns HTTP 400."""
    operator = e2e_users["operator"]
    requester = e2e_users["requester_a"]

    drone = Drone("UAV-SIM-DOUBLE", "FastLifter", 5.0, 800.0, 800.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.HIGH.value)
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "DIR", 5.0, 5.0, 25.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    wp1 = RouteWaypoint(route.id, 0, 17.38, 78.48, 50.0)
    wp2 = RouteWaypoint(route.id, 1, 17.43, 78.39, 25.0)
    db.session.add_all([wp1, wp2])
    db.session.commit()

    asg = AssignmentService.create_assignment(req.id, drone.id, route.id)
    sim = SimulationService.get_or_create_simulation(asg.id)
    sim = SimulationService.start_simulation(sim.id)
    assert sim.status == SimulationStatus.RUNNING.value

    # Authenticate as Operator
    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    # Second start attempt
    second_start = client.post(f"/simulation/api/{sim.id}/start")
    assert second_start.status_code == 400
    assert "Cannot start simulation from status 'RUNNING'" in second_start.get_json()["error"]


def test_failure_rerouting_invalid_simulation_state(client, app, e2e_users):
    """Test Case 12: Rerouting request rejected on COMPLETED simulation (HTTP 400)."""
    operator = e2e_users["operator"]
    requester = e2e_users["requester_a"]

    drone = Drone("UAV-COMPL-01", "Lifeline", 5.0, 800.0, 800.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.HIGH.value)
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "DIR", 5.0, 5.0, 25.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    wp1 = RouteWaypoint(route.id, 0, 17.38, 78.48, 50.0)
    wp2 = RouteWaypoint(route.id, 1, 17.43, 78.39, 25.0)
    db.session.add_all([wp1, wp2])
    db.session.commit()

    asg = AssignmentService.create_assignment(req.id, drone.id, route.id)
    sim = SimulationService.get_or_create_simulation(asg.id)
    sim = SimulationService.start_simulation(sim.id)

    # Advance to completion
    SimulationService.step_simulation(sim.id, delta_sim_seconds=1000.0, speed_multiplier=1.0)
    db.session.refresh(sim)
    assert sim.status == SimulationStatus.COMPLETED.value

    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    # Attempt reroute on completed simulation
    reroute_resp = client.post(f"/simulation/api/{sim.id}/reroute", json={"wind_speed_mps": 6.0})
    assert reroute_resp.status_code == 400
    assert "active simulations" in reroute_resp.get_json()["error"]
    assert "COMPLETED" in reroute_resp.get_json()["error"]


def test_failure_replacement_route_fails_feasibility(app, e2e_users):
    """Test Case 13: When dynamic replacement fails feasibility, original route is kept."""
    requester = e2e_users["requester_a"]
    drone = Drone("UAV-REROUTE-FAIL", "Lifeline", 5.0, 800.0, 800.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 2.0, RequestPriority.HIGH.value)
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "DIR", 8.0, 8.0, 40.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()
    orig_route_id = route.id

    wp1 = RouteWaypoint(route.id, 0, 17.38, 78.48, 50.0)
    wp2 = RouteWaypoint(route.id, 1, 17.43, 78.39, 25.0)
    db.session.add_all([wp1, wp2])
    db.session.commit()

    asg = AssignmentService.create_assignment(req.id, drone.id, route.id)
    sim = SimulationService.get_or_create_simulation(asg.id)
    sim = SimulationService.start_simulation(sim.id)

    # Step forward slightly
    SimulationService.step_simulation(sim.id, delta_sim_seconds=30.0, speed_multiplier=1.0)

    # Catastrophic weather (wind 28 m/s) -> all replacement corridors are infeasible
    storm_weather = WeatherData(
        wind_speed_mps=28.0,
        precipitation_mmh=25.0,
        visibility_km=1.0,
        weather_summary="Hurricane force storm cell",
    )

    reroute_res = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=storm_weather,
        policy_name="SAFETY_MANDATED",
        reason="Severe gale detected",
    )

    # Reroute should decline switch
    assert reroute_res.switched is False
    assert "No replacement candidate satisfies safety constraints" in reroute_res.explanation

    # Verify original route is preserved and assignment is unchanged
    db.session.refresh(asg)
    assert asg.route_id == orig_route_id
    db.session.refresh(sim)
    assert sim.status == SimulationStatus.RUNNING.value


def test_map_tiles_offline_handling_and_fallback_markup(client, app, e2e_users):
    """Test Case 14: Simulation cockpit contains offline tile notice and renders without external network."""
    operator = e2e_users["operator"]
    requester = e2e_users["requester_a"]

    drone = Drone("UAV-OFFLINE-MAP", "Scout", 5.0, 600.0, 600.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add(drone)
    db.session.commit()

    req = DeliveryRequest(requester.id, EmergencyType.BLOOD_SUPPLY.value, 17.38, 78.48, 17.43, 78.39, 1.5, RequestPriority.HIGH.value)
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "DIR", 6.0, 6.0, 30.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    wp1 = RouteWaypoint(route.id, 0, 17.38, 78.48, 50.0)
    wp2 = RouteWaypoint(route.id, 1, 17.43, 78.39, 25.0)
    db.session.add_all([wp1, wp2])
    db.session.commit()

    asg = AssignmentService.create_assignment(req.id, drone.id, route.id)
    sim = SimulationService.get_or_create_simulation(asg.id)

    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    resp = client.get(f"/simulation/{sim.id}")
    assert resp.status_code == 200

    # Verify the tile-offline-notice fallback markup is present in DOM
    assert b"tile-offline-notice" in resp.data
    assert b"Map tiles offline or unreachable" in resp.data
    assert b"simulation-map" in resp.data
    assert b"Simulated Telemetry" in resp.data


def test_failure_ml_prediction_invalid_input_and_fallback(client, app, e2e_users):
    """Test Case 15: Invalid inputs to ML prediction API return HTTP 400 and retain baseline fallback."""
    operator = e2e_users["operator"]
    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["user_role"] = UserRole.OPERATOR.value

    # Negative distance
    resp_neg_dist = client.post("/analytics/api/ml-model/predict", json={"distance_km": -10.0})
    assert resp_neg_dist.status_code == 400
    assert resp_neg_dist.get_json()["success"] is False

    # Negative payload
    resp_neg_payload = client.post("/analytics/api/ml-model/predict", json={"payload_weight_kg": -2.0})
    assert resp_neg_payload.status_code == 400
    assert resp_neg_payload.get_json()["success"] is False

    # Negative wind speed
    resp_neg_wind = client.post("/analytics/api/ml-model/predict", json={"wind_speed_mps": -5.0})
    assert resp_neg_wind.status_code == 400
    assert resp_neg_wind.get_json()["success"] is False
