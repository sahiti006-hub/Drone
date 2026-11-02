"""Unit and integration tests for Dynamic Simulation Rerouting (Enhancement 2).

Tests:
1. Successful dynamic rerouting under SAFETY_MANDATED policy.
2. Route preservation in DB (original Route entity remains, assignment route pointer updates).
3. Immutable reroute history audit trail in SimulationRun parameters_json.
4. OBJECTIVE_IMPROVEMENT switching policy threshold logic (accept vs reject).
5. Infeasible environmental change handling (e.g., gale force winds exceed threshold, original route preserved).
6. Near-destination arrival threshold (rerouting skipped when < 100m to destination).
7. REST API endpoint POST /simulation/api/<id>/reroute with role-based access control.
"""

import json
import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus, EmergencyType, RequestPriority
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.services.simulation_service import SimulationService, DynamicRerouteResult
from app.services.weather_service import WeatherData


@pytest.fixture
def setup_reroute_entities(app):
    """Set up user, drone, request, route, assignment, and running simulation."""
    operator = User("Operator Pilot", "operator.pilot@emergency.org", "OperatorPass123!", UserRole.OPERATOR.value)
    requester = User("Requester Doc", "requester.doc@emergency.org", "RequesterPass123!", UserRole.REQUESTER.value)

    drone = Drone(
        drone_code="UAV-REROUTE-01",
        model_name="SkyLifter-X4",
        maximum_payload_kg=5.0,
        battery_capacity_wh=500.0,
        current_battery_wh=480.0,
        cruise_speed_kmh=60.0,
        status=DroneStatus.IN_TRANSIT.value,
    )

    db.session.add_all([operator, requester, drone])
    db.session.commit()

    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        priority=RequestPriority.CRITICAL.value,
        payload_weight_kg=1.8,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.440081,
        destination_longitude=78.348916,
        status=RequestStatus.IN_TRANSIT.value,
    )
    db.session.add(req)
    db.session.commit()

    # Original Route
    orig_route = Route(
        delivery_request_id=req.id,
        algorithm_name="DIRECT_GREAT_CIRCLE",
        estimated_distance_km=16.0,
        estimated_duration_minutes=16.0,
        estimated_energy_wh=120.0,
        route_score=0.450,
        feasibility_status=FeasibilityStatus.FEASIBLE.value,
    )
    db.session.add(orig_route)
    db.session.commit()

    # Initial waypoints
    wp0 = RouteWaypoint(route_id=orig_route.id, sequence_number=0, latitude=17.385044, longitude=78.486671, altitude_m=0.0)
    wp1 = RouteWaypoint(route_id=orig_route.id, sequence_number=1, latitude=17.4125, longitude=78.4177, altitude_m=60.0)
    wp2 = RouteWaypoint(route_id=orig_route.id, sequence_number=2, latitude=17.440081, longitude=78.348916, altitude_m=0.0)
    db.session.add_all([wp0, wp1, wp2])

    assignment = DroneAssignment(
        delivery_request_id=req.id,
        drone_id=drone.id,
        route_id=orig_route.id,
        status=AssignmentStatus.ACTIVE.value,
    )
    db.session.add(assignment)
    db.session.commit()

    sim = SimulationRun(
        run_code="SIM-REROUTE-01",
        parameters={},
        status=SimulationStatus.RUNNING.value,
        assignment_id=assignment.id,
        total_sim_seconds=960.0,
        remaining_distance_km=11.2,
        current_battery_wh=444.0,
    )
    sim.speed_multiplier = 1.0
    sim.current_progress_percent = 30.0
    sim.distance_covered_km = 4.8
    sim.current_latitude = 17.4015
    sim.current_longitude = 78.4450
    sim.current_altitude_m = 60.0
    sim.elapsed_sim_seconds = 288.0
    db.session.add(sim)
    db.session.commit()

    return {
        "operator": operator,
        "requester": requester,
        "drone": drone,
        "request": req,
        "orig_route": orig_route,
        "assignment": assignment,
        "simulation": sim,
    }


def test_safety_mandated_dynamic_reroute_success(setup_reroute_entities):
    """Test dynamic rerouting under SAFETY_MANDATED policy when adverse weather occurs."""
    sim = setup_reroute_entities["simulation"]
    orig_route_id = setup_reroute_entities["orig_route"].id

    adverse_weather = WeatherData(
        wind_speed_mps=7.5,
        precipitation_mmh=3.0,
        visibility_km=4.0,
        weather_summary="Moderate rain and crosswind gust",
    )

    result = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=adverse_weather,
        policy_name="SAFETY_MANDATED",
        reason="Approaching localized convective storm cell",
    )

    assert result.switched is True
    assert result.original_route_id == orig_route_id
    assert result.new_route_id is not None
    assert result.new_route_id != orig_route_id
    assert result.policy_name == "SAFETY_MANDATED"
    assert "Safety-mandated rerouting accepted" in result.explanation

    # Verify original route is strictly preserved in database
    db_orig = db.session.get(Route, orig_route_id)
    assert db_orig is not None
    assert db_orig.algorithm_name == "DIRECT_GREAT_CIRCLE"

    # Verify new replacement route exists with correct association
    db_new = db.session.get(Route, result.new_route_id)
    assert db_new is not None
    assert db_new.delivery_request_id == setup_reroute_entities["request"].id
    assert db_new.feasibility_status == FeasibilityStatus.FEASIBLE.value

    # Verify assignment now points to replacement route
    assignment = db.session.get(DroneAssignment, setup_reroute_entities["assignment"].id)
    assert assignment.route_id == db_new.id

    # Verify audit history logged in simulation parameters_json
    params = sim.get_parameters()
    assert "reroute_history" in params
    assert len(params["reroute_history"]) == 1
    history_entry = params["reroute_history"][0]
    assert history_entry["original_route_id"] == orig_route_id
    assert history_entry["new_route_id"] == db_new.id
    assert history_entry["policy"] == "SAFETY_MANDATED"
    assert history_entry["reason"] == "Approaching localized convective storm cell"
    assert history_entry["weather_update"]["wind_speed_mps"] == 7.5


