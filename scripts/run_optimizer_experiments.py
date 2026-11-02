"""Reproducible experiment runner for route optimizer evaluation.

Academic Research & Demonstration Framework:
Compares the Baseline Shortest-Feasible-Route selector against the
Multi-Objective Weighted Optimizer across deterministic synthetic scenarios.

DISCLAIMER:
All inputs, coordinates, and drone metrics are synthetic simulation data.
Energy estimates represent mathematical software models and do NOT represent
actual physical wind-tunnel or flight-measured drone energy consumption.
"""

import csv
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.route_optimizer import (
    CandidateRouteGenerator,
    FeasibilityChecker,
    OptimizationResult,
    RouteOptimizer,
    haversine_distance,
)
from app.services.weather_service import WeatherData


# ==============================================================================
# DETERMINISTIC BENCHMARK SCENARIO DEFINITIONS
# ==============================================================================

@dataclass(frozen=True)
class DroneSpecification:
    """Simulated hardware specifications for an autonomous emergency delivery drone."""
    model_name: str
    maximum_payload_kg: float
    battery_capacity_wh: float
    current_battery_wh: float
    cruise_speed_kmh: float = 60.0
    battery_reserve_margin: float = 0.15


@dataclass(frozen=True)
class BenchmarkScenario:
    """Deterministic experimental scenario for comparative route evaluation."""
    scenario_id: str
    name: str
    description: str
    distance_category: str  # SHORT, MEDIUM, LONG
    pickup_coords: tuple[float, float]
    dest_coords: tuple[float, float]
    payload_weight_kg: float
    drone: DroneSpecification
    weather: Optional[WeatherData]
    weight_profile_name: str = "BALANCED"
    weights: Optional[Dict[str, float]] = None
    expected_feasibility: bool = True
    infeasibility_category: Optional[str] = None


# Weight profile matrices
WEIGHT_PROFILES = {
    "BALANCED": {"distance": 0.25, "duration": 0.35, "energy": 0.30, "penalty": 0.10},
    "SPEED_CRITICAL": {"distance": 0.10, "duration": 0.60, "energy": 0.20, "penalty": 0.10},
    "ENERGY_CONSERVING": {"distance": 0.15, "duration": 0.15, "energy": 0.60, "penalty": 0.10},
    "DISTANCE_MINIMIZED": {"distance": 0.70, "duration": 0.10, "energy": 0.10, "penalty": 0.10},
}

# Standard drone fleet profiles
DRONE_LIGHT = DroneSpecification(
    model_name="AeroMedic Rapid",
    maximum_payload_kg=2.5,
    battery_capacity_wh=450.0,
    current_battery_wh=450.0,
    cruise_speed_kmh=65.0,
)

DRONE_STANDARD = DroneSpecification(
    model_name="LifeLine HexaCruiser",
    maximum_payload_kg=5.0,
    battery_capacity_wh=850.0,
    current_battery_wh=850.0,
    cruise_speed_kmh=60.0,
)

DRONE_HEAVY = DroneSpecification(
    model_name="SkyLifter HeavyLoad",
    maximum_payload_kg=8.0,
    battery_capacity_wh=1400.0,
    current_battery_wh=1400.0,
    cruise_speed_kmh=55.0,
)

