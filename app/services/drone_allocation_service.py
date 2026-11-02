"""Drone allocation and route persistence service.

Governs multi-criteria drone selection, deterministic route optimization,
ACID database persistence, and race-condition prevention during fleet dispatch.
"""

from typing import Optional, Dict, Tuple
from app.extensions import db
from app.models.delivery_request import DeliveryRequest, RequestStatus
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
