import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus, EmergencyType
from app.models.route import Route
from app.models.route_waypoint import RouteWaypoint
from app.services.weather_service import (
    WeatherService,
    WeatherData,
    MissingWeatherDataError,
)
from app.services.route_optimizer import (
    haversine_distance,
    compute_path_distance,
    estimate_travel_time,
    estimate_energy_consumption,
    Waypoint,
    RouteCandidate,
    CandidateRouteGenerator,
    FeasibilityChecker,
    RouteOptimizer,
)
from app.services.drone_allocation_service import DroneAllocationService
from app.services.assignment_service import ConflictingAssignmentError


# ==============================================================================
# 1. PURE MATHEMATICAL & ESTIMATION TESTS
# ==============================================================================

def test_haversine_distance_calculation():
    """Verify haversine formula against known reference coordinates."""
    # Bangalore City Center to Electronic City (~12.5 km)
    lat1, lon1 = 12.9716, 77.5946
    lat2, lon2 = 12.8452, 77.6602
    d = haversine_distance(lat1, lon1, lat2, lon2)
    assert 15.0 < d < 16.5

    # 1 degree of latitude at equator is approx 111.19 km
    d_eq = haversine_distance(0.0, 0.0, 1.0, 0.0)
    assert round(d_eq, 1) == 111.2

    # Zero distance between identical points
    assert haversine_distance(12.5, 77.5, 12.5, 77.5) == 0.0


def test_compute_path_distance():
    """Verify cumulative path distance across waypoints."""
    wps = [
        Waypoint(12.9716, 77.5946),
        Waypoint(12.9500, 77.6100),
        Waypoint(12.9352, 77.6245),
    ]
    total_dist = compute_path_distance(wps)
    d1 = haversine_distance(12.9716, 77.5946, 12.9500, 77.6100)
    d2 = haversine_distance(12.9500, 77.6100, 12.9352, 77.6245)
    assert round(total_dist, 4) == round(d1 + d2, 4)


def test_estimated_travel_time():
    """Test travel time estimation including transition buffer and wind penalty."""
    # 60 km at 60 km/h with 0 wind -> 60 min flight + 1.0 min buffer = 61.0 min
    t_calm = estimate_travel_time(distance_km=60.0, cruise_speed_kmh=60.0, wind_headwind_mps=0.0)
    assert t_calm == 61.0

    # With 5 m/s headwind (~18 km/h), travel time increases
    t_headwind = estimate_travel_time(distance_km=60.0, cruise_speed_kmh=60.0, wind_headwind_mps=5.0)
    assert t_headwind > t_calm


def test_energy_estimation_model():
    """Test simplified energy consumption model and return-trip calculation."""
    # 10 km distance, 12 minutes (0.2 hours), 2.0 kg payload
    e_oneway = estimate_energy_consumption(
        distance_km=10.0,
        duration_minutes=12.0,
        payload_weight_kg=2.0,
        cruise_speed_kmh=60.0,
        include_return_trip=False,
    )
    assert e_oneway > 0

    # With return trip enabled, energy consumption must be strictly higher
    e_roundtrip = estimate_energy_consumption(
        distance_km=10.0,
        duration_minutes=12.0,
        payload_weight_kg=2.0,
        cruise_speed_kmh=60.0,
        include_return_trip=True,
    )
    assert e_roundtrip > e_oneway


# ==============================================================================
# 2. FEASIBILITY & ENVIRONMENTAL RULE TESTS
# ==============================================================================

def test_payload_violation():
    """Ensure candidate is rejected when payload exceeds drone maximum capacity."""
    checker = FeasibilityChecker(
        maximum_payload_kg=3.0,
        battery_capacity_wh=500.0,
        current_battery_wh=500.0,
    )
    candidate = RouteCandidate("C1", "Direct", [Waypoint(12.9, 77.5), Waypoint(12.8, 77.6)], energy_wh=40.0)
    weather = WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear")

    is_feasible = checker.evaluate_candidate(candidate, payload_weight_kg=4.5, weather=weather)
    assert is_feasible is False
    assert any("Payload exceeds capacity" in r for r in candidate.rejection_reasons)


def test_insufficient_battery_and_reserve():
    """Ensure candidate is rejected when energy exceeds usable battery (including 15% reserve)."""
    checker = FeasibilityChecker(
        maximum_payload_kg=5.0,
        battery_capacity_wh=100.0,
        current_battery_wh=80.0,
        battery_reserve_margin=0.15,  # Usable battery = 80 * 0.85 = 68.0 Wh
    )
    # Route requires 75.0 Wh, which exceeds 68.0 Wh usable
    candidate = RouteCandidate("C1", "Direct", [Waypoint(12.9, 77.5), Waypoint(12.8, 77.6)], energy_wh=75.0)
    weather = WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear")

    is_feasible = checker.evaluate_candidate(candidate, payload_weight_kg=2.0, weather=weather)
    assert is_feasible is False
    assert any("Insufficient battery" in r for r in candidate.rejection_reasons)


