from app.extensions import db
from app.models.drone import Drone, DroneStatus, ALLOWED_DRONE_TRANSITIONS


class DroneServiceError(Exception):
    """Base exception for drone service errors."""
    pass


class InvalidDroneTransitionError(DroneServiceError):
    """Raised when an illegal drone state transition is attempted."""
    pass


class DroneNotFoundError(DroneServiceError):
    """Raised when the specified drone cannot be located."""
    pass


class DroneService:
    """Service layer governing drone lifecycle, hardware limits, and state transitions."""

    @staticmethod
    def register_drone(
        drone_code: str,
        model_name: str,
        maximum_payload_kg: float,
        battery_capacity_wh: float,
        current_battery_wh: float = None,
        cruise_speed_kmh: float = 60.0,
    ) -> Drone:
        """Register a new drone in the fleet with validation."""
        drone_code_clean = drone_code.strip().upper()
        existing = Drone.query.filter_by(drone_code=drone_code_clean).first()
        if existing:
            raise DroneServiceError(f"Drone with code '{drone_code_clean}' already exists.")

        drone = Drone(
            drone_code=drone_code_clean,
            model_name=model_name,
            maximum_payload_kg=maximum_payload_kg,
            battery_capacity_wh=battery_capacity_wh,
            current_battery_wh=current_battery_wh,
            cruise_speed_kmh=cruise_speed_kmh,
            status=DroneStatus.AVAILABLE.value,
        )
        db.session.add(drone)
        db.session.commit()
        return drone

    @staticmethod
    def update_drone_status(drone_id: int, target_status: DroneStatus | str) -> Drone:
        """Transition drone to a new state enforcing state machine rules."""
        target = target_status if isinstance(target_status, DroneStatus) else DroneStatus(str(target_status).upper())

        drone = db.session.get(Drone, drone_id)
        if not drone:
            raise DroneNotFoundError(f"Drone with ID {drone_id} not found.")

        if drone.is_decommissioned:
            raise DroneServiceError(f"Cannot change status: Drone {drone.drone_code} is decommissioned.")

        current = DroneStatus(drone.status)
        if target == current:
            return drone

        if not drone.can_transition_to(target):
            valid_targets = [s.value for s in ALLOWED_DRONE_TRANSITIONS.get(current, set())]
            raise InvalidDroneTransitionError(
                f"Illegal transition for Drone {drone.drone_code}: cannot move from "
                f"'{current.value}' to '{target.value}'. Allowed: {valid_targets}"
            )

        drone.status = target.value
        db.session.commit()
        return drone

    @staticmethod
    def decommission_drone(drone_id: int) -> Drone:
        """Decommission a drone without deleting historical mission records.

        Ensures data audit integrity is preserved.
        """
        drone = db.session.get(Drone, drone_id)
        if not drone:
            raise DroneNotFoundError(f"Drone with ID {drone_id} not found.")

        # Check for active assignments
        from app.models.drone_assignment import DroneAssignment, AssignmentStatus
        active_assignment = DroneAssignment.query.filter_by(
            drone_id=drone.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()

        if active_assignment:
            raise DroneServiceError(
                f"Cannot decommission drone {drone.drone_code}: active mission in progress (Assignment #{active_assignment.id})."
            )

        drone.is_decommissioned = True
        drone.status = DroneStatus.MAINTENANCE.value
        db.session.commit()
        return drone
