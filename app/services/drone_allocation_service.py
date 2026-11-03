"""Drone allocation and route persistence service.

Governs multi-criteria drone selection, deterministic route optimization,
ACID database persistence, and race-condition prevention during fleet dispatch.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, List, Any
from app.extensions import db
from app.models.delivery_request import DeliveryRequest, RequestStatus, RequestPriority
from app.models.drone import Drone, DroneStatus
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.services.route_optimizer import (
    RouteOptimizer,
    OptimizationResult,
    RouteCandidate,
)
from app.services.weather_service import WeatherService, WeatherData
from app.services.assignment_service import (
    AssignmentService,
    AssignmentServiceError,
    ConflictingAssignmentError,
    InfeasibleAssignmentError,
)


@dataclass
class AllocationMatch:
    """Represents a validated pairing between a delivery request, drone, and route."""
    request_id: int
    request_priority: str
    request_payload_kg: float
    drone_id: int
    drone_code: str
    drone_model: str
    drone_max_payload_kg: float
    route_id: Optional[int]
    corridor_name: str
    distance_km: float
    duration_min: float
    energy_wh: float
    match_score: float
    explanation: str


@dataclass
class UnmatchedRequest:
    """Details an unassigned delivery request and the specific constraint violation."""
    request_id: int
    priority: str
    payload_weight_kg: float
    reason_code: str  # INSUFFICIENT_DRONE_CAPACITY, INSUFFICIENT_BATTERY, NO_AVAILABLE_DRONES, ALL_ROUTES_INFEASIBLE
    explanation: str


@dataclass
class MultiDroneAllocationPlan:
    """Comprehensive multi-drone allocation solution comparing objectives and constraints."""
    algorithm_name: str
    timestamp_utc: str
    total_evaluated_requests: int
    total_available_drones: int
    matches: List[AllocationMatch] = field(default_factory=list)
    unmatched_requests: List[UnmatchedRequest] = field(default_factory=list)
    idle_drones: List[Dict[str, Any]] = field(default_factory=list)
    total_fleet_energy_wh: float = 0.0
    high_priority_fulfillment_rate_pct: float = 0.0
    overall_fulfillment_rate_pct: float = 0.0
    objective_description: str = ""

    def to_dict(self) -> dict:
        """Serialize plan for API responses and dashboard rendering."""
        return {
            "algorithm_name": self.algorithm_name,
            "timestamp_utc": self.timestamp_utc,
            "total_evaluated_requests": self.total_evaluated_requests,
            "total_available_drones": self.total_available_drones,
            "matched_count": len(self.matches),
            "unmatched_count": len(self.unmatched_requests),
            "idle_drones_count": len(self.idle_drones),
            "total_fleet_energy_wh": round(self.total_fleet_energy_wh, 2),
            "high_priority_fulfillment_rate_pct": round(self.high_priority_fulfillment_rate_pct, 1),
            "overall_fulfillment_rate_pct": round(self.overall_fulfillment_rate_pct, 1),
            "objective_description": self.objective_description,
            "matches": [
                {
                    "request_id": m.request_id,
                    "request_priority": m.request_priority,
                    "request_payload_kg": m.request_payload_kg,
                    "drone_id": m.drone_id,
                    "drone_code": m.drone_code,
                    "drone_model": m.drone_model,
                    "drone_max_payload_kg": m.drone_max_payload_kg,
                    "route_id": m.route_id,
                    "corridor_name": m.corridor_name,
                    "distance_km": round(m.distance_km, 2),
                    "duration_min": round(m.duration_min, 1),
                    "energy_wh": round(m.energy_wh, 1),
                    "match_score": round(m.match_score, 4),
                    "explanation": m.explanation,
                }
                for m in self.matches
            ],
            "unmatched_requests": [
                {
                    "request_id": u.request_id,
                    "priority": u.priority,
                    "payload_weight_kg": u.payload_weight_kg,
                    "reason_code": u.reason_code,
                    "explanation": u.explanation,
                }
                for u in self.unmatched_requests
            ],
            "idle_drones": self.idle_drones,
        }


class AllocationServiceError(Exception):
    """Base exception for drone allocation and optimization workflows."""
    pass


class DroneAllocationService:
    """Service orchestrating route generation, feasibility validation, and assignment."""

    @classmethod
    def generate_and_persist_routes(
        cls,
        delivery_request_id: int,
        drone_id: Optional[int] = None,
        algorithm_name: str = "WEIGHTED_MULTI_OBJECTIVE",
        weights: Optional[Dict[str, float]] = None,
        include_return_trip: bool = False,
        require_weather: bool = False,
    ) -> Tuple[OptimizationResult, Optional[Route]]:
        """Generate candidate corridors, evaluate feasibility, and persist results.

        Preserves audit history: does not overwrite previous routes; records all
        evaluated candidates and reasons for infeasibility in the database.
        """
        request = db.session.get(DeliveryRequest, delivery_request_id)
        if not request:
            raise AllocationServiceError(f"Delivery request #{delivery_request_id} not found.")

        # Determine drone specifications for feasibility calculation
        if drone_id is not None:
            drone = db.session.get(Drone, drone_id)
            if not drone:
                raise AllocationServiceError(f"Drone #{drone_id} not found.")
            drone_speed = float(drone.cruise_speed_kmh)
            drone_payload = float(drone.maximum_payload_kg)
            drone_batt_cap = float(drone.battery_capacity_wh)
            drone_curr_batt = float(drone.current_battery_wh)
        else:
            # Baseline reference drone specifications from available fleet or standard defaults
            avail_drone = (
                Drone.query.filter_by(status=DroneStatus.AVAILABLE.value, is_decommissioned=False)
                .order_by(Drone.maximum_payload_kg.desc())
                .first()
            )
            drone_speed = float(avail_drone.cruise_speed_kmh) if avail_drone else 60.0
            drone_payload = float(avail_drone.maximum_payload_kg) if avail_drone else 5.0
            drone_batt_cap = float(avail_drone.battery_capacity_wh) if avail_drone else 850.0
            drone_curr_batt = float(avail_drone.current_battery_wh) if avail_drone else 850.0

        # Retrieve weather observation
        weather = WeatherService.get_weather_for_request(
            delivery_request_id=request.id,
            require_weather=require_weather,
        )

        # Run optimization
        opt_result = RouteOptimizer.optimize(
            pickup_lat=float(request.pickup_latitude),
            pickup_lng=float(request.pickup_longitude),
            dest_lat=float(request.destination_latitude),
            dest_lng=float(request.destination_longitude),
            payload_weight_kg=float(request.payload_weight_kg),
            drone_cruise_speed_kmh=drone_speed,
            drone_max_payload_kg=drone_payload,
            drone_battery_capacity_wh=drone_batt_cap,
            drone_current_battery_wh=drone_curr_batt,
            weather=weather,
            weights=weights,
            include_return_trip=include_return_trip,
            algorithm_name=algorithm_name,
        )

        primary_persisted_route = None

        # Persist all evaluated candidates with their feasibility states
        for candidate in opt_result.candidates:
            is_selected = (
                opt_result.selected_route is not None
                and candidate.candidate_id == opt_result.selected_route.candidate_id
            )

            route_entity = Route(
                delivery_request_id=request.id,
                algorithm_name=f"{algorithm_name}:{candidate.candidate_id}",
                estimated_distance_km=candidate.distance_km,
                estimated_duration_minutes=candidate.duration_minutes,
                estimated_energy_wh=candidate.energy_wh,
                route_score=candidate.objective_score,
                feasibility_status=(
                    FeasibilityStatus.FEASIBLE.value
                    if candidate.is_feasible
                    else FeasibilityStatus.INFEASIBLE.value
                ),
                rejection_reason="; ".join(candidate.rejection_reasons) if not candidate.is_feasible else None,
            )
            db.session.add(route_entity)
            db.session.flush()

            # Persist Waypoints sequence
            for idx, wp in enumerate(candidate.waypoints):
                waypoint_entity = RouteWaypoint(
                    route_id=route_entity.id,
                    sequence_number=idx,
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                    altitude_m=wp.altitude_m,
                )
                db.session.add(waypoint_entity)

            if is_selected:
                primary_persisted_route = route_entity

        # Update delivery request status if feasible route was computed
        if opt_result.is_feasible and request.status == RequestStatus.PENDING.value:
            request.status = RequestStatus.ROUTE_CALCULATED.value

        db.session.commit()
        return opt_result, primary_persisted_route

    @classmethod
    def allocate_and_dispatch(
        cls,
        delivery_request_id: int,
        drone_id: int,
        route_id: Optional[int] = None,
        algorithm_name: str = "WEIGHTED_MULTI_OBJECTIVE",
    ) -> DroneAssignment:
        """Allocate a drone to an emergency delivery request and dispatch.

        Guarantees:
        - Prevents race conditions and double-booking using transaction locks.
        - Verifies drone availability, payload limits, and battery reserves.
        - If route_id is omitted, computes and selects the optimal feasible route automatically.
        """
        request = db.session.get(DeliveryRequest, delivery_request_id)
        if not request:
            raise AllocationServiceError(f"Delivery request #{delivery_request_id} does not exist.")

        drone = db.session.get(Drone, drone_id)
        if not drone:
            raise AllocationServiceError(f"Drone #{drone_id} does not exist.")

        # If no route is provided, calculate optimal route for this specific drone
        if route_id is None:
            opt_result, route_entity = cls.generate_and_persist_routes(
                delivery_request_id=request.id,
                drone_id=drone.id,
                algorithm_name=algorithm_name,
            )
            if not opt_result.is_feasible or not route_entity:
                raise InfeasibleAssignmentError(
                    f"No feasible route could be generated for Drone {drone.drone_code} and Request #{request.id}. "
                    f"Reasons: {opt_result.summary_message}"
                )
            selected_route_id = route_entity.id
        else:
            selected_route_id = route_id

        # Dispatch via AssignmentService (enforces atomic transaction & active locks)
        return AssignmentService.create_assignment(
            delivery_request_id=request.id,
            drone_id=drone.id,
            route_id=selected_route_id,
        )

    @classmethod
    def evaluate_multi_drone_allocation(
        cls,
        request_ids: Optional[List[int]] = None,
        drone_ids: Optional[List[int]] = None,
        algorithm_name: str = "PRIORITY_BEST_FIT",
        require_weather: bool = False,
    ) -> MultiDroneAllocationPlan:
        """Evaluate and match multiple pending delivery requests to eligible available drones.

        Algorithms:
        1. PRIORITY_BEST_FIT: Triages requests by priority level (CRITICAL > HIGH > MEDIUM > LOW),
           then selects the optimal drone minimizing payload capacity waste and battery drain.
        2. FCFS_GREEDY_BASELINE: Evaluates requests in FIFO arrival order (created_at asc)
           and assigns the first feasible drone found, ignoring priority hierarchy.
        """
        # 1. Fetch Requests
        query = DeliveryRequest.query.filter(
            DeliveryRequest.status.in_([RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value])
        )
        if request_ids:
            query = query.filter(DeliveryRequest.id.in_(request_ids))

        requests_list = query.all()

        # 2. Fetch Available Drones
        drone_query = Drone.query.filter_by(
            status=DroneStatus.AVAILABLE.value,
            is_decommissioned=False,
        )
        if drone_ids:
            drone_query = drone_query.filter(Drone.id.in_(drone_ids))

        available_drones = drone_query.all()

        plan = MultiDroneAllocationPlan(
            algorithm_name=algorithm_name,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            total_evaluated_requests=len(requests_list),
            total_available_drones=len(available_drones),
        )

        if not requests_list:
            plan.objective_description = "No pending or unassigned delivery requests found."
            return plan

        priority_weights = {
            RequestPriority.CRITICAL.value: 4,
            RequestPriority.HIGH.value: 3,
            RequestPriority.MEDIUM.value: 2,
            RequestPriority.LOW.value: 1,
        }

        # 3. Sort Requests according to selected strategy
        if algorithm_name == "PRIORITY_BEST_FIT":
            sorted_requests = sorted(
                requests_list,
                key=lambda r: (
                    -priority_weights.get(r.priority, 1),
                    r.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    r.id,
                ),
            )
            plan.objective_description = (
                "Priority-Driven Best-Fit Multi-Drone Matching: Triages by priority level "
                "(CRITICAL > HIGH > MEDIUM > LOW), then minimizes payload capacity headroom waste "
                "and battery depletion ratio to maximize urgent life-support fulfillment."
            )
        else:  # FCFS_GREEDY_BASELINE
            sorted_requests = sorted(
                requests_list,
                key=lambda r: (
                    r.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    r.id,
                ),
            )
            plan.objective_description = (
                "First-Come, First-Served (FCFS) Greedy Baseline: Allocates available drones "
                "strictly in request arrival order, greedily selecting the first feasible drone."
            )

        # Track drone availability within batch
        remaining_drones = list(available_drones)

        for req in sorted_requests:
            if not remaining_drones:
                plan.unmatched_requests.append(
                    UnmatchedRequest(
                        request_id=req.id,
                        priority=req.priority,
                        payload_weight_kg=float(req.payload_weight_kg),
                        reason_code="NO_AVAILABLE_DRONES",
                        explanation="All fleet airframes were claimed by earlier or higher-priority requests.",
                    )
                )
                continue

            # Check if ANY drone in remaining fleet has capacity
            capacity_eligible_drones = [
                d for d in remaining_drones
                if float(d.maximum_payload_kg) >= float(req.payload_weight_kg)
            ]

            if not capacity_eligible_drones:
                max_avail_cap = max((float(d.maximum_payload_kg) for d in remaining_drones), default=0.0)
                plan.unmatched_requests.append(
                    UnmatchedRequest(
                        request_id=req.id,
                        priority=req.priority,
                        payload_weight_kg=float(req.payload_weight_kg),
                        reason_code="INSUFFICIENT_DRONE_CAPACITY",
                        explanation=(
                            f"Cargo mass {float(req.payload_weight_kg):.2f} kg exceeds maximum capacity "
                            f"of all remaining available drones (highest available: {max_avail_cap:.2f} kg)."
                        ),
                    )
                )
                continue

            # Evaluate route feasibility and score matching for eligible drones
            candidate_matches = []
            feasibility_rejections = []

            weather = WeatherService.get_weather_for_request(
                delivery_request_id=req.id,
                require_weather=require_weather,
            )

            for drone in capacity_eligible_drones:
                opt_res = RouteOptimizer.optimize(
                    pickup_lat=float(req.pickup_latitude),
                    pickup_lng=float(req.pickup_longitude),
                    dest_lat=float(req.destination_latitude),
                    dest_lng=float(req.destination_longitude),
                    payload_weight_kg=float(req.payload_weight_kg),
                    drone_cruise_speed_kmh=float(drone.cruise_speed_kmh),
                    drone_max_payload_kg=float(drone.maximum_payload_kg),
                    drone_battery_capacity_wh=float(drone.battery_capacity_wh),
                    drone_current_battery_wh=float(drone.current_battery_wh),
                    weather=weather,
                    algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
                )

                if opt_res.is_feasible and opt_res.selected_route:
                    sel = opt_res.selected_route
                    # Match score calculation
                    cap_waste = float(drone.maximum_payload_kg) - float(req.payload_weight_kg)
                    norm_cap_waste = cap_waste / max(1.0, float(drone.maximum_payload_kg))

                    usable_batt = float(drone.current_battery_wh) * 0.85
                    batt_ratio = sel.energy_wh / max(1.0, usable_batt)

                    if algorithm_name == "PRIORITY_BEST_FIT":
                        match_score = (
                            0.50 * sel.objective_score
                            + 0.30 * norm_cap_waste
                            + 0.20 * batt_ratio
                        )
                        explanation = (
                            f"Matched to {drone.drone_code} ({drone.model_name}): "
                            f"Corridor '{sel.corridor_name}', {sel.distance_km:.2f} km, "
                            f"Headroom {cap_waste:.2f} kg, Reserve utilization {batt_ratio*100:.1f}%."
                        )
                    else:  # FCFS_GREEDY
                        match_score = sel.distance_km
                        explanation = f"Greedy first-feasible match to {drone.drone_code} on {sel.corridor_name}."

                    candidate_matches.append({
                        "drone": drone,
                        "selected_route": sel,
                        "opt_result": opt_res,
                        "match_score": match_score,
                        "explanation": explanation,
                    })

                    # In greedy baseline, take first and break
                    if algorithm_name == "FCFS_GREEDY_BASELINE":
                        break
                else:
                    reasons = [
                        r.get("reasons", []) for r in opt_res.rejected_candidates
                    ]
                    flat_reasons = "; ".join(sum(reasons, [])) or "Battery reserve or weather constraint violated"
                    feasibility_rejections.append((drone.drone_code, flat_reasons))

            if candidate_matches:
                candidate_matches.sort(key=lambda m: (m["match_score"], m["drone"].drone_code))
                best = candidate_matches[0]
                best_drone = best["drone"]
                best_sel = best["selected_route"]

                plan.matches.append(
                    AllocationMatch(
                        request_id=req.id,
                        request_priority=req.priority,
                        request_payload_kg=float(req.payload_weight_kg),
                        drone_id=best_drone.id,
                        drone_code=best_drone.drone_code,
                        drone_model=best_drone.model_name,
                        drone_max_payload_kg=float(best_drone.maximum_payload_kg),
                        route_id=None,
                        corridor_name=best_sel.corridor_name,
                        distance_km=best_sel.distance_km,
                        duration_min=best_sel.duration_minutes,
                        energy_wh=best_sel.energy_wh,
                        match_score=best["match_score"],
                        explanation=best["explanation"],
                    )
                )
                plan.total_fleet_energy_wh += best_sel.energy_wh
                remaining_drones.remove(best_drone)
            else:
                drone_reasons = " | ".join(f"{code}: {r}" for code, r in feasibility_rejections[:2])
                plan.unmatched_requests.append(
                    UnmatchedRequest(
                        request_id=req.id,
                        priority=req.priority,
                        payload_weight_kg=float(req.payload_weight_kg),
                        reason_code="INSUFFICIENT_BATTERY_OR_WEATHER",
                        explanation=f"All capacity-eligible drones failed route feasibility checks ({drone_reasons}).",
                    )
                )

        # Idle drones list
        plan.idle_drones = [
            {
                "id": d.id,
                "drone_code": d.drone_code,
                "model_name": d.model_name,
                "maximum_payload_kg": float(d.maximum_payload_kg),
                "current_battery_wh": float(d.current_battery_wh),
                "battery_percentage": d.battery_percentage,
            }
            for d in remaining_drones
        ]

        # Calculate metrics
        high_pri_requests = [
            r for r in requests_list
            if r.priority in (RequestPriority.CRITICAL.value, RequestPriority.HIGH.value)
        ]
        matched_high_pri = [
            m for m in plan.matches
            if m.request_priority in (RequestPriority.CRITICAL.value, RequestPriority.HIGH.value)
        ]

        plan.high_priority_fulfillment_rate_pct = (
            (len(matched_high_pri) / len(high_pri_requests)) * 100.0
            if high_pri_requests else 100.0
        )
        plan.overall_fulfillment_rate_pct = (
            (len(plan.matches) / len(requests_list)) * 100.0
            if requests_list else 100.0
        )

        return plan

    @classmethod
    def execute_batch_dispatch(
        cls,
        allocation_plan: MultiDroneAllocationPlan,
    ) -> List[DroneAssignment]:
        """Atomically dispatch all validated pairings in an allocation plan.

        Enforces all ACID guarantees and locks via AssignmentService.
        """
        dispatched_assignments = []
        if not allocation_plan or not allocation_plan.matches:
            return dispatched_assignments

        try:
            for match in allocation_plan.matches:
                assignment = cls.allocate_and_dispatch(
                    delivery_request_id=match.request_id,
                    drone_id=match.drone_id,
                    algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
                )
                dispatched_assignments.append(assignment)

            db.session.commit()
            return dispatched_assignments
        except Exception as e:
            db.session.rollback()
            raise AllocationServiceError(f"Batch dispatch transaction failed: {str(e)}") from e
