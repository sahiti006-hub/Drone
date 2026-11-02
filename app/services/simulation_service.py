"""Discrete-time simulation service for emergency drone delivery missions.

IMPORTANT NOTICE:
This module is strictly a software simulation and numerical kinematics proxy.
It does NOT control real drone hardware, interface with flight controllers,
or produce certified aviation flight plans. It is designed solely for academic
evaluation, mission rehearsal, and dispatch route validation.
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.extensions import db
from app.models.analysis_log import AnalysisLog, EvaluationStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.route_waypoint import RouteWaypoint
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.services.route_optimizer import haversine_distance


class SimulationServiceError(Exception):
    """Base exception for simulation service errors."""
    pass


class InvalidAssignmentStateError(SimulationServiceError):
    """Raised when an assignment cannot be simulated in its current state."""
    pass


class DuplicateSimulationError(SimulationServiceError):
    """Raised when attempting to create a duplicate active simulation for an assignment."""
    pass


class InvalidSimulationStateTransitionError(SimulationServiceError):
    """Raised when an illegal lifecycle state transition is attempted."""
    pass


# Strict backend state transition rules
VALID_SIMULATION_TRANSITIONS: Dict[str, set] = {
    SimulationStatus.CREATED.value: {
        SimulationStatus.RUNNING.value,
        SimulationStatus.CANCELLED.value,
    },
    SimulationStatus.PENDING.value: {
        SimulationStatus.RUNNING.value,
        SimulationStatus.CANCELLED.value,
    },
    SimulationStatus.RUNNING.value: {
        SimulationStatus.PAUSED.value,
        SimulationStatus.COMPLETED.value,
        SimulationStatus.CANCELLED.value,
        SimulationStatus.FAILED.value,
    },
    SimulationStatus.PAUSED.value: {
        SimulationStatus.RUNNING.value,
        SimulationStatus.CANCELLED.value,
        SimulationStatus.FAILED.value,
    },
    SimulationStatus.COMPLETED.value: set(),
    SimulationStatus.CANCELLED.value: set(),
    SimulationStatus.FAILED.value: set(),
}


def compute_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the initial compass bearing from (lat1, lon1) to (lat2, lon2) in degrees [0, 360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return round(bearing, 1)


def get_route_segment_metrics(waypoints: List[Dict[str, Any]]) -> Tuple[List[float], float]:
    """Calculate cumulative distance list and total distance for a sequence of waypoints.

    Args:
        waypoints: Ordered list of dicts with 'latitude' and 'longitude'.

    Returns:
        Tuple of (cumulative_distances_km, total_distance_km).
    """
    if not waypoints or len(waypoints) < 2:
        return [0.0], 0.0

    cumulative = [0.0]
    total = 0.0
    for i in range(len(waypoints) - 1):
        p1 = (waypoints[i]["latitude"], waypoints[i]["longitude"])
        p2 = (waypoints[i + 1]["latitude"], waypoints[i + 1]["longitude"])
        dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
        total += dist
        cumulative.append(total)

    return cumulative, total


def interpolate_position(
    waypoints: List[Dict[str, Any]],
    distance_km: float,
    cumulative_distances: Optional[List[float]] = None,
    total_distance_km: Optional[float] = None,
) -> Dict[str, Any]:
    """Interpolates position (lat, lon, alt) and heading along ordered waypoints at distance_km.

    Args:
        waypoints: List of dicts with 'latitude', 'longitude', 'altitude_m'.
        distance_km: Distance covered from the starting waypoint in kilometres.
        cumulative_distances: Precomputed cumulative segment distances (optional).
        total_distance_km: Precomputed total distance (optional).

    Returns:
        Dict containing latitude, longitude, altitude_m, heading_deg, segment_index.
    """
    if not waypoints:
        raise ValueError("Cannot interpolate across an empty waypoints list.")

    if len(waypoints) == 1:
        w = waypoints[0]
        return {
            "latitude": float(w["latitude"]),
            "longitude": float(w["longitude"]),
            "altitude_m": float(w.get("altitude_m", 50.0)),
            "heading_deg": 0.0,
            "segment_index": 0,
        }

    if cumulative_distances is None or total_distance_km is None:
        cumulative_distances, total_distance_km = get_route_segment_metrics(waypoints)

    target_d = max(0.0, min(float(distance_km), total_distance_km))

    # At or before start
    if target_d <= 1e-9:
        w0 = waypoints[0]
        w1 = waypoints[1]
        bearing = compute_bearing(
            float(w0["latitude"]), float(w0["longitude"]),
            float(w1["latitude"]), float(w1["longitude"]),
        )
        return {
            "latitude": float(w0["latitude"]),
            "longitude": float(w0["longitude"]),
            "altitude_m": float(w0.get("altitude_m", 50.0)),
            "heading_deg": bearing,
            "segment_index": 0,
        }

    # At or beyond destination
    if target_d >= total_distance_km - 1e-9:
        w_last = waypoints[-1]
        w_prev = waypoints[-2]
        bearing = compute_bearing(
            float(w_prev["latitude"]), float(w_prev["longitude"]),
            float(w_last["latitude"]), float(w_last["longitude"]),
        )
        return {
            "latitude": float(w_last["latitude"]),
            "longitude": float(w_last["longitude"]),
            "altitude_m": float(w_last.get("altitude_m", 20.0)),
            "heading_deg": bearing,
            "segment_index": len(waypoints) - 2,
        }

    # Binary or linear search for active segment
    for i in range(len(cumulative_distances) - 1):
        c_start = cumulative_distances[i]
        c_end = cumulative_distances[i + 1]
        if c_start <= target_d <= c_end:
            seg_len = c_end - c_start
            alpha = (target_d - c_start) / seg_len if seg_len > 1e-9 else 0.0

            w_start = waypoints[i]
            w_end = waypoints[i + 1]

            lat = float(w_start["latitude"]) + alpha * (float(w_end["latitude"]) - float(w_start["latitude"]))
            lon = float(w_start["longitude"]) + alpha * (float(w_end["longitude"]) - float(w_start["longitude"]))
            alt = float(w_start.get("altitude_m", 50.0)) + alpha * (float(w_end.get("altitude_m", 50.0)) - float(w_start.get("altitude_m", 50.0)))

            bearing = compute_bearing(
                float(w_start["latitude"]), float(w_start["longitude"]),
                float(w_end["latitude"]), float(w_end["longitude"]),
            )

            return {
                "latitude": round(lat, 7),
                "longitude": round(lon, 7),
                "altitude_m": round(alt, 2),
                "heading_deg": bearing,
                "segment_index": i,
            }

    # Fallback to last waypoint
    w_last = waypoints[-1]
    return {
        "latitude": float(w_last["latitude"]),
        "longitude": float(w_last["longitude"]),
        "altitude_m": float(w_last.get("altitude_m", 20.0)),
        "heading_deg": 0.0,
        "segment_index": len(waypoints) - 2,
    }


class SimulationService:
    """Manages discrete-time kinematic simulation runs, checkpoints, and telemetry sync."""

    @staticmethod
    def get_or_create_simulation(assignment_id: int) -> SimulationRun:
        """Retrieve existing active simulation or initialize a new one for the given assignment.

        Enforces prevention of duplicate active simulation runs.
        """
        assignment = db.session.get(DroneAssignment, assignment_id)
        if not assignment:
            raise SimulationServiceError(f"DroneAssignment #{assignment_id} not found.")

        # Check for existing active or paused simulation run
        active_sim = (
            SimulationRun.query
            .filter_by(assignment_id=assignment.id)
            .filter(SimulationRun.status.in_([
                SimulationStatus.CREATED.value,
                SimulationStatus.PENDING.value,
                SimulationStatus.RUNNING.value,
                SimulationStatus.PAUSED.value,
            ]))
            .first()
        )
        if active_sim:
            return active_sim

        # If assignment is already closed, disallow creating a new simulation
        if assignment.status in (AssignmentStatus.COMPLETED.value, AssignmentStatus.ABORTED.value, AssignmentStatus.FAILED.value):
            raise InvalidAssignmentStateError(
                f"Assignment #{assignment_id} is already in {assignment.status} status and cannot be simulated."
            )

        route = assignment.route
        if not route:
            raise SimulationServiceError(f"Assignment #{assignment_id} has no linked Route.")

        waypoints = (
            RouteWaypoint.query
            .filter_by(route_id=route.id)
            .order_by(RouteWaypoint.sequence_number.asc())
            .all()
        )
        if not waypoints or len(waypoints) < 2:
            raise SimulationServiceError(f"Route #{route.id} has insufficient waypoints for simulation.")

        wp_dicts = [wp.to_dict() for wp in waypoints]
        _, total_distance_km = get_route_segment_metrics(wp_dicts)

        drone = assignment.drone
        cruise_speed = float(drone.cruise_speed_kmh) if drone and drone.cruise_speed_kmh else 60.0
        total_sim_seconds = (total_distance_km / cruise_speed) * 3600.0 if cruise_speed > 0 else 600.0

        run_code = f"SIM-ASG{assignment.id}-{uuid.uuid4().hex[:8].upper()}"
        initial_wp = wp_dicts[0]

        parameters = {
            "assignment_id": assignment.id,
            "drone_id": assignment.drone_id,
            "drone_code": drone.drone_code if drone else "UNKNOWN",
            "route_id": route.id,
            "algorithm_name": route.algorithm_name,
            "total_distance_km": round(total_distance_km, 3),
            "cruise_speed_kmh": cruise_speed,
            "estimated_duration_min": float(route.estimated_duration_minutes),
            "estimated_energy_wh": float(route.estimated_energy_wh),
            "start_battery_wh": float(drone.current_battery_wh) if drone else 0.0,
        }

        sim = SimulationRun(
            run_code=run_code,
            parameters=parameters,
            status=SimulationStatus.CREATED.value,
            assignment_id=assignment.id,
            total_sim_seconds=total_sim_seconds,
            remaining_distance_km=total_distance_km,
            current_battery_wh=float(drone.current_battery_wh) if drone else 0.0,
        )
        sim.current_latitude = initial_wp["latitude"]
        sim.current_longitude = initial_wp["longitude"]
        sim.current_altitude_m = initial_wp.get("altitude_m", 50.0)
        sim.distance_covered_km = 0.0
        sim.current_progress_percent = 0.0

        db.session.add(sim)
        db.session.commit()
        return sim

    @staticmethod
    def start_simulation(simulation_id: int) -> SimulationRun:
        """Transition simulation from CREATED/PENDING to RUNNING."""
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        current = sim.status
        allowed = VALID_SIMULATION_TRANSITIONS.get(current, set())
        if SimulationStatus.RUNNING.value not in allowed:
            raise InvalidSimulationStateTransitionError(
                f"Cannot start simulation from status '{current}'. Valid transitions: {list(allowed)}"
            )

        sim.start()

        # Update assignment, delivery request, and drone status
        if sim.assignment:
            req = sim.assignment.delivery_request
            if req and req.status != RequestStatus.IN_TRANSIT.value:
                req.status = RequestStatus.IN_TRANSIT.value

            drone = sim.assignment.drone
            if drone and drone.status != DroneStatus.IN_TRANSIT.value:
                drone.status = DroneStatus.IN_TRANSIT.value

        db.session.commit()
        return sim

    @staticmethod
    def pause_simulation(simulation_id: int) -> SimulationRun:
        """Pause a currently RUNNING simulation."""
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        current = sim.status
        allowed = VALID_SIMULATION_TRANSITIONS.get(current, set())
        if SimulationStatus.PAUSED.value not in allowed:
            raise InvalidSimulationStateTransitionError(
                f"Cannot pause simulation from status '{current}'. Valid transitions: {list(allowed)}"
            )

        sim.pause()
        db.session.commit()
        return sim

    @staticmethod
    def resume_simulation(simulation_id: int) -> SimulationRun:
        """Resume a PAUSED simulation."""
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        if sim.status != SimulationStatus.PAUSED.value:
            raise InvalidSimulationStateTransitionError(
                f"Cannot resume simulation from status '{sim.status}'. Simulation must be PAUSED."
            )

        sim.resume()
        db.session.commit()
        return sim

    @staticmethod
    def cancel_simulation(simulation_id: int, reason: str = "Operator cancelled") -> SimulationRun:
        """Cancel an in-progress or paused simulation and release the drone."""
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        current = sim.status
        allowed = VALID_SIMULATION_TRANSITIONS.get(current, set())
        if SimulationStatus.CANCELLED.value not in allowed:
            raise InvalidSimulationStateTransitionError(
                f"Cannot cancel simulation from status '{current}'. Valid transitions: {list(allowed)}"
            )

        sim.cancel(reason=reason)

        if sim.assignment:
            sim.assignment.mark_aborted()
            req = sim.assignment.delivery_request
            if req:
                req.status = RequestStatus.CANCELLED.value

            drone = sim.assignment.drone
            if drone:
                # If battery is critically low (< 20%), flag as charging
                if drone.current_battery_wh and drone.battery_capacity_wh and (drone.current_battery_wh / drone.battery_capacity_wh) < 0.20:
                    drone.status = DroneStatus.CHARGING.value
                else:
                    drone.status = DroneStatus.AVAILABLE.value

        db.session.commit()
        return sim

    @staticmethod
    def step_simulation(
        simulation_id: int,
        delta_sim_seconds: float = 1.0,
        speed_multiplier: float = 1.0,
    ) -> Dict[str, Any]:
        """Advance the simulation forward by delta_sim_seconds at the specified speed multiplier.

        Calculates position interpolation, remaining battery, elapsed time, and
        automatically marks completion when 100% progress is reached.
        """
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        if sim.status != SimulationStatus.RUNNING.value:
            raise InvalidSimulationStateTransitionError(
                f"Cannot step simulation in '{sim.status}' status. Simulation must be RUNNING."
            )

        if delta_sim_seconds <= 0:
            raise ValueError("delta_sim_seconds must be positive.")

        if not (0.1 <= speed_multiplier <= 50.0):
            raise ValueError("speed_multiplier must be between 0.1 and 50.0.")

        assignment = sim.assignment
        if not assignment or not assignment.route:
            raise SimulationServiceError(f"Linked Route not found for Simulation #{simulation_id}.")

        route = assignment.route
        drone = assignment.drone
        waypoints = (
            RouteWaypoint.query
            .filter_by(route_id=route.id)
            .order_by(RouteWaypoint.sequence_number.asc())
            .all()
        )
        wp_dicts = [wp.to_dict() for wp in waypoints]
        cum_dists, total_dist_km = get_route_segment_metrics(wp_dicts)

        cruise_speed = float(drone.cruise_speed_kmh) if drone and drone.cruise_speed_kmh else 60.0
        effective_delta_sec = delta_sim_seconds * speed_multiplier
        delta_distance_km = (cruise_speed / 3600.0) * effective_delta_sec

        new_distance = min(total_dist_km, sim.distance_covered_km + delta_distance_km)
        new_elapsed = sim.elapsed_sim_seconds + effective_delta_sec
        new_remaining_dist = max(0.0, total_dist_km - new_distance)
        progress_pct = (new_distance / total_dist_km * 100.0) if total_dist_km > 0 else 100.0

        # Energy consumption model proxy
        est_energy = float(route.estimated_energy_wh)
        energy_used = (new_distance / total_dist_km * est_energy) if total_dist_km > 0 else est_energy
        start_battery = float(drone.current_battery_wh) if drone else 0.0
        current_battery = max(0.0, start_battery - energy_used)

        # Interpolate position
        pos = interpolate_position(
            waypoints=wp_dicts,
            distance_km=new_distance,
            cumulative_distances=cum_dists,
            total_distance_km=total_dist_km,
        )

        is_completed = (new_distance >= total_dist_km - 1e-6) or (progress_pct >= 99.99)

        if is_completed:
            # Mission completed
            summary_metrics = {
                "dispatches": 1,
                "total_distance_km": round(total_dist_km, 3),
                "total_sim_seconds": round(new_elapsed, 1),
                "energy_consumed_wh": round(energy_used, 2),
                "final_battery_wh": round(current_battery, 2),
                "delivery_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "DELIVERED",
            }
            sim.complete(summary_metrics)
            sim.distance_covered_km = round(total_dist_km, 3)
            sim.current_progress_percent = 100.0
            sim.remaining_distance_km = 0.0
            sim.current_latitude = pos["latitude"]
            sim.current_longitude = pos["longitude"]
            sim.current_altitude_m = pos["altitude_m"]
            sim.current_battery_wh = round(current_battery, 2)
            sim.elapsed_sim_seconds = round(new_elapsed, 2)

            assignment.mark_completed()
            if assignment.delivery_request:
                assignment.delivery_request.status = RequestStatus.DELIVERED.value

            if drone:
                drone.current_battery_wh = round(current_battery, 2)
                # If battery below 20%, transition to charging
                if (drone.current_battery_wh / float(drone.battery_capacity_wh)) < 0.20:
                    drone.status = DroneStatus.CHARGING.value
                else:
                    drone.status = DroneStatus.AVAILABLE.value

            # Persist AnalysisLog comparing predicted vs actual simulated outcomes
            pred_metrics = {
                "distance_km": float(route.estimated_distance_km),
                "duration_min": float(route.estimated_duration_minutes),
                "energy_wh": float(route.estimated_energy_wh),
            }
            actual_metrics = {
                "distance_km": round(total_dist_km, 3),
                "duration_min": round(new_elapsed / 60.0, 2),
                "energy_wh": round(energy_used, 2),
                "status": "DELIVERED",
            }
            analysis_log = AnalysisLog(
                simulation_run_id=sim.id,
                algorithm_name=route.algorithm_name,
                scenario_reference=f"REQ_{assignment.delivery_request_id}_ROUTE_{route.id}",
                predicted_metrics=pred_metrics,
                actual_simulated_metrics=actual_metrics,
                evaluation_status=EvaluationStatus.OPTIMAL.value,
                notes="Mission delivered successfully via simulated kinematic corridor.",
            )
            db.session.add(analysis_log)

        else:
            sim.update_checkpoint(
                progress_percent=progress_pct,
                latitude=pos["latitude"],
                longitude=pos["longitude"],
                altitude_m=pos["altitude_m"],
                elapsed_seconds=new_elapsed,
                distance_covered_km=new_distance,
                remaining_distance_km=new_remaining_dist,
                current_battery_wh=current_battery,
                speed_multiplier=speed_multiplier,
                extra_data={
                    "heading_deg": pos["heading_deg"],
                    "segment_index": pos["segment_index"],
                },
            )

        db.session.commit()

        return {
            "simulation_id": sim.id,
            "status": sim.status,
            "progress_percent": sim.current_progress_percent,
            "latitude": float(sim.current_latitude) if sim.current_latitude is not None else pos["latitude"],
            "longitude": float(sim.current_longitude) if sim.current_longitude is not None else pos["longitude"],
            "altitude_m": float(sim.current_altitude_m) if sim.current_altitude_m is not None else pos["altitude_m"],
            "heading_deg": pos.get("heading_deg", 0.0),
            "distance_covered_km": sim.distance_covered_km,
            "remaining_distance_km": sim.remaining_distance_km,
            "elapsed_sim_seconds": sim.elapsed_sim_seconds,
            "remaining_sim_seconds": round((sim.remaining_distance_km / cruise_speed) * 3600.0, 1) if cruise_speed > 0 else 0.0,
            "current_battery_wh": sim.current_battery_wh,
            "battery_percent": round((sim.current_battery_wh / float(drone.battery_capacity_wh) * 100.0), 1) if drone and drone.battery_capacity_wh else 100.0,
            "is_completed": is_completed,
        }

    @staticmethod
    def sync_checkpoint(
        simulation_id: int,
        progress_percent: float,
        latitude: float,
        longitude: float,
        altitude_m: float,
        elapsed_seconds: float,
        distance_covered_km: float,
        remaining_distance_km: float,
        current_battery_wh: float,
        speed_multiplier: float = 1.0,
        extra_data: dict = None,
    ) -> Dict[str, Any]:
        """Checkpoint persist method called periodically by frontend client to save recovery state.

        Prevents unnecessary frequent DB writes while maintaining recovery snapshots.
        """
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        # Ignore checkpoint sync if simulation is already completed or cancelled
        if sim.status in (SimulationStatus.COMPLETED.value, SimulationStatus.CANCELLED.value):
            return sim.to_dict()

        sim.update_checkpoint(
            progress_percent=progress_percent,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude_m,
            elapsed_seconds=elapsed_seconds,
            distance_covered_km=distance_covered_km,
            remaining_distance_km=remaining_distance_km,
            current_battery_wh=current_battery_wh,
            speed_multiplier=speed_multiplier,
            extra_data=extra_data,
        )
        db.session.commit()
        return sim.to_dict()

    @staticmethod
    def get_simulation_state(simulation_id: int) -> Dict[str, Any]:
        """Get the full serialized simulation state with linked route, waypoints, and candidate corridors."""
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        assignment = sim.assignment
        if not assignment:
            raise SimulationServiceError(f"No linked assignment for Simulation #{simulation_id}.")

        route = assignment.route
        delivery_req = assignment.delivery_request
        drone = assignment.drone

        # Fetch selected route waypoints
        waypoints = (
            RouteWaypoint.query
            .filter_by(route_id=route.id)
            .order_by(RouteWaypoint.sequence_number.asc())
            .all()
        )
        wp_dicts = [wp.to_dict() for wp in waypoints]

        # Fetch alternative candidate routes for this delivery request
        all_routes = (
            Route.query
            .filter_by(delivery_request_id=delivery_req.id)
            .order_by(Route.id.asc())
            .all()
        )
        alternatives = []
        for r in all_routes:
            if r.id != route.id:
                r_wps = (
                    RouteWaypoint.query
                    .filter_by(route_id=r.id)
                    .order_by(RouteWaypoint.sequence_number.asc())
                    .all()
                )
                alternatives.append({
                    "id": r.id,
                    "algorithm_name": r.algorithm_name,
                    "estimated_distance_km": float(r.estimated_distance_km),
                    "estimated_duration_minutes": float(r.estimated_duration_minutes),
                    "estimated_energy_wh": float(r.estimated_energy_wh),
                    "route_score": float(r.route_score) if r.route_score is not None else None,
                    "feasibility_status": r.feasibility_status,
                    "rejection_reason": r.rejection_reason,
                    "waypoints": [w.to_dict() for w in r_wps],
                })

        cruise_speed = float(drone.cruise_speed_kmh) if drone and drone.cruise_speed_kmh else 60.0
        remaining_sim_sec = (
            round((sim.remaining_distance_km / cruise_speed) * 3600.0, 1)
            if cruise_speed > 0 and sim.remaining_distance_km > 0
            else 0.0
        )

        battery_pct = (
            round((sim.current_battery_wh / float(drone.battery_capacity_wh)) * 100.0, 1)
            if drone and drone.battery_capacity_wh and sim.current_battery_wh is not None
            else 100.0
        )

        checkpoint_info = sim.get_checkpoint()

        return {
            "simulation": sim.to_dict(),
            "status": sim.status,
            "progress_percent": sim.current_progress_percent,
            "heading_deg": checkpoint_info.get("heading_deg", 0.0),
            "telemetry": {
                "latitude": float(sim.current_latitude) if sim.current_latitude is not None else float(delivery_req.pickup_latitude),
                "longitude": float(sim.current_longitude) if sim.current_longitude is not None else float(delivery_req.pickup_longitude),
                "altitude_m": float(sim.current_altitude_m) if sim.current_altitude_m is not None else 50.0,
                "elapsed_sim_seconds": sim.elapsed_sim_seconds,
                "remaining_sim_seconds": remaining_sim_sec,
                "distance_covered_km": sim.distance_covered_km,
                "remaining_distance_km": sim.remaining_distance_km,
                "current_battery_wh": sim.current_battery_wh,
                "battery_percent": battery_pct,
                "speed_multiplier": sim.speed_multiplier,
            },
            "delivery_request": {
                "id": delivery_req.id,
                "emergency_type": delivery_req.emergency_type,
                "priority": delivery_req.priority,
                "status": delivery_req.status,
                "payload_weight_kg": float(delivery_req.payload_weight_kg),
                "pickup": {
                    "latitude": float(delivery_req.pickup_latitude),
                    "longitude": float(delivery_req.pickup_longitude),
                },
                "destination": {
                    "latitude": float(delivery_req.destination_latitude),
                    "longitude": float(delivery_req.destination_longitude),
                },
            },
            "drone": {
                "id": drone.id,
                "drone_code": drone.drone_code,
                "model_name": drone.model_name,
                "cruise_speed_kmh": cruise_speed,
                "battery_capacity_wh": float(drone.battery_capacity_wh),
                "status": drone.status,
            },
            "selected_route": {
                "id": route.id,
                "algorithm_name": route.algorithm_name,
                "estimated_distance_km": float(route.estimated_distance_km),
                "estimated_duration_minutes": float(route.estimated_duration_minutes),
                "estimated_energy_wh": float(route.estimated_energy_wh),
                "route_score": float(route.route_score) if route.route_score is not None else None,
                "waypoints": wp_dicts,
            },
            "alternative_routes": alternatives,
        }
