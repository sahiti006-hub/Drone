"""Comprehensive Benchmark Suite for Route Optimization & Multi-Drone Allocation.

Empirical Research & Algorithmic Audit:
Benchmarks:
1. Route Optimization: Baseline (Shortest-Feasible) vs. Weighted Multi-Objective across
   diverse distances, payloads, weather states, and weight configurations.
2. Multi-Drone Batch Allocation: Priority Best-Fit vs. FCFS Greedy Baseline across
   increasing batch sizes (5 to 80 requests) and fleet contention profiles.
3. In-Flight Dynamic Rerouting: Safety-Mandated vs. Objective-Improvement switching policies.

DISCLAIMER:
All inputs, coordinates, and drone specifications represent synthetic simulation data.
Energy estimates represent mathematical software aerodynamic models and do NOT represent
flight-measured physical battery consumption.
"""

import csv
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.services.route_optimizer import (
    RouteOptimizer,
    RouteCandidate,
    OptimizationResult,
    haversine_distance,
)
from app.services.drone_allocation_service import (
    DroneAllocationService,
    MultiDroneAllocationPlan,
)
from app.services.weather_service import WeatherData
from app.services.simulation_service import SimulationService, DynamicRerouteResult


# ==============================================================================
# 1. ROUTE OPTIMIZATION BENCHMARK
# ==============================================================================

@dataclass
class RouteScenario:
    scenario_id: str
    name: str
    category: str
    pickup_lat: float
    pickup_lng: float
    dest_lat: float
    dest_lng: float
    payload_kg: float
    drone_speed_kmh: float
    drone_max_payload_kg: float
    drone_battery_capacity_wh: float
    drone_current_battery_wh: float
    weather: Optional[WeatherData]
    expected_feasible: bool
    notes: str


