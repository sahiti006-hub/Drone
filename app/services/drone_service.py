from app.extensions import db
from app.models.drone import Drone, DroneStatus, ALLOWED_DRONE_TRANSITIONS
from app.models.drone_assignment import DroneAssignment, AssignmentStatus


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
    """Service layer governing drone lifecycle, hardware limits, inventory, and state transitions."""

    @staticmethod
    def register_drone(
        drone_code: str,
        model_name: str,
        maximum_payload_kg: float,
        battery_capacity_wh: float,
        current_battery_wh: float = None,
        cruise_speed_kmh: float = 60.0,
    ) -> Drone:
        """Register a new drone in the fleet with complete hardware validation."""
        drone_code_clean = drone_code.strip().upper()
        existing = Drone.query.filter_by(drone_code=drone_code_clean).first()
        if existing:
            raise DroneServiceError(f"Drone with code '{drone_code_clean}' already exists.")

        if float(maximum_payload_kg) <= 0:
            raise ValueError("Maximum payload capacity must be positive.")
        if float(battery_capacity_wh) <= 0:
            raise ValueError("Battery capacity must be positive.")
        if float(cruise_speed_kmh) <= 0:
            raise ValueError("Cruise speed must be positive.")

        initial_batt = float(current_battery_wh) if current_battery_wh is not None else float(battery_capacity_wh)
        if initial_batt < 0 or initial_batt > float(battery_capacity_wh):
            raise ValueError("Current battery level must be between 0 and maximum battery capacity.")

        drone = Drone(
            drone_code=drone_code_clean,
            model_name=model_name,
            maximum_payload_kg=maximum_payload_kg,
            battery_capacity_wh=battery_capacity_wh,
            current_battery_wh=initial_batt,
            cruise_speed_kmh=cruise_speed_kmh,
            status=DroneStatus.AVAILABLE.value,
        )
        db.session.add(drone)
        db.session.commit()
        return drone

    @staticmethod
    def get_drones(
        status: str = None,
        min_payload: float = None,
        include_decommissioned: bool = False,
    ) -> list[Drone]:
        """Query drone fleet filtered by operational status and minimum payload capacity."""
        query = Drone.query

        if not include_decommissioned:
            query = query.filter(Drone.is_decommissioned.is_(False))

        if status:
            query = query.filter(Drone.status == str(status).upper())

        if min_payload is not None:
            query = query.filter(Drone.maximum_payload_kg >= float(min_payload))

        return query.order_by(Drone.created_at.desc()).all()

    @staticmethod
    def get_drone_by_id(drone_id: int) -> Drone:
        """Retrieve a single drone or raise DroneNotFoundError."""
        drone = db.session.get(Drone, drone_id)
        if not drone:
            raise DroneNotFoundError(f"Drone ID {drone_id} not found.")
        return drone

    @staticmethod
    def update_drone(
        drone_id: int,
        model_name: str = None,
        maximum_payload_kg: float = None,
        battery_capacity_wh: float = None,
        current_battery_wh: float = None,
        cruise_speed_kmh: float = None,
    ) -> Drone:
        """Update permitted hardware properties of a drone with validation."""
        drone = DroneService.get_drone_by_id(drone_id)

        if drone.is_decommissioned:
            raise DroneServiceError(f"Cannot edit decommissioned Drone {drone.drone_code}.")

        if model_name:
            drone.model_name = model_name.strip()

        if maximum_payload_kg is not None:
            val = float(maximum_payload_kg)
            if val <= 0:
                raise ValueError("Payload capacity must be strictly positive.")
            drone.maximum_payload_kg = val

        if battery_capacity_wh is not None:
            val = float(battery_capacity_wh)
            if val <= 0:
                raise ValueError("Battery capacity must be strictly positive.")
            drone.battery_capacity_wh = val

        if current_battery_wh is not None:
            val = float(current_battery_wh)
            if val < 0 or val > float(drone.battery_capacity_wh):
                raise ValueError(
                    f"Current battery level ({val} Wh) must be between 0 and capacity ({drone.battery_capacity_wh} Wh)."
                )
            drone.current_battery_wh = val

        if cruise_speed_kmh is not None:
            val = float(cruise_speed_kmh)
            if val <= 0:
                raise ValueError("Cruise speed must be strictly positive.")
            drone.cruise_speed_kmh = val

        db.session.commit()
        return drone

    @staticmethod
    def update_drone_status(drone_id: int, target_status: DroneStatus | str) -> Drone:
        """Transition drone to a new state enforcing state machine rules and active assignment lock."""
        target = target_status if isinstance(target_status, DroneStatus) else DroneStatus(str(target_status).upper())

        drone = DroneService.get_drone_by_id(drone_id)

        if drone.is_decommissioned:
            raise DroneServiceError(f"Cannot change status: Drone {drone.drone_code} is decommissioned.")

        # Guard: An actively assigned drone cannot be casually marked AVAILABLE
        active_assignment = DroneAssignment.query.filter_by(
            drone_id=drone.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()

        if active_assignment and target == DroneStatus.AVAILABLE:
            raise DroneServiceError(
                f"Cannot mark Drone {drone.drone_code} as AVAILABLE while assigned to Active Mission "
                f"(Assignment #{active_assignment.id}). Complete or abort the mission first."
            )

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
    def check_drone_eligibility(
        drone_id: int,
        payload_weight_kg: float,
        estimated_energy_wh: float = None,
    ) -> tuple[bool, str]:
        """Check whether a drone is eligible to accept an emergency delivery assignment.

        Returns:
            tuple: (is_eligible: bool, reason_message: str)
        """
        drone = db.session.get(Drone, drone_id)
        if not drone:
            return False, "Drone does not exist."

        if drone.is_decommissioned:
            return False, f"Drone {drone.drone_code} is decommissioned."

        if drone.status != DroneStatus.AVAILABLE.value:
            return False, f"Drone is currently in '{drone.status}' state."

        # Active assignment check
        active = DroneAssignment.query.filter_by(drone_id=drone.id, status=AssignmentStatus.ACTIVE.value).first()
        if active:
            return False, f"Drone is currently locked in active assignment #{active.id}."

        if float(drone.maximum_payload_kg) < float(payload_weight_kg):
            return False, (
                f"Payload exceeds drone capacity: requires {payload_weight_kg} kg, "
                f"drone maximum is {drone.maximum_payload_kg} kg."
            )

        if estimated_energy_wh is not None:
            safety_reserve = float(estimated_energy_wh) * 1.15
            if float(drone.current_battery_wh) < safety_reserve:
                return False, (
                    f"Insufficient battery: requires {round(safety_reserve, 2)} Wh with safety buffer, "
                    f"drone currently has {drone.current_battery_wh} Wh."
                )

        return True, "Drone is eligible and ready for deployment."

    @staticmethod
    def decommission_drone(drone_id: int) -> Drone:
        """Decommission a drone without deleting historical mission records."""
        drone = DroneService.get_drone_by_id(drone_id)

        active_assignment = DroneAssignment.query.filter_by(
            drone_id=drone.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()

        if active_assignment:
            raise DroneServiceError(
                f"Cannot decommission Drone {drone.drone_code}: active mission in progress (Assignment #{active_assignment.id})."
            )

        drone.is_decommissioned = True
        drone.status = DroneStatus.MAINTENANCE.value
        db.session.commit()
        return drone
