"""Discrete-time simulation service for emergency drone delivery missions.

IMPORTANT NOTICE:
This module is strictly a software simulation and numerical kinematics proxy.
It does NOT control real drone hardware, interface with flight controllers,
or produce certified aviation flight plans. It is designed solely for academic
evaluation, mission rehearsal, and dispatch route validation.
"""

import json
import math
import uuid
from dataclasses import dataclass
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
from app.services.weather_service import WeatherData


@dataclass
class DynamicRerouteResult:
    """Outcome of an in-flight dynamic rerouting evaluation."""
    switched: bool
    original_route_id: int
    new_route_id: Optional[int]
    reason: str
    previous_corridor: str
    new_corridor: Optional[str]
    candidates_evaluated_count: int
    feasible_candidates_count: int
    policy_name: str
    explanation: str

    def to_dict(self) -> dict:
        return {
            "switched": self.switched,
            "original_route_id": self.original_route_id,
            "new_route_id": self.new_route_id,
            "reason": self.reason,
            "previous_corridor": self.previous_corridor,
            "new_corridor": self.new_corridor,
            "candidates_evaluated_count": self.candidates_evaluated_count,
            "feasible_candidates_count": self.feasible_candidates_count,
            "policy_name": self.policy_name,
            "explanation": self.explanation,
        }


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
                try:
                    from app.models.drone_booking import DroneBooking, BookingStatus
                    from app.services.notification_service import NotificationService
                    booking = DroneBooking.query.filter_by(
                        delivery_request_id=assignment.delivery_request_id
                    ).first()
                    if booking and booking.status != BookingStatus.CANCELLED.value:
                        booking.status = BookingStatus.DELIVERED.value
                        NotificationService.create_notification(
                            user_id=booking.requester_id,
                            booking_id=booking.id,
                            delivery_request_id=assignment.delivery_request_id,
                            notification_type="DELIVERY_COMPLETED",
                            title="Emergency Delivery Completed",
                            message=f"Mission {booking.booking_reference} delivered successfully. Thank you for using Smart Drone Dispatch.",
                            severity="SUCCESS",
                        )
                except Exception:
                    pass

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

        weather_safety = None
        if not is_completed:
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

            # In-flight weather monitoring & dynamic safety management
            try:
                weather_safety = SimulationService.evaluate_in_flight_weather_and_safety(
                    sim=sim,
                    assignment=assignment,
                    pos=pos,
                    current_battery=current_battery,
                )
            except Exception:
                weather_safety = None

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
            "weather_safety": weather_safety,
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

        # Validate kinematic & boundary constraints
        lat_f = float(latitude)
        lon_f = float(longitude)
        alt_f = float(altitude_m)
        prog_f = float(progress_percent)
        elapsed_f = float(elapsed_seconds)
        dist_cov_f = float(distance_covered_km)
        dist_rem_f = float(remaining_distance_km)
        batt_f = float(current_battery_wh)
        speed_mult_f = float(speed_multiplier)

        if not (-90.0 <= lat_f <= 90.0):
            raise ValueError(f"Checkpoint latitude out of range: {lat_f}. Must be between -90 and +90.")
        if not (-180.0 <= lon_f <= 180.0):
            raise ValueError(f"Checkpoint longitude out of range: {lon_f}. Must be between -180 and +180.")
        if alt_f < 0:
            raise ValueError(f"Checkpoint altitude cannot be negative: {alt_f}m.")
        if not (0.0 <= prog_f <= 100.0):
            raise ValueError(f"Checkpoint progress percent must be between 0 and 100: {prog_f}")
        if elapsed_f < 0:
            raise ValueError("Elapsed simulation seconds cannot be negative.")
        if dist_cov_f < 0:
            raise ValueError("Distance covered cannot be negative.")
        if dist_rem_f < 0:
            raise ValueError("Remaining distance cannot be negative.")
        if batt_f < 0:
            raise ValueError("Current battery cannot be negative.")
        if not (0.1 <= speed_mult_f <= 50.0):
            raise ValueError(f"Speed multiplier must be between 0.1 and 50.0: {speed_mult_f}")

        sim.update_checkpoint(
            progress_percent=prog_f,
            latitude=lat_f,
            longitude=lon_f,
            altitude_m=alt_f,
            elapsed_seconds=elapsed_f,
            distance_covered_km=dist_cov_f,
            remaining_distance_km=dist_rem_f,
            current_battery_wh=batt_f,
            speed_multiplier=speed_mult_f,
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

    @staticmethod
    def evaluate_and_reroute(
        simulation_id: int,
        updated_weather: WeatherData,
        policy_name: str = "SAFETY_MANDATED",
        min_improvement_pct: float = 5.0,
        reason: str = "In-flight environmental condition change",
    ) -> DynamicRerouteResult:
        """Evaluate in-flight dynamic rerouting from current simulated drone position.

        Generates and evaluates replacement corridors from current coordinates to destination.
        Switches only if:
        1. A replacement route passes all physical and weather feasibility checks.
        2. The switching policy is satisfied:
           - 'SAFETY_MANDATED': Switches if current corridor became infeasible or if a feasible
             detour avoids adverse weather.
           - 'OBJECTIVE_IMPROVEMENT': Switches if replacement reduces composite objective cost
             by at least min_improvement_pct.
        Preserves original Route in database and records an immutable reroute audit trail.
        """
        sim = db.session.get(SimulationRun, simulation_id)
        if not sim:
            raise SimulationServiceError(f"SimulationRun #{simulation_id} not found.")

        if sim.status not in (SimulationStatus.RUNNING.value, SimulationStatus.PAUSED.value):
            raise InvalidSimulationStateTransitionError(
                f"Dynamic rerouting can only be evaluated for active simulations (current: {sim.status})."
            )

        assignment = sim.assignment
        if not assignment or not assignment.route or not assignment.delivery_request or not assignment.drone:
            raise SimulationServiceError(f"Simulation #{simulation_id} missing linked entities.")

        orig_route = assignment.route
        req = assignment.delivery_request
        drone = assignment.drone

        curr_lat = float(sim.current_latitude) if sim.current_latitude is not None else float(req.pickup_latitude)
        curr_lon = float(sim.current_longitude) if sim.current_longitude is not None else float(req.pickup_longitude)
        dest_lat = float(req.destination_latitude)
        dest_lon = float(req.destination_longitude)

        remaining_direct_dist = haversine_distance(curr_lat, curr_lon, dest_lat, dest_lon)
        if remaining_direct_dist < 0.10:
            return DynamicRerouteResult(
                switched=False,
                original_route_id=orig_route.id,
                new_route_id=None,
                reason=reason,
                previous_corridor=orig_route.algorithm_name,
                new_corridor=None,
                candidates_evaluated_count=0,
                feasible_candidates_count=0,
                policy_name=policy_name,
                explanation="Drone is within 100 meters of destination (final landing approach). Rerouting omitted.",
            )

        # Usable remaining battery on drone
        curr_battery_wh = float(sim.current_battery_wh) if sim.current_battery_wh is not None else float(drone.current_battery_wh)

        # Generate replacement candidate corridors from current position to destination
        from app.services.route_optimizer import RouteOptimizer
        opt_res = RouteOptimizer.optimize(
            pickup_lat=curr_lat,
            pickup_lng=curr_lon,
            dest_lat=dest_lat,
            dest_lng=dest_lon,
            payload_weight_kg=float(req.payload_weight_kg),
            drone_cruise_speed_kmh=float(drone.cruise_speed_kmh),
            drone_max_payload_kg=float(drone.maximum_payload_kg),
            drone_battery_capacity_wh=float(drone.battery_capacity_wh),
            drone_current_battery_wh=curr_battery_wh,
            weather=updated_weather,
            algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
        )

        if not opt_res.is_feasible or not opt_res.selected_route:
            return DynamicRerouteResult(
                switched=False,
                original_route_id=orig_route.id,
                new_route_id=None,
                reason=reason,
                previous_corridor=orig_route.algorithm_name,
                new_corridor=None,
                candidates_evaluated_count=opt_res.candidate_count,
                feasible_candidates_count=0,
                policy_name=policy_name,
                explanation=(
                    f"Rerouting evaluation completed: No replacement candidate satisfies safety constraints "
                    f"under updated conditions ({updated_weather.weather_summary}, wind {updated_weather.wind_speed_mps} m/s). "
                    f"Retaining original flight plan."
                ),
            )

        best_cand = opt_res.selected_route

        # Evaluate Switching Policy
        should_switch = False
        policy_explanation = ""

        current_score = float(orig_route.route_score) if orig_route.route_score is not None else 0.5
        new_score = float(best_cand.objective_score)

        if policy_name == "SAFETY_MANDATED":
            should_switch = True
            policy_explanation = (
                f"Safety-mandated rerouting accepted: Adopted '{best_cand.corridor_name}' "
                f"to navigate around updated weather hazard ({updated_weather.weather_summary})."
            )
        elif policy_name == "OBJECTIVE_IMPROVEMENT":
            # Compare estimated remaining flight energy of current route vs new replacement corridor
            orig_dist = float(orig_route.estimated_distance_km)
            orig_energy = float(orig_route.estimated_energy_wh)
            remaining_ratio = (float(sim.remaining_distance_km) / orig_dist) if orig_dist > 0 else 1.0
            curr_remaining_energy = max(0.1, remaining_ratio * orig_energy)
            new_energy = float(best_cand.energy_wh)

            if curr_remaining_energy > 0:
                improvement_pct = ((curr_remaining_energy - new_energy) / curr_remaining_energy) * 100.0
            else:
                improvement_pct = 0.0

            if improvement_pct >= min_improvement_pct:
                should_switch = True
                policy_explanation = (
                    f"Objective improvement policy satisfied: Remaining energy reduced by {improvement_pct:.1f}% "
                    f"(from {curr_remaining_energy:.1f} Wh to {new_energy:.1f} Wh), exceeding threshold of {min_improvement_pct:.1f}%."
                )
            else:
                should_switch = False
                policy_explanation = (
                    f"Switching policy rejected: Remaining energy improvement of {improvement_pct:.1f}% "
                    f"(from {curr_remaining_energy:.1f} Wh to {new_energy:.1f} Wh) does not meet required threshold of {min_improvement_pct:.1f}%."
                )
        else:
            should_switch = True
            policy_explanation = f"Policy '{policy_name}' satisfied."

        if not should_switch:
            return DynamicRerouteResult(
                switched=False,
                original_route_id=orig_route.id,
                new_route_id=None,
                reason=reason,
                previous_corridor=orig_route.algorithm_name,
                new_corridor=best_cand.corridor_name,
                candidates_evaluated_count=opt_res.candidate_count,
                feasible_candidates_count=opt_res.feasible_count,
                policy_name=policy_name,
                explanation=policy_explanation,
            )

        # PRESERVE ORIGINAL ROUTE & PERSIST FULL REVISED REPLACEMENT ROUTE
        # Collect prior waypoints traversed from start up to current position
        orig_wps = (
            RouteWaypoint.query.filter_by(route_id=orig_route.id)
            .order_by(RouteWaypoint.sequence_number.asc())
            .all()
        )
        orig_wp_dicts = [wp.to_dict() for wp in orig_wps]
        cum_dists, _ = get_route_segment_metrics(orig_wp_dicts)

        prior_distance = float(sim.distance_covered_km)
        prior_waypoints: List[Tuple[float, float, float]] = []
        for idx, wp in enumerate(orig_wps):
            if cum_dists[idx] < (prior_distance - 0.05):
                prior_waypoints.append((float(wp.latitude), float(wp.longitude), float(wp.altitude_m)))

        if not prior_waypoints and orig_wps:
            prior_waypoints.append((float(orig_wps[0].latitude), float(orig_wps[0].longitude), float(orig_wps[0].altitude_m)))

        # Add current position
        curr_alt = float(sim.current_altitude_m) if sim.current_altitude_m is not None else 50.0
        prior_waypoints.append((curr_lat, curr_lon, curr_alt))

        # Add forward candidate waypoints (excluding index 0 which is curr_lat, curr_lon)
        forward_waypoints = [
            (float(wp.latitude), float(wp.longitude), float(wp.altitude_m))
            for wp in best_cand.waypoints[1:]
        ]
        all_revised_waypoints = prior_waypoints + forward_waypoints

        # Recalculate total revised distance
        full_wps_dicts = [{"latitude": lat, "longitude": lon} for lat, lon, _ in all_revised_waypoints]
        _, full_revised_distance = get_route_segment_metrics(full_wps_dicts)

        prior_elapsed_min = float(sim.elapsed_sim_seconds) / 60.0
        total_revised_duration = prior_elapsed_min + float(best_cand.duration_minutes)

        # Estimate prior energy spent based on ratio of distance covered
        orig_energy = float(orig_route.estimated_energy_wh)
        ratio = (prior_distance / float(orig_route.estimated_distance_km)) if float(orig_route.estimated_distance_km) > 0 else 0.0
        prior_energy = ratio * orig_energy
        total_revised_energy = prior_energy + float(best_cand.energy_wh)

        replacement_route = Route(
            delivery_request_id=req.id,
            algorithm_name=f"REROUTE:{best_cand.candidate_id}",
            estimated_distance_km=round(full_revised_distance, 3),
            estimated_duration_minutes=round(total_revised_duration, 2),
            estimated_energy_wh=round(total_revised_energy, 2),
            route_score=best_cand.objective_score,
            feasibility_status=FeasibilityStatus.FEASIBLE.value,
            rejection_reason=f"Dynamic reroute from Route #{orig_route.id}. Reason: {reason}",
        )
        db.session.add(replacement_route)
        db.session.flush()

        # Persist full revised sequence of waypoints starting from pickup through reroute to destination
        for idx, (lat, lon, alt) in enumerate(all_revised_waypoints):
            db.session.add(
                RouteWaypoint(
                    route_id=replacement_route.id,
                    sequence_number=idx,
                    latitude=lat,
                    longitude=lon,
                    altitude_m=alt,
                )
            )

        # Update assignment's active route reference (preserves original route in DB)
        assignment.route_id = replacement_route.id

        # Update simulation trajectory parameters and remaining distance
        params = sim.get_parameters()
        reroute_history = params.setdefault("reroute_history", [])
        reroute_history.append({
            "original_route_id": orig_route.id,
            "new_route_id": replacement_route.id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_sim_seconds": sim.elapsed_sim_seconds,
            "reason": reason,
            "policy": policy_name,
            "weather_update": {
                "wind_speed_mps": updated_weather.wind_speed_mps,
                "visibility_km": updated_weather.visibility_km,
                "precipitation_mmh": updated_weather.precipitation_mmh,
                "weather_summary": updated_weather.weather_summary,
            },
            "reroute_origin": {"latitude": curr_lat, "longitude": curr_lon},
            "new_corridor": best_cand.corridor_name,
            "new_remaining_distance_km": best_cand.distance_km,
        })
        sim.parameters_json = json.dumps(params)
        sim.remaining_distance_km = best_cand.distance_km

        db.session.commit()

        return DynamicRerouteResult(
            switched=True,
            original_route_id=orig_route.id,
            new_route_id=replacement_route.id,
            reason=reason,
            previous_corridor=orig_route.algorithm_name,
            new_corridor=best_cand.corridor_name,
            candidates_evaluated_count=opt_res.candidate_count,
            feasible_candidates_count=opt_res.feasible_count,
            policy_name=policy_name,
            explanation=policy_explanation,
        )

    @classmethod
    def evaluate_in_flight_weather_and_safety(
        cls,
        sim: SimulationRun,
        assignment: DroneAssignment,
        pos: Dict[str, Any],
        current_battery: float,
    ) -> Dict[str, Any]:
        """Monitors real-time weather during simulation step and triggers rerouting or emergency diversion."""
        from app.models.drone_booking import DroneBooking, BookingStatus
        from app.models.weather_intelligence import WeatherClassification, WeatherAlert
        from app.services.weather_service import WeatherData
        from app.services.weather_intelligence_service import WeatherIntelligenceService
        from app.services.payment_service import PaymentService
        from app.services.notification_service import NotificationService

        curr_lat = pos["latitude"]
        curr_lon = pos["longitude"]
        curr_alt = pos.get("altitude_m", 50.0)

        # 1. Sample real-time weather at current simulated drone position
        obs = WeatherIntelligenceService.sample_weather_at_coordinate(curr_lat, curr_lon, curr_alt)
        classification = WeatherClassification(obs.classification)

        # 2. Check linked DroneBooking (if initiated via smart booking)
        booking = DroneBooking.query.filter_by(
            delivery_request_id=assignment.delivery_request_id
        ).first()

        safety_report = {
            "classification": classification.value,
            "wind_speed_mps": float(obs.wind_speed_mps),
            "precipitation_mmh": float(obs.precipitation_mmh),
            "visibility_km": float(obs.visibility_km),
            "weather_summary": obs.weather_summary,
            "action_taken": "NOMINAL_FLIGHT_CONTINUED",
        }

        # Case A: GREEN - Nominal flight
        if classification == WeatherClassification.GREEN:
            if booking and booking.status == BookingStatus.WEATHER_CAUTION.value:
                booking.status = BookingStatus.IN_FLIGHT.value
            return safety_report

        # Case B: YELLOW - Caution range
        if classification == WeatherClassification.YELLOW:
            safety_report["action_taken"] = "WEATHER_CAUTION_ALERT"
            if booking and booking.status not in (BookingStatus.DIVERTED.value, BookingStatus.REROUTED.value):
                booking.status = BookingStatus.WEATHER_CAUTION.value

            # Record WeatherAlert
            alert = WeatherAlert(
                booking_id=booking.id if booking else None,
                simulation_run_id=sim.id,
                alert_level="CAUTION",
                weather_classification="YELLOW",
                affected_segment=f"Waypoint Sector ({curr_lat:.4f}, {curr_lon:.4f})",
                warning_description=f"Approaching weather tolerance: wind {obs.wind_speed_mps} m/s.",
                recommended_action="Increase telemetry monitoring frequency.",
            )
            db.session.add(alert)
            return safety_report

        # Case C & D & E: RED - Severe atmospheric hazard!
        safety_report["action_taken"] = "SEVERE_WEATHER_HAZARD"
        weather_data = WeatherData(
            wind_speed_mps=float(obs.wind_speed_mps),
            precipitation_mmh=float(obs.precipitation_mmh),
            visibility_km=float(obs.visibility_km),
            weather_summary=obs.weather_summary,
            is_simulated=True,
            captured_at=obs.captured_at,
        )

        # Attempt dynamic rerouting via existing SAFETY_MANDATED policy
        try:
            reroute_res = cls.evaluate_and_reroute(
                simulation_id=sim.id,
                updated_weather=weather_data,
                policy_name="SAFETY_MANDATED",
                reason="In-flight severe atmospheric hazard (RED classification)",
            )
        except Exception:
            reroute_res = None

        if reroute_res and reroute_res.switched:
            # Case C: Safely rerouted!
            safety_report["action_taken"] = "DYNAMIC_REROUTE_EXECUTED"
            safety_report["new_corridor"] = reroute_res.new_corridor
            if booking:
                booking.status = BookingStatus.REROUTED.value

            alert = WeatherAlert(
                booking_id=booking.id if booking else None,
                simulation_run_id=sim.id,
                alert_level="HAZARD",
                weather_classification="RED",
                affected_segment=f"Corridor {reroute_res.previous_corridor}",
                warning_description=f"Hazardous wind {obs.wind_speed_mps} m/s exceeded 12.0 m/s limit.",
                recommended_action=f"Switched dynamically to replacement corridor '{reroute_res.new_corridor}'.",
            )
            db.session.add(alert)

            NotificationService.create_notification(
                user_id=booking.requester_id if booking else None,
                target_role="OPERATOR",
                booking_id=booking.id if booking else None,
                delivery_request_id=assignment.delivery_request_id,
                notification_type="DYNAMIC_REROUTING",
                title="Dynamic In-Flight Rerouting Triggered",
                message=f"Mission safely rerouted to '{reroute_res.new_corridor}' to avoid weather hazard.",
                severity="WARNING",
            )
            return safety_report

        # Case D: No feasible alternative corridor exists -> Initiate Emergency Diversion
        diversion = WeatherIntelligenceService.find_nearest_safe_diversion(
            current_lat=curr_lat,
            current_lng=curr_lon,
            remaining_battery_wh=current_battery,
        )

        if diversion and diversion["is_reachable"]:
            safety_report["action_taken"] = "EMERGENCY_DIVERSION_INITIATED"
            safety_report["diversion_location"] = diversion["name"]

            # Pause regular mission flight simulation
            sim.pause()

            if booking:
                booking.status = BookingStatus.DIVERTED.value
                try:
                    PaymentService.process_refund(
                        booking_id=booking.id,
                        refund_type="DIVERSION_COMPENSATION",
                        reason=f"Mission diverted to {diversion['name']} due to severe weather.",
                    )
                except Exception:
                    pass

            alert = WeatherAlert(
                booking_id=booking.id if booking else None,
                simulation_run_id=sim.id,
                alert_level="CRITICAL",
                weather_classification="RED",
                affected_segment="Full Destination Airspace Closed",
                warning_description=f"All forward corridors blocked. Emergency diversion to {diversion['name']}.",
                recommended_action=f"Execute safe landing at {diversion['code']}.",
            )
            db.session.add(alert)

            NotificationService.create_notification(
                user_id=booking.requester_id if booking else None,
                target_role="OPERATOR",
                booking_id=booking.id if booking else None,
                delivery_request_id=assignment.delivery_request_id,
                notification_type="EMERGENCY_DIVERSION",
                title="Emergency Mission Diversion",
                message=f"Severe weather blocked all corridors. Drone diverted to {diversion['name']} ({diversion['distance_km']} km away).",
                severity="DANGER",
            )
            return safety_report

        # Case E: No safe diversion location reachable -> Emergency State
        safety_report["action_taken"] = "CRITICAL_EMERGENCY_STATE"
        sim.pause()
        if booking:
            booking.status = BookingStatus.EMERGENCY_REVIEW.value

        alert = WeatherAlert(
            booking_id=booking.id if booking else None,
            simulation_run_id=sim.id,
            alert_level="CRITICAL",
            weather_classification="RED",
            affected_segment="Airspace & Diversion Exhaustion",
            warning_description="No feasible alternative flight corridors or reachable emergency diversion sites.",
            recommended_action="Emergency operator manual review and immediate recovery protocol.",
        )
        db.session.add(alert)

        NotificationService.create_notification(
            user_id=booking.requester_id if booking else None,
            target_role="OPERATOR",
            booking_id=booking.id if booking else None,
            delivery_request_id=assignment.delivery_request_id,
            notification_type="EMERGENCY_DIVERSION",
            title="CRITICAL EMERGENCY STATE",
            message="No feasible route or safe diversion site reachable. Manual incident review initiated.",
            severity="DANGER",
        )
        return safety_report