def generate_route_scenarios() -> List[RouteScenario]:
    """Generate 12 deterministic scenarios covering diverse distances, payloads, and weather."""
    # Origin: Bangalore Central (12.9716, 77.5946)
    origin_lat, origin_lng = 12.9716, 77.5946

    scenarios = [
        # Short Distance (3.5 - 5.0 km)
        RouteScenario(
            scenario_id="ROUTE-01",
            name="Short Light Transit - Calm",
            category="SHORT_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,  # St Johns Koramangala ~5.2 km
            payload_kg=1.0,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=500.0, drone_current_battery_wh=500.0,
            weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
            expected_feasible=True,
            notes="Ideal short corridor, light payload, calm skies",
        ),
        RouteScenario(
            scenario_id="ROUTE-02",
            name="Short Heavy Payload - Moderate Wind",
            category="SHORT_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=4.5,
            drone_speed_kmh=55.0, drone_max_payload_kg=5.0,
            drone_battery_capacity_wh=800.0, drone_current_battery_wh=750.0,
            weather=WeatherData(wind_speed_mps=7.5, precipitation_mmh=1.0, visibility_km=8.0, weather_summary="Breezy"),
            expected_feasible=True,
            notes="Near payload limit (4.5kg on 5.0kg airframe)",
        ),

        # Medium Distance (10.0 - 15.0 km)
        RouteScenario(
            scenario_id="ROUTE-03",
            name="Medium Medical Transit - Low Altitude vs Climb",
            category="MEDIUM_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=13.0358, dest_lng=77.5970,  # Hebbal ~7.2 km north
            payload_kg=2.0,
            drone_speed_kmh=65.0, drone_max_payload_kg=4.0,
            drone_battery_capacity_wh=600.0, drone_current_battery_wh=550.0,
            weather=WeatherData(wind_speed_mps=4.0, precipitation_mmh=0.0, visibility_km=9.0, weather_summary="Fair"),
            expected_feasible=True,
            notes="Tests vertical climb penalty between Direct (50m) and High Altitude (90m)",
        ),
        RouteScenario(
            scenario_id="ROUTE-04",
            name="Medium Transit - Strong Headwind (11 m/s)",
            category="MEDIUM_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.8996, dest_lng=77.4827,  # Kengeri ~14.5 km
            payload_kg=2.5,
            drone_speed_kmh=60.0, drone_max_payload_kg=4.0,
            drone_battery_capacity_wh=750.0, drone_current_battery_wh=650.0,
            weather=WeatherData(wind_speed_mps=11.0, precipitation_mmh=2.0, visibility_km=6.0, weather_summary="Windy"),
            expected_feasible=True,
            notes="Adverse headwind near maximum permissible threshold (12 m/s)",
        ),

        # Long Distance (20.0 - 28.0 km)
        RouteScenario(
            scenario_id="ROUTE-05",
            name="Long Regional Emergency - High Capacity Drone",
            category="LONG_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=13.1986, dest_lng=77.7066,  # Devanahalli Airport ~28.0 km
            payload_kg=1.8,
            drone_speed_kmh=75.0, drone_max_payload_kg=4.0,
            drone_battery_capacity_wh=1200.0, drone_current_battery_wh=1200.0,
            weather=WeatherData(wind_speed_mps=3.5, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
            expected_feasible=True,
            notes="Long distance test assessing battery endurance and speed scaling",
        ),
        RouteScenario(
            scenario_id="ROUTE-06",
            name="Long Regional - Tight Battery Reserve",
            category="LONG_DISTANCE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=13.1986, dest_lng=77.7066,
            payload_kg=2.5,
            drone_speed_kmh=70.0, drone_max_payload_kg=4.0,
            drone_battery_capacity_wh=800.0, drone_current_battery_wh=420.0,
            weather=WeatherData(wind_speed_mps=5.0, precipitation_mmh=0.0, visibility_km=8.0, weather_summary="Fair"),
            expected_feasible=False,
            notes="Insufficient usable battery after mandatory 15% reserve deduction",
        ),

        # Adverse Stress & Rejection Scenarios
        RouteScenario(
            scenario_id="ROUTE-07",
            name="Stress - Payload Exceeds Maximum Capacity",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=6.5,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=600.0, drone_current_battery_wh=600.0,
            weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
            expected_feasible=False,
            notes="Cargo overload (6.5kg on 3.0kg drone) must be rejected immediately",
        ),
        RouteScenario(
            scenario_id="ROUTE-08",
            name="Stress - Gale Wind Safety Gate Violation (16.5 m/s)",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=1.0,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=500.0, drone_current_battery_wh=500.0,
            weather=WeatherData(wind_speed_mps=16.5, precipitation_mmh=3.0, visibility_km=5.0, weather_summary="Severe Wind"),
            expected_feasible=False,
            notes="Wind 16.5 m/s exceeds 12.0 m/s threshold -> 100% rejection",
        ),
        RouteScenario(
            scenario_id="ROUTE-09",
            name="Stress - Heavy Monsoon Downpour (15.0 mm/h)",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=1.5,
            drone_speed_kmh=60.0, drone_max_payload_kg=4.0,
            drone_battery_capacity_wh=600.0, drone_current_battery_wh=600.0,
            weather=WeatherData(wind_speed_mps=6.0, precipitation_mmh=15.0, visibility_km=3.5, weather_summary="Torrential Rain"),
            expected_feasible=False,
            notes="Rain 15 mm/h exceeds 8.0 mm/h tolerance -> All corridors rejected",
        ),
        RouteScenario(
            scenario_id="ROUTE-10",
            name="Stress - Dense Fog / Sub-VFR Visibility (1.5 km)",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=1.2,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=500.0, drone_current_battery_wh=500.0,
            weather=WeatherData(wind_speed_mps=1.0, precipitation_mmh=0.0, visibility_km=1.5, weather_summary="Dense Fog"),
            expected_feasible=False,
            notes="Visibility 1.5 km below 3.0 km minimum safety limit",
        ),
        RouteScenario(
            scenario_id="ROUTE-11",
            name="Stress - Unverified Missing Atmospheric Telemetry",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=1.0,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=500.0, drone_current_battery_wh=500.0,
            weather=None,
            expected_feasible=False,
            notes="Fail-safe policy: dispatch prohibited without verified weather data",
        ),
        RouteScenario(
            scenario_id="ROUTE-12",
            name="Stress - Severely Depleted Battery at Launch (40 Wh)",
            category="STRESS_INFEASIBLE",
            pickup_lat=origin_lat, pickup_lng=origin_lng,
            dest_lat=12.9352, dest_lng=77.6245,
            payload_kg=1.0,
            drone_speed_kmh=60.0, drone_max_payload_kg=3.0,
            drone_battery_capacity_wh=500.0, drone_current_battery_wh=40.0,
            weather=WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear"),
            expected_feasible=False,
            notes="Drone battery 40 Wh < 15% reserve floor (75 Wh) -> immediate rejection",
        ),
    ]
    return scenarios


def run_route_optimizer_benchmarks(scenarios: List[RouteScenario]) -> List[Dict[str, Any]]:
    """Execute comparative benchmark between Baseline and Weighted Optimizer profiles."""
    results = []

    configs = [
        ("BASELINE_SHORTEST_FEASIBLE", "SHORTEST_FEASIBLE", None),
        ("OPTIMIZER_BALANCED", "WEIGHTED_MULTI_OBJECTIVE", {"distance": 0.25, "duration": 0.35, "energy": 0.30, "penalty": 0.10}),
        ("OPTIMIZER_SPEED_CRITICAL", "WEIGHTED_MULTI_OBJECTIVE", {"distance": 0.10, "duration": 0.60, "energy": 0.20, "penalty": 0.10}),
        ("OPTIMIZER_ENERGY_CONSERVING", "WEIGHTED_MULTI_OBJECTIVE", {"distance": 0.10, "duration": 0.20, "energy": 0.60, "penalty": 0.10}),
    ]

    for sc in scenarios:
        for profile_id, algo_name, weights in configs:
            # Measure pure execution solve time (isolated from setup)
            t0 = time.perf_counter_ns()
            res = RouteOptimizer.optimize(
                pickup_lat=sc.pickup_lat,
                pickup_lng=sc.pickup_lng,
                dest_lat=sc.dest_lat,
                dest_lng=sc.dest_lng,
                payload_weight_kg=sc.payload_kg,
                drone_cruise_speed_kmh=sc.drone_speed_kmh,
                drone_max_payload_kg=sc.drone_max_payload_kg,
                drone_battery_capacity_wh=sc.drone_battery_capacity_wh,
                drone_current_battery_wh=sc.drone_current_battery_wh,
                weather=sc.weather,
                weights=weights,
                algorithm_name=algo_name,
            )
            t1 = time.perf_counter_ns()
            exec_time_ms = (t1 - t0) / 1_000_000.0

            sel = res.selected_route
            results.append({
                "scenario_id": sc.scenario_id,
                "scenario_name": sc.name,
                "category": sc.category,
                "profile_id": profile_id,
                "algorithm_name": algo_name,
                "is_feasible": res.is_feasible,
                "execution_time_ms": round(exec_time_ms, 4),
                "candidate_count": res.candidate_count,
                "feasible_count": res.feasible_count,
                "rejected_count": res.candidate_count - res.feasible_count,
                "selected_corridor": sel.corridor_name if sel else "NONE",
                "distance_km": round(sel.distance_km, 3) if sel else 0.0,
                "duration_min": round(sel.duration_minutes, 2) if sel else 0.0,
                "energy_wh": round(sel.energy_wh, 2) if sel else 0.0,
                "penalty_score": round(sel.penalty_score, 4) if sel else 0.0,
                "objective_score": round(sel.objective_score, 4) if sel else 0.0,
            })

    return results


# ==============================================================================
# 2. MULTI-DRONE BATCH ALLOCATION BENCHMARK
# ==============================================================================

@dataclass
class AllocationScaleScenario:
    scale_id: str
    name: str
    num_requests: int
    num_drones: int
    description: str


def run_allocation_benchmarks(app_instance) -> List[Dict[str, Any]]:
    """Benchmark Priority Best-Fit vs. FCFS Greedy Baseline across scale increments."""
    scale_definitions = [
        AllocationScaleScenario("SCALE_TINY", "Small Fleet / Low Contention", 5, 3, "5 requests, 3 drones"),
        AllocationScaleScenario("SCALE_SMALL", "Balanced Fleet / Medium Contention", 12, 6, "12 requests, 6 drones"),
        AllocationScaleScenario("SCALE_MEDIUM", "Municipal Fleet / High Contention", 25, 12, "25 requests, 12 drones"),
        AllocationScaleScenario("SCALE_LARGE", "Regional Dispatch / Heavy Contention", 50, 20, "50 requests, 20 drones"),
        AllocationScaleScenario("SCALE_STRESS", "Severe Fleet Starvation Stress", 80, 25, "80 requests, 25 drones"),
        AllocationScaleScenario("SCALE_INVERSION", "Priority Inversion Bottleneck", 10, 4, "5 low-priority requests arrive first, competing with 5 later critical requests"),
    ]

    results = []
    rng = random.Random(42)  # Fixed deterministic seed

    with app_instance.app_context():
        db.create_all()

        # Ensure base requester exists
        requester = User.query.filter_by(email="benchmark_requester@emergency.org").first()
        if not requester:
            requester = User(
                full_name="Benchmark Requester",
                email="benchmark_requester@emergency.org",
                password="SecurePassPassword123!",
                role=UserRole.REQUESTER.value,
            )
            db.session.add(requester)
            db.session.commit()

        base_lat, base_lng = 12.9716, 77.5946

        for scale in scale_definitions:
            # Clean up prior benchmark transient records
            DeliveryRequest.query.filter(DeliveryRequest.requester_id == requester.id).delete()
            Drone.query.filter(Drone.drone_code.like("BENCH-%")).delete()
            db.session.commit()

            # 1. Generate Drones for this scale
            created_drone_ids = []
            for d_idx in range(scale.num_drones):
                # Tiered fleet: Light (1.5 - 2.5 kg), Medium (3.0 - 5.0 kg), Heavy (6.0 - 8.5 kg)
                tier = d_idx % 3
                if tier == 0:
                    max_payload = 2.5
                    batt_cap = 500.0
                    model = "SwiftCourier V1"
                elif tier == 1:
                    max_payload = 5.0
                    batt_cap = 850.0
                    model = "MediHexa MK-II"
                else:
                    max_payload = 8.0
                    batt_cap = 1200.0
                    model = "TitanLifter H8"

                # Battery state of charge between 60% and 100%
                soc = 0.60 + (rng.random() * 0.40)
                drone = Drone(
                    drone_code=f"BENCH-UAV-{scale.scale_id}-{d_idx+1:02d}",
                    model_name=model,
                    maximum_payload_kg=max_payload,
                    battery_capacity_wh=batt_cap,
                    current_battery_wh=round(batt_cap * soc, 1),
                    cruise_speed_kmh=60.0 + (tier * 5.0),
                    status=DroneStatus.AVAILABLE.value,
                )
                db.session.add(drone)
                db.session.flush()
                created_drone_ids.append(drone.id)

            # 2. Generate Requests for this scale
            created_request_ids = []
            now = datetime.now(timezone.utc)

            priorities_pool = [
                RequestPriority.CRITICAL.value,
                RequestPriority.HIGH.value,
                RequestPriority.MEDIUM.value,
                RequestPriority.LOW.value,
            ]

            for r_idx in range(scale.num_requests):
                if scale.scale_id == "SCALE_INVERSION":
                    # First half are LOW priority, second half are CRITICAL priority
                    priority = RequestPriority.LOW.value if r_idx < 5 else RequestPriority.CRITICAL.value
                    # Low priority requests arrive earlier
                    created_at = now - timedelta(minutes=(100 - r_idx))
                    payload = 2.0 if r_idx < 5 else 4.5  # Critical ones are heavy
                else:
                    priority = priorities_pool[r_idx % 4]
                    created_at = now - timedelta(minutes=(scale.num_requests - r_idx))
                    # Payloads between 0.8 kg and 6.5 kg
                    payload = round(0.8 + rng.random() * 5.5, 2)

                # Destination coordinates within 4 - 18 km radius
                angle = rng.random() * 2 * math.pi
                dist_km = 4.0 + rng.random() * 14.0
                d_lat = (dist_km / 111.0) * math.cos(angle)
                d_lng = (dist_km / (111.0 * math.cos(math.radians(base_lat)))) * math.sin(angle)

                req = DeliveryRequest(
                    requester_id=requester.id,
                    emergency_type=EmergencyType.BLOOD_SUPPLY.value,
                    pickup_latitude=base_lat,
                    pickup_longitude=base_lng,
                    destination_latitude=base_lat + d_lat,
                    destination_longitude=base_lng + d_lng,
                    payload_weight_kg=payload,
                    priority=priority,
                    status=RequestStatus.PENDING.value,
                )
                req.created_at = created_at
                db.session.add(req)
                db.session.flush()
                created_request_ids.append(req.id)

            db.session.commit()

            # 3. Benchmark both algorithms on exact identical dataset
            for algo in ["FCFS_GREEDY_BASELINE", "PRIORITY_BEST_FIT"]:
                t0 = time.perf_counter_ns()
                plan = DroneAllocationService.evaluate_multi_drone_allocation(
                    request_ids=created_request_ids,
                    drone_ids=created_drone_ids,
                    algorithm_name=algo,
                    require_weather=False,
                )
                t1 = time.perf_counter_ns()
                solve_time_ms = (t1 - t0) / 1_000_000.0

                # Analyze priority-specific fulfillment
                req_priority_map = {
                    r.id: r.priority
                    for r in DeliveryRequest.query.filter(DeliveryRequest.id.in_(created_request_ids)).all()
                }

                crit_total = sum(1 for p in req_priority_map.values() if p == RequestPriority.CRITICAL.value)
                high_total = sum(1 for p in req_priority_map.values() if p == RequestPriority.HIGH.value)
                med_total = sum(1 for p in req_priority_map.values() if p == RequestPriority.MEDIUM.value)
                low_total = sum(1 for p in req_priority_map.values() if p == RequestPriority.LOW.value)

                crit_matched = sum(1 for m in plan.matches if req_priority_map.get(m.request_id) == RequestPriority.CRITICAL.value)
                high_matched = sum(1 for m in plan.matches if req_priority_map.get(m.request_id) == RequestPriority.HIGH.value)
                med_matched = sum(1 for m in plan.matches if req_priority_map.get(m.request_id) == RequestPriority.MEDIUM.value)
                low_matched = sum(1 for m in plan.matches if req_priority_map.get(m.request_id) == RequestPriority.LOW.value)

                crit_rate = (crit_matched / crit_total * 100.0) if crit_total > 0 else 0.0
                high_rate = (high_matched / high_total * 100.0) if high_total > 0 else 0.0
                med_rate = (med_matched / med_total * 100.0) if med_total > 0 else 0.0
                low_rate = (low_matched / low_total * 100.0) if low_total > 0 else 0.0

                mean_dist = (sum(m.distance_km for m in plan.matches) / len(plan.matches)) if plan.matches else 0.0
                mean_headroom = (sum(m.drone_max_payload_kg - m.request_payload_kg for m in plan.matches) / len(plan.matches)) if plan.matches else 0.0

                results.append({
                    "scale_id": scale.scale_id,
                    "scale_name": scale.name,
                    "algorithm": algo,
                    "total_requests": scale.num_requests,
                    "total_drones": scale.num_drones,
                    "matched_count": len(plan.matches),
                    "unmatched_count": len(plan.unmatched_requests),
                    "idle_drones": len(plan.idle_drones),
                    "overall_fulfillment_pct": round(plan.overall_fulfillment_rate_pct, 1),
                    "critical_fulfillment_pct": round(crit_rate, 1),
                    "high_fulfillment_pct": round(high_rate, 1),
                    "medium_fulfillment_pct": round(med_rate, 1),
                    "low_fulfillment_pct": round(low_rate, 1),
                    "total_fleet_energy_wh": round(plan.total_fleet_energy_wh, 2),
                    "mean_route_distance_km": round(mean_dist, 2),
                    "mean_capacity_headroom_kg": round(mean_headroom, 2),
                    "execution_time_ms": round(solve_time_ms, 3),
                })

        # Teardown benchmark transient records
        DeliveryRequest.query.filter(DeliveryRequest.requester_id == requester.id).delete()
        Drone.query.filter(Drone.drone_code.like("BENCH-%")).delete()
        db.session.commit()

    return results


# ==============================================================================
# 3. DYNAMIC REROUTING BENCHMARK
# ==============================================================================

def run_dynamic_rerouting_benchmarks(app_instance) -> List[Dict[str, Any]]:
    """Benchmark dynamic in-flight rerouting policies against baseline static plans."""
    results = []

    with app_instance.app_context():
        db.create_all()

        # Setup transient user, drone, request, assignment, simulation
        requester = User.query.filter_by(email="reroute_bench@emergency.org").first()
        if not requester:
            requester = User("Reroute Requester", "reroute_bench@emergency.org", "Pass12345!", UserRole.REQUESTER.value)
            db.session.add(requester)
            db.session.commit()

        drone = Drone(
            drone_code="UAV-REROUTE-BENCH-01",
            model_name="SkyCourier Pro",
            maximum_payload_kg=4.0,
            battery_capacity_wh=800.0,
            current_battery_wh=750.0,
            cruise_speed_kmh=60.0,
            status=DroneStatus.AVAILABLE.value,
        )
        db.session.add(drone)
        db.session.commit()

        req = DeliveryRequest(
            requester_id=requester.id,
            emergency_type=EmergencyType.ANTIVENOM.value,
            pickup_latitude=12.9716, pickup_longitude=77.5946,
            destination_latitude=12.9352, destination_longitude=77.6245,  # ~5.2 km
            payload_weight_kg=1.5,
            priority=RequestPriority.CRITICAL.value,
            status=RequestStatus.PENDING.value,
        )
        db.session.add(req)
        db.session.commit()

        # Compute initial route
        opt_res, orig_route = DroneAllocationService.generate_and_persist_routes(
            delivery_request_id=req.id,
            drone_id=drone.id,
            algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
            require_weather=False,
        )

        asg = DroneAssignment(
            delivery_request_id=req.id,
            drone_id=drone.id,
            route_id=orig_route.id,
            status=AssignmentStatus.ACTIVE.value,
        )
        db.session.add(asg)
        db.session.commit()

        sim = SimulationRun(
            run_code="SIM-BENCH-REROUTE-01",
            parameters={},
            status=SimulationStatus.RUNNING.value,
            assignment_id=asg.id,
            total_sim_seconds=480.0,
            remaining_distance_km=2.8,
            current_battery_wh=680.0,
        )
        sim.current_latitude = 12.9550
        sim.current_longitude = 77.6080
        sim.current_altitude_m = 50.0
        sim.current_speed_kmh = 60.0
        sim.current_progress_percent = 46.0
        db.session.add(sim)
        db.session.commit()

        reroute_scenarios = [
            # 1. Storm violation
            (
                "REROUTE-01",
                "Severe In-Flight Convective Storm (16.5 m/s wind)",
                WeatherData(wind_speed_mps=16.5, precipitation_mmh=4.0, visibility_km=5.0, weather_summary="Severe Storm"),
                "SAFETY_MANDATED",
                5.0,
                "Current corridor becomes infeasible. Detour required.",
            ),
            # 2. Objective improvement: Wind shift benefits high-altitude corridor
            (
                "REROUTE-02",
                "Favorable Wind Shift (>15% Energy Reduction)",
                WeatherData(wind_speed_mps=3.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Favorable Breeze"),
                "OBJECTIVE_IMPROVEMENT",
                5.0,
                "Tests energy-saving switching threshold.",
            ),
            # 3. Marginal wind change (rejected by policy)
            (
                "REROUTE-03",
                "Negligible Wind Shift (<5% Improvement)",
                WeatherData(wind_speed_mps=2.0, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Calm"),
                "OBJECTIVE_IMPROVEMENT",
                15.0,  # High threshold 15% -> should reject
                "Tests stability: suppresses unnecessary flight plan changes.",
            ),
        ]

        for s_id, s_name, w_data, policy, thresh, desc in reroute_scenarios:
            t0 = time.perf_counter_ns()
            res = SimulationService.evaluate_and_reroute(
                simulation_id=sim.id,
                updated_weather=w_data,
                policy_name=policy,
                min_improvement_pct=thresh,
                reason=s_name,
            )
            t1 = time.perf_counter_ns()
            eval_time_ms = (t1 - t0) / 1_000_000.0

            results.append({
                "scenario_id": s_id,
                "scenario_name": s_name,
                "policy_name": policy,
                "threshold_pct": thresh,
                "switched": res.switched,
                "original_route_id": res.original_route_id,
                "new_route_id": res.new_route_id,
                "candidates_evaluated": res.candidates_evaluated_count,
                "execution_time_ms": round(eval_time_ms, 3),
                "explanation": res.explanation,
                "description": desc,
            })

        # Clean rollback of in-memory benchmark session
        db.session.rollback()
        db.drop_all()

    return results


# ==============================================================================
# 4. CHART GENERATION (Pure Python SVG)
# ==============================================================================

def generate_svg_charts(
    route_results: List[Dict[str, Any]],
    alloc_results: List[Dict[str, Any]],
    output_dir: Path,
):
    """Generate high-resolution vector SVG charts based on empirical measurements."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # Chart 1: Priority Fulfillment Comparison (Priority Best-Fit vs. FCFS)
    # --------------------------------------------------------------------------
    svg1 = []
    svg1.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 480" width="850" height="480">')
    svg1.append('<rect width="100%" height="100%" fill="#ffffff" />')
    svg1.append('<text x="425" y="35" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="bold" fill="#0f172a">Multi-Drone Allocation: Critical & Overall Fulfillment by Fleet Scale</text>')
    svg1.append('<text x="425" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#64748b">Empirical Comparison: Priority Best-Fit vs. First-Come First-Served (FCFS) Baseline</text>')

    # Chart Area
    x0, y0, w, h = 90, 90, 700, 310
    svg1.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0+h}" stroke="#cbd5e1" stroke-width="1.5" />')
    svg1.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" stroke="#cbd5e1" stroke-width="1.5" />')

    # Gridlines and Y-axis labels (0% to 100%)
    for y_val in range(0, 101, 20):
        y_pos = y0 + h - int((y_val / 100.0) * h)
        svg1.append(f'<line x1="{x0}" y1="{y_pos}" x2="{x0+w}" y2="{y_pos}" stroke="#f1f5f9" stroke-width="1" />')
        svg1.append(f'<text x="{x0-10}" y="{y_pos+4}" text-anchor="end" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{y_val}%</text>')

    scales = ["SCALE_TINY", "SCALE_SMALL", "SCALE_MEDIUM", "SCALE_LARGE", "SCALE_STRESS", "SCALE_INVERSION"]
    scale_labels = ["Tiny (5 req)", "Small (12 req)", "Med (25 req)", "Large (50 req)", "Stress (80 req)", "Inversion (10 req)"]

    bar_group_w = w / len(scales)
    bar_w = 22

    for i, s_id in enumerate(scales):
        center_x = x0 + (i * bar_group_w) + (bar_group_w / 2.0)

        pbf = next((r for r in alloc_results if r["scale_id"] == s_id and r["algorithm"] == "PRIORITY_BEST_FIT"), None)
        fcfs = next((r for r in alloc_results if r["scale_id"] == s_id and r["algorithm"] == "FCFS_GREEDY_BASELINE"), None)

        if pbf and fcfs:
            # PBF Critical (Green)
            crit_h1 = (pbf["critical_fulfillment_pct"] / 100.0) * h
            svg1.append(f'<rect x="{center_x - bar_w*1.5}" y="{y0 + h - crit_h1}" width="{bar_w}" height="{crit_h1}" fill="#10b981" rx="2" />')

            # FCFS Critical (Red/Orange)
            crit_h2 = (fcfs["critical_fulfillment_pct"] / 100.0) * h
            svg1.append(f'<rect x="{center_x - bar_w*0.5}" y="{y0 + h - crit_h2}" width="{bar_w}" height="{crit_h2}" fill="#ef4444" rx="2" />')

            # PBF Overall (Dark Blue)
            over_h1 = (pbf["overall_fulfillment_pct"] / 100.0) * h
            svg1.append(f'<rect x="{center_x + bar_w*0.5}" y="{y0 + h - over_h1}" width="{bar_w}" height="{over_h1}" fill="#3b82f6" rx="2" opacity="0.85" />')

        # X label
        svg1.append(f'<text x="{center_x}" y="{y0 + h + 20}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#334155">{scale_labels[i]}</text>')

    # Legend
    svg1.append('<rect x="230" y="440" width="14" height="14" fill="#10b981" rx="2" />')
    svg1.append('<text x="250" y="452" font-family="Arial, sans-serif" font-size="12" fill="#1e293b">Priority Best-Fit: Critical Fulfillment %</text>')

    svg1.append('<rect x="520" y="440" width="14" height="14" fill="#ef4444" rx="2" />')
    svg1.append('<text x="540" y="452" font-family="Arial, sans-serif" font-size="12" fill="#1e293b">FCFS Baseline: Critical Fulfillment %</text>')

    svg1.append('</svg>')

    chart1_path = output_dir / "allocation_fulfillment_by_priority.svg"
    with open(chart1_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg1))
    print(f"[+] Generated Chart: {chart1_path}")

    # --------------------------------------------------------------------------
    # Chart 2: Algorithm Execution Latency vs Batch Size (Scaling Analysis)
    # --------------------------------------------------------------------------
    svg2 = []
    svg2.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 480" width="850" height="480">')
    svg2.append('<rect width="100%" height="100%" fill="#ffffff" />')
    svg2.append('<text x="425" y="35" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="bold" fill="#0f172a">Algorithm Execution Time Scaling: PBF vs. FCFS</text>')
    svg2.append('<text x="425" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="#64748b">Measured runtime latency in milliseconds across increasing batch sizes (N=5 to N=80)</text>')

    x0, y0, w, h = 90, 90, 700, 310
    svg2.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0+h}" stroke="#cbd5e1" stroke-width="1.5" />')
    svg2.append(f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" stroke="#cbd5e1" stroke-width="1.5" />')

    max_ms = max(r["execution_time_ms"] for r in alloc_results) * 1.25 or 50.0

    # Y-axis
    for step in range(5):
        val = (max_ms / 4.0) * step
        y_pos = y0 + h - int((val / max_ms) * h)
        svg2.append(f'<line x1="{x0}" y1="{y_pos}" x2="{x0+w}" y2="{y_pos}" stroke="#f1f5f9" stroke-width="1" />')
        svg2.append(f'<text x="{x0-10}" y="{y_pos+4}" text-anchor="end" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{val:.1f} ms</text>')

    # Plot points and lines
    pbf_points = []
    fcfs_points = []

    for i, s_id in enumerate(scales[:5]):  # First 5 scales sorted by size
        x_pt = x0 + int((i / 4.0) * (w - 60)) + 30
        pbf_r = next((r for r in alloc_results if r["scale_id"] == s_id and r["algorithm"] == "PRIORITY_BEST_FIT"), None)
        fcfs_r = next((r for r in alloc_results if r["scale_id"] == s_id and r["algorithm"] == "FCFS_GREEDY_BASELINE"), None)

        if pbf_r:
            y_pbf = y0 + h - int((pbf_r["execution_time_ms"] / max_ms) * h)
            pbf_points.append((x_pt, y_pbf, pbf_r["execution_time_ms"]))
        if fcfs_r:
            y_fcfs = y0 + h - int((fcfs_r["execution_time_ms"] / max_ms) * h)
            fcfs_points.append((x_pt, y_fcfs, fcfs_r["execution_time_ms"]))

        req_n = pbf_r["total_requests"] if pbf_r else i
        svg2.append(f'<text x="{x_pt}" y="{y0 + h + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#334155">N={req_n}</text>')

    # Connect lines
    if len(pbf_points) > 1:
        pts_str = " ".join(f"{pt[0]},{pt[1]}" for pt in pbf_points)
        svg2.append(f'<polyline points="{pts_str}" fill="none" stroke="#2563eb" stroke-width="3" />')
    if len(fcfs_points) > 1:
        pts_str = " ".join(f"{pt[0]},{pt[1]}" for pt in fcfs_points)
        svg2.append(f'<polyline points="{pts_str}" fill="none" stroke="#f59e0b" stroke-width="3" stroke-dasharray="6,4" />')

    # Draw point markers
    for pt in pbf_points:
        svg2.append(f'<circle cx="{pt[0]}" cy="{pt[1]}" r="5" fill="#2563eb" />')
        svg2.append(f'<text x="{pt[0]}" y="{pt[1]-10}" text-anchor="middle" font-family="Arial, sans-serif" font-size="10" font-weight="bold" fill="#1e3a8a">{pt[2]:.1f}ms</text>')

    for pt in fcfs_points:
        svg2.append(f'<circle cx="{pt[0]}" cy="{pt[1]}" r="5" fill="#f59e0b" />')
        svg2.append(f'<text x="{pt[0]}" y="{pt[1]+18}" text-anchor="middle" font-family="Arial, sans-serif" font-size="10" font-weight="bold" fill="#b45309">{pt[2]:.1f}ms</text>')

    # Legend
    svg2.append('<line x1="280" y1="446" x2="310" y2="446" stroke="#2563eb" stroke-width="3" />')
    svg2.append('<circle cx="295" cy="446" r="4" fill="#2563eb" />')
    svg2.append('<text x="320" y="450" font-family="Arial, sans-serif" font-size="12" fill="#1e293b">Priority Best-Fit (ms)</text>')

    svg2.append('<line x1="510" y1="446" x2="540" y2="446" stroke="#f59e0b" stroke-width="3" stroke-dasharray="6,4" />')
    svg2.append('<circle cx="525" cy="446" r="4" fill="#f59e0b" />')
    svg2.append('<text x="550" y="450" font-family="Arial, sans-serif" font-size="12" fill="#1e293b">FCFS Greedy Baseline (ms)</text>')

    svg2.append('</svg>')

    chart2_path = output_dir / "algorithm_execution_scaling.svg"
    with open(chart2_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg2))
    print(f"[+] Generated Chart: {chart2_path}")


# ==============================================================================
# 5. MAIN BENCHMARK RUNNER
# ==============================================================================

def main():
    print("=" * 80)
    print("  SMART EMERGENCY DRONE DELIVERY SYSTEM: ALGORITHM BENCHMARK SUITE")
    print("  Deterministic Experimental Verification & Trade-off Analysis")
    print("=" * 80)

    # Instantiate test application context
    app = create_app("testing")

    data_dir = BASE_DIR / "data" / "experiments"
    reports_dir = BASE_DIR / "reports" / "figures"
    docs_dir = BASE_DIR / "docs"
    docs_figures_dir = docs_dir / "figures"

    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    docs_figures_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # Step 1: Route Optimizer Benchmarking
    # --------------------------------------------------------------------------
    print("\n[*] [STEP 1/3] Benchmarking Route Optimizer across 12 deterministic scenarios...")
    scenarios = generate_route_scenarios()
    route_results = run_route_optimizer_benchmarks(scenarios)

    route_csv = data_dir / "route_optimizer_benchmarks.csv"
    with open(route_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(route_results[0].keys()))
        writer.writeheader()
        writer.writerows(route_results)
    print(f"[+] Saved Route Optimizer Benchmarks: {route_csv} ({len(route_results)} rows)")

    # --------------------------------------------------------------------------
    # Step 2: Multi-Drone Batch Allocation Benchmarking
    # --------------------------------------------------------------------------
    print("\n[*] [STEP 2/3] Benchmarking Multi-Drone Batch Allocation across 6 scales...")
    alloc_results = run_allocation_benchmarks(app)

    alloc_csv = data_dir / "multi_drone_allocation_benchmarks.csv"
    with open(alloc_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(alloc_results[0].keys()))
        writer.writeheader()
        writer.writerows(alloc_results)
    print(f"[+] Saved Allocation Benchmarks: {alloc_csv} ({len(alloc_results)} rows)")

    # --------------------------------------------------------------------------
    # Step 3: Dynamic In-Flight Rerouting Benchmarking
    # --------------------------------------------------------------------------
    print("\n[*] [STEP 3/3] Benchmarking In-Flight Dynamic Rerouting Policies...")
    reroute_results = run_dynamic_rerouting_benchmarks(app)

    reroute_csv = data_dir / "dynamic_rerouting_benchmarks.csv"
    with open(reroute_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(reroute_results[0].keys()))
        writer.writeheader()
        writer.writerows(reroute_results)
    print(f"[+] Saved Dynamic Rerouting Benchmarks: {reroute_csv} ({len(reroute_results)} rows)")

    # --------------------------------------------------------------------------
    # Step 4: Consolidated Summary CSV for Documentation
    # --------------------------------------------------------------------------
    doc_summary_csv = docs_dir / "algorithm_benchmark_results.csv"
    with open(doc_summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(alloc_results[0].keys()))
        writer.writeheader()
        writer.writerows(alloc_results)
    print(f"[+] Saved Consolidated Benchmark CSV: {doc_summary_csv}")

    # --------------------------------------------------------------------------
    # Step 5: Visual SVG Chart Generation
    # --------------------------------------------------------------------------
    print("\n[*] Generating Vector SVG Charts...")
    generate_svg_charts(route_results, alloc_results, reports_dir)
    generate_svg_charts(route_results, alloc_results, docs_figures_dir)

    # --------------------------------------------------------------------------
    # Print Executive Summary Tables
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("  EXECUTIVE SUMMARY TABLE: MULTI-DRONE ALLOCATION EMPIRICAL RESULTS")
    print("=" * 80)
    print(f"{'Scale Scenario':<22} | {'Algorithm':<20} | {'Matched':<7} | {'Crit %':<7} | {'Overall %':<9} | {'Latency':<8}")
    print("-" * 80)
    for r in alloc_results:
        print(f"{r['scale_name']:<22} | {r['algorithm']:<20} | {r['matched_count']:>2}/{r['total_requests']:<4} | {r['critical_fulfillment_pct']:>5.1f}% | {r['overall_fulfillment_pct']:>7.1f}% | {r['execution_time_ms']:>6.2f}ms")

    print("\n" + "=" * 80)
    print("  EXECUTIVE SUMMARY TABLE: DYNAMIC IN-FLIGHT REROUTING POLICIES")
    print("=" * 80)
    for r in reroute_results:
        print(f"[{r['scenario_id']}] {r['scenario_name']}")
        print(f"    Policy: {r['policy_name']} (Threshold: {r['threshold_pct']}%) -> Switched: {r['switched']} (Latency: {r['execution_time_ms']:.2f}ms)")
        print(f"    Decision: {r['explanation']}")

    print("\n[+] BENCHMARK EXECUTION COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