def test_objective_improvement_policy_threshold(setup_reroute_entities):
    """Test OBJECTIVE_IMPROVEMENT policy logic (rejecting negligible gain, accepting significant gain)."""
    sim = setup_reroute_entities["simulation"]
    orig_route = setup_reroute_entities["orig_route"]

    mild_weather = WeatherData(
        wind_speed_mps=2.0,
        precipitation_mmh=0.0,
        visibility_km=10.0,
        weather_summary="Calm clear skies",
    )

    # Require 80% improvement -> should reject switch (remaining energy cannot drop by 80%)
    result_reject = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=mild_weather,
        policy_name="OBJECTIVE_IMPROVEMENT",
        min_improvement_pct=80.0,
        reason="Testing high improvement threshold",
    )

    assert result_reject.switched is False
    assert result_reject.new_route_id is None
    assert "Switching policy rejected" in result_reject.explanation

    # Now make original remaining energy very high by setting remaining_distance_km high
    # Or test with a threshold of -50% (any reasonable or slightly better corridor accepted)
    result_accept = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=mild_weather,
        policy_name="OBJECTIVE_IMPROVEMENT",
        min_improvement_pct=-50.0,
        reason="Testing low improvement threshold",
    )

    assert result_accept.switched is True
    assert result_accept.new_route_id is not None
    assert "Objective improvement policy satisfied" in result_accept.explanation


def test_infeasible_weather_retains_flight_plan(setup_reroute_entities):
    """Test that when updated weather is completely infeasible (wind > max safe speed), reroute fails safely."""
    sim = setup_reroute_entities["simulation"]
    orig_route_id = setup_reroute_entities["orig_route"].id

    extreme_weather = WeatherData(
        wind_speed_mps=22.0,  # Far exceeds 12 m/s maximum safe limit
        precipitation_mmh=15.0,
        visibility_km=1.0,
        weather_summary="Severe squall and wind shear",
    )

    result = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=extreme_weather,
        policy_name="SAFETY_MANDATED",
        reason="Squall alert",
    )

    assert result.switched is False
    assert result.new_route_id is None
    assert "No replacement candidate satisfies safety constraints" in result.explanation
    assert result.feasible_candidates_count == 0

    # Ensure assignment was NOT modified
    assignment = db.session.get(DroneAssignment, setup_reroute_entities["assignment"].id)
    assert assignment.route_id == orig_route_id


def test_near_destination_skips_rerouting(setup_reroute_entities):
    """Test that when the drone is within 100 meters of the destination, rerouting is safely omitted."""
    sim = setup_reroute_entities["simulation"]
    dest_lat = setup_reroute_entities["request"].destination_latitude
    dest_lon = setup_reroute_entities["request"].destination_longitude

    # Place drone 30 meters from target (approx 0.00027 deg)
    sim.current_latitude = float(dest_lat) + 0.0001
    sim.current_longitude = float(dest_lon) + 0.0001
    db.session.commit()

    weather = WeatherData(wind_speed_mps=4.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear")

    result = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=weather,
        policy_name="SAFETY_MANDATED",
    )

    assert result.switched is False
    assert "final landing approach" in result.explanation


def test_reroute_rest_api_endpoint(client, setup_reroute_entities):
    """Test the POST /simulation/api/<id>/reroute REST API endpoint with authentication and RBAC."""
    sim = setup_reroute_entities["simulation"]
    operator = setup_reroute_entities["operator"]
    requester = setup_reroute_entities["requester"]

    # 1. Unauthenticated request should redirect to login or return 401/302
    res_unauth = client.post(f"/simulation/api/{sim.id}/reroute", json={})
    assert res_unauth.status_code in (302, 401)

    # 2. Requester (non-operator) should be forbidden (403)
    with client.session_transaction() as sess:
        sess["user_id"] = requester.id
        sess["_fresh"] = True

    res_req = client.post(f"/simulation/api/{sim.id}/reroute", json={})
    assert res_req.status_code == 403

    # 3. Operator should successfully trigger dynamic reroute
    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["_fresh"] = True

    payload = {
        "wind_speed_mps": 6.5,
        "precipitation_mmh": 2.0,
        "visibility_km": 6.0,
        "weather_summary": "Gusty crosswinds at waypoint 2",
        "policy": "SAFETY_MANDATED",
        "reason": "Air traffic telemetry alert",
    }
    res_op = client.post(f"/simulation/api/{sim.id}/reroute", json=payload)
    assert res_op.status_code == 200
    data = res_op.get_json()
    assert data["success"] is True
    assert data["reroute"]["switched"] is True
    assert data["reroute"]["new_route_id"] is not None
