"""Automated Tests for Algorithm Benchmark Reproducibility & Mathematical Invariants."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestPriority, RequestStatus, EmergencyType
from app.services.route_optimizer import RouteOptimizer
from app.services.drone_allocation_service import DroneAllocationService
from app.services.weather_service import WeatherData
from scripts.run_algorithm_benchmarks import (
    generate_route_scenarios,
    run_route_optimizer_benchmarks,
    run_allocation_benchmarks,
)


def test_route_optimizer_benchmark_deterministic_reproducibility():
    """Verify that the route optimizer produces identical numerical outputs across consecutive runs."""
    scenarios = generate_route_scenarios()[:3]  # First 3 scenarios

    run1 = run_route_optimizer_benchmarks(scenarios)
    run2 = run_route_optimizer_benchmarks(scenarios)

    assert len(run1) == len(run2)
    for r1, r2 in zip(run1, run2):
        assert r1["scenario_id"] == r2["scenario_id"]
        assert r1["algorithm_name"] == r2["algorithm_name"]
        assert r1["selected_corridor"] == r2["selected_corridor"]
        assert r1["distance_km"] == r2["distance_km"]
        assert r1["duration_min"] == r2["duration_min"]
        assert r1["energy_wh"] == r2["energy_wh"]
        assert r1["objective_score"] == r2["objective_score"]
        assert r1["is_feasible"] == r2["is_feasible"]


def test_allocation_benchmark_priority_inversion_behavior(app):
    """Verify that FCFS baseline causes critical request starvation during priority inversion,
    while Priority Best-Fit preserves critical life-support fulfillment."""
    with app.app_context():
        results = run_allocation_benchmarks(app)

    inversion_fcfs = next(
        (r for r in results if r["scale_id"] == "SCALE_INVERSION" and r["algorithm"] == "FCFS_GREEDY_BASELINE"),
        None,
    )
    inversion_pbf = next(
        (r for r in results if r["scale_id"] == "SCALE_INVERSION" and r["algorithm"] == "PRIORITY_BEST_FIT"),
        None,
    )

    assert inversion_fcfs is not None
    assert inversion_pbf is not None

    # Under FCFS, 5 low priority requests arrive first and consume the fleet, starving critical arrivals
    assert inversion_fcfs["critical_fulfillment_pct"] == 0.0

    # Under Priority Best-Fit, critical requests are triaged first
    assert inversion_pbf["critical_fulfillment_pct"] > 0.0
    assert inversion_pbf["critical_fulfillment_pct"] >= 40.0


def test_route_optimizer_vertical_climb_penalty_invariant():
    """Verify that the Multi-Objective Optimizer penalizes vertical climb,
    avoiding the unnecessary 80m climb chosen by the naive shortest-distance baseline."""
    # Test identical distance scenario
    origin_lat, origin_lng = 12.9716, 77.5946
    dest_lat, dest_lng = 12.9352, 77.6245

    weather = WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear")

    res_base = RouteOptimizer.optimize(
        pickup_lat=origin_lat, pickup_lng=origin_lng,
        dest_lat=dest_lat, dest_lng=dest_lng,
        payload_weight_kg=1.0,
        drone_cruise_speed_kmh=60.0,
        drone_max_payload_kg=3.0,
        drone_battery_capacity_wh=500.0,
        drone_current_battery_wh=500.0,
        weather=weather,
        algorithm_name="SHORTEST_FEASIBLE",
    )

    res_opt = RouteOptimizer.optimize(
        pickup_lat=origin_lat, pickup_lng=origin_lng,
        dest_lat=dest_lat, dest_lng=dest_lng,
        payload_weight_kg=1.0,
        drone_cruise_speed_kmh=60.0,
        drone_max_payload_kg=3.0,
        drone_battery_capacity_wh=500.0,
        drone_current_battery_wh=500.0,
        weather=weather,
        algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
    )

    assert res_base.is_feasible is True
    assert res_opt.is_feasible is True

    # Baseline tie-breaks to High Altitude (90m AGL)
    assert res_base.selected_route.candidate_id == "CORRIDOR_HIGH_ALTITUDE"
    assert res_base.selected_route.penalty_score > 0.0

    # Optimizer penalizes altitude steps and selects Direct (50m AGL)
    assert res_opt.selected_route.candidate_id == "CORRIDOR_DIRECT"
    assert round(res_opt.selected_route.penalty_score, 4) == 0.0
    assert res_opt.selected_route.objective_score < res_base.selected_route.objective_score