# Benchmark scenario catalog (14 synthetic scenarios covering varied operations)
SCENARIOS: List[BenchmarkScenario] = [
    # 1. Short Distance, Light Payload, Calm Skies
    BenchmarkScenario(
        scenario_id="EXP-01-SHORT-LIGHT-CALM",
        name="Short Distance Urban Transfer (Blood Units)",
        description="Routine urban clinic transfer over 4.2 km with light antivenom package under calm skies.",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),  # Hyderabad Central
        dest_coords=(17.412345, 78.508912),
        payload_weight_kg=1.0,
        drone=DRONE_LIGHT,
        weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=12.0, weather_summary="Clear"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=True,
    ),
    # 2. Short Distance, Heavy Payload
    BenchmarkScenario(
        scenario_id="EXP-02-SHORT-HEAVY-CALM",
        name="Short Distance Heavy Transfer (Surgical Kit)",
        description="Short 4.8 km transfer carrying heavy emergency surgical kit (4.5 kg) within capacity.",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.425000, 78.470000),
        payload_weight_kg=4.5,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=3.2, precipitation_mmh=0.5, visibility_km=10.0, weather_summary="Partly Cloudy"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=True,
    ),
    # 3. Medium Distance, Standard Payload, Moderate Headwind
    BenchmarkScenario(
        scenario_id="EXP-03-MED-STD-HEADWIND",
        name="Suburban Hospital Transit with Headwind",
        description="Medium 11.8 km flight with 2.2 kg diagnostic kit facing 6.5 m/s headwind.",
        distance_category="MEDIUM",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.450000, 78.390000),
        payload_weight_kg=2.2,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=6.5, precipitation_mmh=1.2, visibility_km=8.0, weather_summary="Moderate Wind"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=True,
    ),
    # 4. Long Distance, Standard Payload, Large Battery
    BenchmarkScenario(
        scenario_id="EXP-04-LONG-STD-FAVORABLE",
        name="Rural Health Outpost Relief (Long Range)",
        description="Long distance 21.5 km flight to rural outpost carrying pediatric vaccines.",
        distance_category="LONG",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.550000, 78.350000),
        payload_weight_kg=2.0,
        drone=DRONE_HEAVY,
        weather=WeatherData(wind_speed_mps=3.0, precipitation_mmh=0.0, visibility_km=15.0, weather_summary="Clear"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=True,
    ),
    # 5. Long Distance, Heavy Payload, Critical Speed
    BenchmarkScenario(
        scenario_id="EXP-05-LONG-HEAVY-SPEED",
        name="High-Priority Trauma Dispatch (Long & Heavy)",
        description="Long range 24.2 km flight carrying 6.0 kg defibrillator with speed-priority weighting.",
        distance_category="LONG",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.580000, 78.330000),
        payload_weight_kg=6.0,
        drone=DRONE_HEAVY,
        weather=WeatherData(wind_speed_mps=4.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
        weight_profile_name="SPEED_CRITICAL",
        weights=WEIGHT_PROFILES["SPEED_CRITICAL"],
        expected_feasibility=True,
    ),
    # 6. Weight Profile Comparison: Energy Conservation Focus
    BenchmarkScenario(
        scenario_id="EXP-06-MED-ENERGY-PROFILE",
        name="Energy Conservation Weight Profile Test",
        description="Identical 12.5 km corridor evaluated under energy-conserving optimization weights.",
        distance_category="MEDIUM",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.445000, 78.385000),
        payload_weight_kg=2.5,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=2.5, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
        weight_profile_name="ENERGY_CONSERVING",
        weights=WEIGHT_PROFILES["ENERGY_CONSERVING"],
        expected_feasibility=True,
    ),
    # 7. Low Battery State (Marginal Feasibility)
    BenchmarkScenario(
        scenario_id="EXP-07-LOW-BATT-MARGINAL",
        name="Partial Battery State (Marginal Feasibility)",
        description="Drone operating at 30% battery capacity (255 Wh of 850 Wh) across 6.5 km path.",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.430000, 78.450000),
        payload_weight_kg=1.8,
        drone=DroneSpecification(
            model_name="LifeLine HexaCruiser (Low Battery)",
            maximum_payload_kg=5.0,
            battery_capacity_wh=850.0,
            current_battery_wh=255.0,  # 30% remaining
            cruise_speed_kmh=60.0,
        ),
        weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=12.0, weather_summary="Clear"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=True,
    ),
    # 8. Infeasible Stress Test: Critical Battery Exhaustion
    BenchmarkScenario(
        scenario_id="EXP-08-INFEASIBLE-LOW-BATTERY",
        name="Infeasible: Insufficient Usable Battery",
        description="Drone battery severely depleted (45 Wh). Fails mandatory 15% reserve check.",
        distance_category="MEDIUM",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.480000, 78.360000),
        payload_weight_kg=2.0,
        drone=DroneSpecification(
            model_name="LifeLine HexaCruiser (Depleted)",
            maximum_payload_kg=5.0,
            battery_capacity_wh=850.0,
            current_battery_wh=45.0,  # Below threshold
            cruise_speed_kmh=60.0,
        ),
        weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="Battery Depletion",
    ),
    # 9. Infeasible Stress Test: Payload Exceeds Airframe Rating
    BenchmarkScenario(
        scenario_id="EXP-09-INFEASIBLE-OVERLOAD",
        name="Infeasible: Cargo Payload Exceeds Capacity",
        description="Cargo mass 5.5 kg submitted for light drone unit with max payload limit of 2.5 kg.",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.410000, 78.500000),
        payload_weight_kg=5.5,
        drone=DRONE_LIGHT,
        weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="Payload Capacity",
    ),
    # 10. Infeasible Stress Test: Gale-Force High Wind Velocity
    BenchmarkScenario(
        scenario_id="EXP-10-INFEASIBLE-WIND",
        name="Infeasible: High Atmospheric Wind Hazard",
        description="Observed sustained wind velocity 16.5 m/s exceeds aviation limit threshold (12.0 m/s).",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.420000, 78.490000),
        payload_weight_kg=1.5,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=16.5, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Gale Wind"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="High Wind Velocity",
    ),
    # 11. Infeasible Stress Test: Dense Fog Low Visibility
    BenchmarkScenario(
        scenario_id="EXP-11-INFEASIBLE-FOG",
        name="Infeasible: Low Visibility Fog Hazard",
        description="Ground visibility 1.2 km falls below VFR regulatory minimum (3.0 km).",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.415000, 78.480000),
        payload_weight_kg=1.5,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=3.0, precipitation_mmh=0.0, visibility_km=1.2, weather_summary="Dense Fog"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="Low Visibility",
    ),
    # 12. Infeasible Stress Test: Heavy Monsoon Precipitation
    BenchmarkScenario(
        scenario_id="EXP-12-INFEASIBLE-RAIN",
        name="Infeasible: Torrential Rain Storm",
        description="Precipitation rate 14.5 mm/h exceeds airframe water-ingress safety tolerance (8.0 mm/h).",
        distance_category="MEDIUM",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.440000, 78.430000),
        payload_weight_kg=2.0,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=5.0, precipitation_mmh=14.5, visibility_km=6.0, weather_summary="Heavy Rain"),
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="Excessive Precipitation",
    ),
    # 13. Infeasible Stress Test: Missing Weather Data (Fail-Safe Policy)
    BenchmarkScenario(
        scenario_id="EXP-13-INFEASIBLE-WEATHER-DATA",
        name="Infeasible: Unverified Weather Observation",
        description="Missing weather telemetry. Fail-safe system policy explicitly forbids blind dispatches.",
        distance_category="SHORT",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.420000, 78.470000),
        payload_weight_kg=1.5,
        drone=DRONE_STANDARD,
        weather=None,
        weight_profile_name="BALANCED",
        weights=WEIGHT_PROFILES["BALANCED"],
        expected_feasibility=False,
        infeasibility_category="Unverified Weather",
    ),
    # 14. Weight Sensitivity: Distance Minimized Profile
    BenchmarkScenario(
        scenario_id="EXP-14-DISTANCE-MIN-PROFILE",
        name="Distance-Minimized Weight Profile Test",
        description="Medium 13.0 km flight using high distance weight (0.70) to examine corridor selection.",
        distance_category="MEDIUM",
        pickup_coords=(17.385044, 78.486671),
        dest_coords=(17.460000, 78.410000),
        payload_weight_kg=2.0,
        drone=DRONE_STANDARD,
        weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
        weight_profile_name="DISTANCE_MINIMIZED",
        weights=WEIGHT_PROFILES["DISTANCE_MINIMIZED"],
        expected_feasibility=True,
    ),
]


