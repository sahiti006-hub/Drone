from datetime import datetime, timezone
from app.extensions import db
from app.models.drone import Drone, DroneStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus
from app.models.route import Route, FeasibilityStatus
from app.models.drone_assignment import DroneAssignment, AssignmentStatus


class AssignmentServiceError(Exception):
    """Base exception for drone assignment operations."""
    pass


class ConflictingAssignmentError(AssignmentServiceError):
    """Raised when an active assignment already locks the drone or request."""
    pass


class InfeasibleAssignmentError(AssignmentServiceError):
    """Raised when payload or battery capacity cannot satisfy the delivery route."""
    pass


class AssignmentService:
    """Service governing mission dispatch, ACID transaction guarantees, and conflict prevention."""

    @staticmethod
    def create_assignment(delivery_request_id: int, drone_id: int, route_id: int) -> DroneAssignment:
        """Atomically assign a drone to a delivery request and route.

        Guarantees:
        - Prevents multiple concurrent active assignments for the same drone.
        - Prevents multiple concurrent active assignments for the same delivery request.
        - Verifies drone payload capacity >= cargo weight.
        - Verifies drone current battery >= route estimated energy.
        - Updates drone status to IN_TRANSIT and request status to ASSIGNED.
        - Fully rolled back upon any validation or database failure.
        """
        try:
            # Step 1: Validate Request
            request = db.session.get(DeliveryRequest, delivery_request_id)
            if not request:
                raise AssignmentServiceError(f"Delivery request ID {delivery_request_id} does not exist.")

            # Check if this request already has an active assignment
            active_req_assignment = DroneAssignment.query.filter_by(
                delivery_request_id=request.id,
                status=AssignmentStatus.ACTIVE.value,
            ).first()
            if active_req_assignment:
                raise ConflictingAssignmentError(
                    f"Delivery request #{request.id} already has an active assignment (#{active_req_assignment.id})."
                )

            if request.status not in {RequestStatus.PENDING.value, RequestStatus.ROUTE_CALCULATED.value}:
                raise AssignmentServiceError(
                    f"Delivery request #{request.id} is not eligible for assignment (status: {request.status})."
                )

            # Step 2: Validate Drone
            drone = db.session.get(Drone, drone_id)
            if not drone:
                raise AssignmentServiceError(f"Drone ID {drone_id} does not exist.")

            if drone.is_decommissioned:
                raise AssignmentServiceError(f"Drone {drone.drone_code} is decommissioned.")

            # Check if this drone already has an active assignment
            active_drone_assignment = DroneAssignment.query.filter_by(
                drone_id=drone.id,
                status=AssignmentStatus.ACTIVE.value,
            ).first()
            if active_drone_assignment:
                raise ConflictingAssignmentError(
                    f"Drone {drone.drone_code} is already assigned to active mission (#{active_drone_assignment.id})."
                )

            if drone.status != DroneStatus.AVAILABLE.value:
                raise AssignmentServiceError(
                    f"Drone {drone.drone_code} is not available (current status: {drone.status})."
                )

            # Step 3: Validate Route
            route = db.session.get(Route, route_id)
            if not route:
                raise AssignmentServiceError(f"Route ID {route_id} does not exist.")

            if route.delivery_request_id != request.id:
                raise AssignmentServiceError(
                    f"Route #{route.id} does not belong to delivery request #{request.id}."
                )

            if route.feasibility_status != FeasibilityStatus.FEASIBLE.value:
                raise InfeasibleAssignmentError(
                    f"Route #{route.id} is marked as INFEASIBLE: {route.rejection_reason}"
                )

            # Step 4: Feasibility checks (Payload & Battery)
            if float(drone.maximum_payload_kg) < float(request.payload_weight_kg):
                raise InfeasibleAssignmentError(
                    f"Drone payload capacity ({drone.maximum_payload_kg} kg) cannot carry "
                    f"payload weight ({request.payload_weight_kg} kg)."
                )

            # Reserve a 15% safety battery reserve
            battery_needed = float(route.estimated_energy_wh) * 1.15
            if float(drone.current_battery_wh) < battery_needed:
                raise InfeasibleAssignmentError(
                    f"Drone battery ({drone.current_battery_wh} Wh) insufficient for route "
                    f"(required with safety buffer: {round(battery_needed, 2)} Wh)."
                )

            # Step 5: Atomically create assignment and update states
            assignment = DroneAssignment(
                delivery_request_id=request.id,
                drone_id=drone.id,
                route_id=route.id,
                status=AssignmentStatus.ACTIVE.value,
            )

            drone.status = DroneStatus.IN_TRANSIT.value
            request.status = RequestStatus.ASSIGNED.value

            db.session.add(assignment)
            db.session.commit()
            return assignment

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def complete_assignment(assignment_id: int) -> DroneAssignment:
        """Mark an assignment completed, update drone and request states atomically."""
        try:
            assignment = db.session.get(DroneAssignment, assignment_id)
            if not assignment:
                raise AssignmentServiceError(f"Assignment #{assignment_id} not found.")

            if assignment.status != AssignmentStatus.ACTIVE.value:
                raise AssignmentServiceError(
                    f"Assignment #{assignment_id} is not ACTIVE (current status: {assignment.status})."
                )

            assignment.mark_completed()

            # Deduct consumed energy from drone battery
            route = assignment.route
            drone = assignment.drone
            energy_used = float(route.estimated_energy_wh)
            remaining_battery = max(0.0, float(drone.current_battery_wh) - energy_used)
            drone.current_battery_wh = remaining_battery

            # If battery is low (< 25%), switch to CHARGING, otherwise AVAILABLE
            if drone.battery_percentage < 25.0:
                drone.status = DroneStatus.CHARGING.value
            else:
                drone.status = DroneStatus.AVAILABLE.value

            # Update request status to DELIVERED
            assignment.delivery_request.status = RequestStatus.DELIVERED.value

            db.session.commit()
            return assignment

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def abort_assignment(assignment_id: int, reason: str = "Mission aborted by operator") -> DroneAssignment:
        """Abort an active assignment safely returning drone to available."""
        try:
            assignment = db.session.get(DroneAssignment, assignment_id)
            if not assignment:
                raise AssignmentServiceError(f"Assignment #{assignment_id} not found.")

            if assignment.status != AssignmentStatus.ACTIVE.value:
                raise AssignmentServiceError(f"Cannot abort non-active assignment #{assignment_id}.")

            assignment.mark_aborted()
            assignment.drone.status = DroneStatus.AVAILABLE.value
            assignment.delivery_request.status = RequestStatus.PENDING.value

            db.session.commit()
            return assignment

        except Exception:
            db.session.rollback()
            raise