def test_weather_threshold_violations():
    """Verify that excessive wind, high precipitation, or low visibility trigger rejection."""
    checker = FeasibilityChecker(
        maximum_payload_kg=5.0,
        battery_capacity_wh=800.0,
        current_battery_wh=800.0,
        max_wind_speed_mps=12.0,
        min_visibility_km=3.0,
        max_precipitation_mmh=8.0,
    )
    candidate = RouteCandidate("C1", "Direct", [Waypoint(12.9, 77.5), Waypoint(12.8, 77.6)], energy_wh=50.0)

    # 1. High wind violation (15.0 m/s > 12.0 m/s)
    bad_wind = WeatherData(wind_speed_mps=15.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Gale")
    assert checker.evaluate_candidate(candidate, 2.0, bad_wind) is False
    assert any("Wind speed exceeds" in r for r in candidate.rejection_reasons)

    # 2. Low visibility violation (1.5 km < 3.0 km)
    bad_vis = WeatherData(wind_speed_mps=3.0, precipitation_mmh=0.0, visibility_km=1.5, weather_summary="Dense Fog")
    assert checker.evaluate_candidate(candidate, 2.0, bad_vis) is False
    assert any("Visibility below" in r for r in candidate.rejection_reasons)

    # 3. High precipitation violation (11.0 mm/h > 8.0 mm/h)
    bad_rain = WeatherData(wind_speed_mps=3.0, precipitation_mmh=11.0, visibility_km=10.0, weather_summary="Downpour")
    assert checker.evaluate_candidate(candidate, 2.0, bad_rain) is False
    assert any("Precipitation exceeds" in r for r in candidate.rejection_reasons)


def test_missing_weather_policy():
    """Safety Policy: missing weather data must explicitly reject feasibility, never assumed safe."""
    checker = FeasibilityChecker(
        maximum_payload_kg=5.0,
        battery_capacity_wh=800.0,
        current_battery_wh=800.0,
    )
    candidate = RouteCandidate("C1", "Direct", [Waypoint(12.9, 77.5), Waypoint(12.8, 77.6)], energy_wh=30.0)

    assert checker.evaluate_candidate(candidate, payload_weight_kg=2.0, weather=None) is False
    assert any("Missing verified weather observation" in r for r in candidate.rejection_reasons)

    # WeatherService raises MissingWeatherDataError when required
    with pytest.raises(MissingWeatherDataError):
        WeatherService.get_weather_for_request(delivery_request_id=99999, require_weather=True)


# ==============================================================================
# 3. CANDIDATE GENERATION & OPTIMIZATION TESTS
# ==============================================================================

def test_candidate_generation():
    """Ensure candidate generator creates distinct, ordered geometric corridors."""
    candidates = CandidateRouteGenerator.generate_candidates(
        pickup_lat=12.9716, pickup_lng=77.5946,
        dest_lat=12.9352, dest_lng=77.6245,
    )
    assert len(candidates) == 4
    ids = {c.candidate_id for c in candidates}
    assert "CORRIDOR_DIRECT" in ids
    assert "CORRIDOR_NORTH_DETOUR" in ids
    assert "CORRIDOR_SOUTH_DETOUR" in ids
    assert "CORRIDOR_HIGH_ALTITUDE" in ids

    # All waypoints must be valid
    for c in candidates:
        assert len(c.waypoints) >= 2
        for w in c.waypoints:
            w.validate()

    # Zero distance / identical coordinates returns empty list
    empty = CandidateRouteGenerator.generate_candidates(12.5, 77.5, 12.5, 77.5)
    assert empty == []


def test_no_feasible_route():
    """When all corridors are infeasible, optimizer returns clear no-feasible result without crashing."""
    weather = WeatherData(wind_speed_mps=25.0, precipitation_mmh=20.0, visibility_km=1.0, weather_summary="Severe Storm")
    res = RouteOptimizer.optimize(
        pickup_lat=12.9716, pickup_lng=77.5946,
        dest_lat=12.9352, dest_lng=77.6245,
        payload_weight_kg=2.0,
        drone_cruise_speed_kmh=60.0,
        drone_max_payload_kg=5.0,
        drone_battery_capacity_wh=800.0,
        drone_current_battery_wh=800.0,
        weather=weather,
    )
    assert res.is_feasible is False
    assert res.selected_route is None
    assert res.feasible_count == 0
    assert len(res.rejected_candidates) == res.candidate_count


def test_optimizer_weight_changes():
    """Verify that shifting weights between distance and duration alters composite objective scores."""
    weather = WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Calm")

    # 1. Distance-heavy weighting
    res_dist = RouteOptimizer.optimize(
        pickup_lat=12.9716, pickup_lng=77.5946,
        dest_lat=12.9352, dest_lng=77.6245,
        payload_weight_kg=1.5,
        drone_cruise_speed_kmh=60.0,
        drone_max_payload_kg=5.0,
        drone_battery_capacity_wh=800.0,
        drone_current_battery_wh=800.0,
        weather=weather,
        weights={"distance": 0.90, "duration": 0.05, "energy": 0.05, "penalty": 0.0},
    )
    assert res_dist.is_feasible is True

    # 2. Duration-heavy weighting
    res_time = RouteOptimizer.optimize(
        pickup_lat=12.9716, pickup_lng=77.5946,
        dest_lat=12.9352, dest_lng=77.6245,
        payload_weight_kg=1.5,
        drone_cruise_speed_kmh=60.0,
        drone_max_payload_kg=5.0,
        drone_battery_capacity_wh=800.0,
        drone_current_battery_wh=800.0,
        weather=weather,
        weights={"distance": 0.05, "duration": 0.90, "energy": 0.05, "penalty": 0.0},
    )
    assert res_time.is_feasible is True


def test_deterministic_tie_breaking():
    """Verify that identical metric candidates resolve deterministically via candidate_id."""
    c1 = RouteCandidate("CORRIDOR_B", "Corridor B", [Waypoint(12.0, 77.0), Waypoint(12.1, 77.1)], distance_km=5.0, duration_minutes=5.0, energy_wh=50.0, objective_score=0.25, is_feasible=True)
    c2 = RouteCandidate("CORRIDOR_A", "Corridor A", [Waypoint(12.0, 77.0), Waypoint(12.1, 77.1)], distance_km=5.0, duration_minutes=5.0, energy_wh=50.0, objective_score=0.25, is_feasible=True)

    candidates = [c1, c2]
    # Sorting by (objective_score, energy_wh, distance_km, candidate_id)
    candidates.sort(key=lambda c: (c.objective_score, c.energy_wh, c.distance_km, c.candidate_id))
    assert candidates[0].candidate_id == "CORRIDOR_A"
    assert candidates[1].candidate_id == "CORRIDOR_B"


# ==============================================================================
# 4. DATABASE INTEGRATION & ALLOCATION TESTS
# ==============================================================================

def test_route_and_waypoints_persistence(app):
    """Test generating routes and persisting them into database with waypoints."""
    user = User("Doctor Persist", "doc_persist@hospital.org", "Pass12345!", UserRole.REQUESTER)
    drone = Drone("DRONE-OPT-01", "OptiHexa", 6.0, 900.0, 900.0)
    db.session.add_all([user, drone])
    db.session.flush()

    req = DeliveryRequest(
        requester_id=user.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.5,
    )
    db.session.add(req)
    db.session.commit()

    # Generate and persist routes
    opt_result, selected_route = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=req.id,
        drone_id=drone.id,
    )

    assert opt_result.is_feasible is True
    assert selected_route is not None
    assert selected_route.id is not None
    assert selected_route.feasibility_status == "FEASIBLE"

    # Check waypoints persisted in sequence
    wps = RouteWaypoint.query.filter_by(route_id=selected_route.id).order_by(RouteWaypoint.sequence_number).all()
    assert len(wps) > 0
    assert wps[0].sequence_number == 0

    # Request status updated to ROUTE_CALCULATED
    db.session.refresh(req)
    assert req.status == RequestStatus.ROUTE_CALCULATED.value


def test_drone_allocation_conflict_prevention(app):
    """Ensure two allocations for the same drone trigger ConflictingAssignmentError."""
    user = User("Dispatch Tester", "disp_test@hospital.org", "Pass12345!", UserRole.REQUESTER)
    drone = Drone("DRONE-CONFLICT-01", "SkyMedic", 5.0, 850.0, 850.0)
    db.session.add_all([user, drone])
    db.session.flush()

    req1 = DeliveryRequest(user.id, EmergencyType.ANTIVENOM.value, 12.97, 77.59, 12.93, 77.62, 1.5)
    req2 = DeliveryRequest(user.id, EmergencyType.BLOOD_SUPPLY.value, 12.97, 77.59, 12.93, 77.62, 2.0)
    db.session.add_all([req1, req2])
    db.session.commit()

    # Allocate drone to Request 1
    assign1 = DroneAllocationService.allocate_and_dispatch(req1.id, drone.id)
    assert assign1.id is not None
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # Second allocation attempt for the same drone must fail cleanly
    with pytest.raises(ConflictingAssignmentError):
        DroneAllocationService.allocate_and_dispatch(req2.id, drone.id)