# ==============================================================================
# EXPERIMENT EXECUTION ENGINE
# ==============================================================================

def get_git_commit_hash() -> str:
    """Retrieve current Git commit SHA for provenance recording."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def run_experiment_suite(scenarios: List[BenchmarkScenario]) -> List[Dict[str, Any]]:
    """Execute all benchmark scenarios under both Baseline and Weighted Optimizer.

    Ensures both algorithms receive identical candidate sets and physical constraints.
    """
    results: List[Dict[str, Any]] = []

    print("=" * 80)
    print("STARTING DETERMINISTIC OPTIMIZER BENCHMARK EXPERIMENT SUITE")
    print(f"Total Scenarios: {len(scenarios)} | Execution Environment: Python {platform.python_version()} on {platform.system()}")
    print("=" * 80)

    for i, scen in enumerate(scenarios, start=1):
        print(f"\n[{i:02d}/{len(scenarios):02d}] Scenario: {scen.scenario_id} - {scen.name}")
        straight_dist = haversine_distance(
            scen.pickup_coords[0], scen.pickup_coords[1],
            scen.dest_coords[0], scen.dest_coords[1],
        )
        print(f"     Straight-line distance: {straight_dist:.2f} km | Payload: {scen.payload_weight_kg:.1f} kg | Drone: {scen.drone.model_name}")

        # Common inputs for both algorithms
        kwargs = {
            "pickup_lat": scen.pickup_coords[0],
            "pickup_lng": scen.pickup_coords[1],
            "dest_lat": scen.dest_coords[0],
            "dest_lng": scen.dest_coords[1],
            "payload_weight_kg": scen.payload_weight_kg,
            "drone_cruise_speed_kmh": scen.drone.cruise_speed_kmh,
            "drone_max_payload_kg": scen.drone.maximum_payload_kg,
            "drone_battery_capacity_wh": scen.drone.battery_capacity_wh,
            "drone_current_battery_wh": scen.drone.current_battery_wh,
            "weather": scen.weather,
            "weights": scen.weights,
            "battery_reserve_margin": scen.drone.battery_reserve_margin,
            "include_return_trip": False,
        }

        # ----------------------------------------------------------------------
        # Algorithm 1: Baseline Shortest Feasible Route
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        baseline_res = RouteOptimizer.optimize(
            **kwargs,
            algorithm_name="SHORTEST_FEASIBLE",
        )
        t_baseline_ms = (time.perf_counter() - t0) * 1000.0

        # ----------------------------------------------------------------------
        # Algorithm 2: Weighted Multi-Objective Optimizer
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        opt_res = RouteOptimizer.optimize(
            **kwargs,
            algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
        )
        t_opt_ms = (time.perf_counter() - t0) * 1000.0

        # Verification: both received exact same candidate count
        assert baseline_res.candidate_count == opt_res.candidate_count, (
            "Integrity failure: Baseline and Optimizer received different candidate sets!"
        )
        assert baseline_res.feasible_count == opt_res.feasible_count, (
            "Integrity failure: Baseline and Optimizer computed different feasibility states!"
        )

        # Baseline metrics
        b_route = baseline_res.selected_route
        b_corridor = b_route.corridor_name if b_route else "None"
        b_dist = b_route.distance_km if b_route else 0.0
        b_time = b_route.duration_minutes if b_route else 0.0
        b_energy = b_route.energy_wh if b_route else 0.0
        b_score = b_route.objective_score if b_route else 0.0

        # Optimizer metrics
        o_route = opt_res.selected_route
        o_corridor = o_route.corridor_name if o_route else "None"
        o_dist = o_route.distance_km if o_route else 0.0
        o_time = o_route.duration_minutes if o_route else 0.0
        o_energy = o_route.energy_wh if o_route else 0.0
        o_score = o_route.objective_score if o_route else 0.0

        rejection_str = "; ".join(
            f"{r['candidate_id']}: {', '.join(r['reasons'])}"
            for r in opt_res.rejected_candidates
        ) if not opt_res.is_feasible else ""

        # Record comparative row
        record = {
            "scenario_id": scen.scenario_id,
            "scenario_name": scen.name,
            "distance_category": scen.distance_category,
            "straight_line_km": round(straight_dist, 3),
            "payload_weight_kg": scen.payload_weight_kg,
            "drone_model": scen.drone.model_name,
            "drone_max_payload_kg": scen.drone.maximum_payload_kg,
            "drone_battery_capacity_wh": scen.drone.battery_capacity_wh,
            "drone_current_battery_wh": scen.drone.current_battery_wh,
            "weather_condition": scen.weather.weather_summary if scen.weather else "MISSING",
            "wind_speed_mps": scen.weather.wind_speed_mps if scen.weather else None,
            "visibility_km": scen.weather.visibility_km if scen.weather else None,
            "precipitation_mmh": scen.weather.precipitation_mmh if scen.weather else None,
            "weight_profile": scen.weight_profile_name,
            "generated_candidates": opt_res.candidate_count,
            "feasible_candidates": opt_res.feasible_count,
            "is_feasible": opt_res.is_feasible,
            "infeasibility_category": scen.infeasibility_category or ("None" if opt_res.is_feasible else "Rejected"),
            # Baseline outcomes
            "baseline_corridor": b_corridor,
            "baseline_distance_km": round(b_dist, 3),
            "baseline_duration_min": round(b_time, 2),
            "baseline_energy_wh": round(b_energy, 2),
            "baseline_objective_score": round(b_score, 4),
            "baseline_exec_time_ms": round(t_baseline_ms, 3),
            # Optimizer outcomes
            "optimizer_corridor": o_corridor,
            "optimizer_distance_km": round(o_dist, 3),
            "optimizer_duration_min": round(o_time, 2),
            "optimizer_energy_wh": round(o_energy, 2),
            "optimizer_objective_score": round(o_score, 4),
            "optimizer_exec_time_ms": round(t_opt_ms, 3),
            # Trade-off differences (Optimizer - Baseline)
            "delta_distance_km": round(o_dist - b_dist, 3),
            "delta_duration_min": round(o_time - b_time, 2),
            "delta_energy_wh": round(o_energy - b_energy, 2),
            "delta_objective_score": round(o_score - b_score, 4),
            "rejection_reasons": rejection_str,
        }
        results.append(record)

        status_str = "FEASIBLE" if opt_res.is_feasible else f"INFEASIBLE ({scen.infeasibility_category})"
        print(f"     Status: {status_str}")
        if opt_res.is_feasible:
            print(f"     Baseline  : {b_corridor} -> {b_dist:.2f} km, {b_time:.1f} min, {b_energy:.1f} Wh (Cost Score: {b_score:.4f}, Latency: {t_baseline_ms:.2f}ms)")
            print(f"     Optimizer : {o_corridor} -> {o_dist:.2f} km, {o_time:.1f} min, {o_energy:.1f} Wh (Cost Score: {o_score:.4f}, Latency: {t_opt_ms:.2f}ms)")
            if b_corridor != o_corridor:
                print(f"     * TRADE-OFF: Optimizer diverged from shortest path to optimize composite cost score!")
        else:
            print(f"     Rejection verified across all {opt_res.candidate_count} candidates.")

    return results


def export_results(results: List[Dict[str, Any]], export_dir: str) -> str:
    """Export benchmark evaluation results to CSV and metadata to JSON."""
    os.makedirs(export_dir, exist_ok=True)
    csv_path = os.path.join(export_dir, "optimizer_benchmark_results.csv")
    meta_path = os.path.join(export_dir, "experiment_metadata.json")
    scen_path = os.path.join(export_dir, "scenario_definitions.json")

    # 1. Export CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    # 2. Export Metadata
    metadata = {
        "framework": "Smart Emergency Drone System - Comparative Route Optimizer Evaluation",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit_hash(),
        "environment": {
            "python_version": platform.python_version(),
            "os_platform": platform.platform(),
            "processor": platform.processor(),
        },
        "total_scenarios_evaluated": len(results),
        "algorithms_compared": [
            {
                "name": "SHORTEST_FEASIBLE (Baseline)",
                "selection_criterion": "Lexicographic sorting: minimum cumulative distance km, tiebreak on energy and duration.",
            },
            {
                "name": "WEIGHTED_MULTI_OBJECTIVE",
                "selection_criterion": "Min-max normalized multi-criteria objective function: J = w_d*d + w_t*t + w_e*e + w_p*p.",
            },
        ],
        "weight_profiles": WEIGHT_PROFILES,
        "disclaimer": (
            "Simulation software benchmark. Energy estimates use analytical kinematic power models "
            "and do NOT reflect physical flight-tested battery telemetry."
        ),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # 3. Export Scenario Definitions
    scenarios_data = [
        {
            "scenario_id": s.scenario_id,
            "name": s.name,
            "description": s.description,
            "distance_category": s.distance_category,
            "pickup": s.pickup_coords,
            "destination": s.dest_coords,
            "payload_weight_kg": s.payload_weight_kg,
            "drone_specs": asdict(s.drone),
            "weather": asdict(s.weather) if s.weather else None,
            "weight_profile": s.weight_profile_name,
            "expected_feasibility": s.expected_feasibility,
            "infeasibility_category": s.infeasibility_category,
        }
        for s in SCENARIOS
    ]
    with open(scen_path, "w", encoding="utf-8") as f:
        json.dump(scenarios_data, f, indent=2)

    return csv_path


def main():
    """Main execution function."""
    export_dir = os.path.join(PROJECT_ROOT, "data", "experiments")
    results = run_experiment_suite(SCENARIOS)
    csv_file = export_results(results, export_dir)
    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETE: Results exported successfully to:\n  - CSV: {csv_file}")
    print(f"  - Metadata: {os.path.join(export_dir, 'experiment_metadata.json')}")
    print(f"  - Scenarios: {os.path.join(export_dir, 'scenario_definitions.json')}")
    print("=" * 80)


if __name__ == "__main__":
    main()
