import enum
from datetime import datetime, timezone
from app.extensions import db


class DroneStatus(str, enum.Enum):
    """Explicit operational statuses for emergency delivery drones."""
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_TRANSIT = "IN_TRANSIT"
    CHARGING = "CHARGING"
    MAINTENANCE = "MAINTENANCE"


# State transition rules: Map current status -> Set of valid next statuses
ALLOWED_DRONE_TRANSITIONS = {
    DroneStatus.AVAILABLE: {DroneStatus.RESERVED, DroneStatus.MAINTENANCE, DroneStatus.CHARGING},
    DroneStatus.RESERVED: {DroneStatus.IN_TRANSIT, DroneStatus.AVAILABLE, DroneStatus.MAINTENANCE},
    DroneStatus.IN_TRANSIT: {DroneStatus.AVAILABLE, DroneStatus.CHARGING, DroneStatus.MAINTENANCE},
    DroneStatus.CHARGING: {DroneStatus.AVAILABLE, DroneStatus.MAINTENANCE},
    DroneStatus.MAINTENANCE: {DroneStatus.AVAILABLE, DroneStatus.CHARGING},
}


class Drone(db.Model):
    """Drone hardware unit tracking battery, payload, and operational status."""
    __tablename__ = "drones"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    drone_code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    model_name = db.Column(db.String(100), nullable=False)
    maximum_payload_kg = db.Column(db.Numeric(6, 2), nullable=False)
    battery_capacity_wh = db.Column(db.Numeric(8, 2), nullable=False)
    current_battery_wh = db.Column(db.Numeric(8, 2), nullable=False)
    cruise_speed_kmh = db.Column(db.Numeric(6, 2), nullable=False, default=60.00)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=DroneStatus.AVAILABLE.value,
        index=True,
    )
    is_decommissioned = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship to assignments (history preserved; do not cascade delete)
    assignments = db.relationship(
        "DroneAssignment",
        back_populates="drone",
        lazy="dynamic",
        passive_deletes=False,
    )

    def __init__(
        self,
        drone_code: str,
        model_name: str,
        maximum_payload_kg: float,
        battery_capacity_wh: float,
        current_battery_wh: float = None,
        cruise_speed_kmh: float = 60.0,
        status: str = DroneStatus.AVAILABLE.value,
    ):
        if float(maximum_payload_kg) <= 0:
            raise ValueError("Maximum payload must be greater than zero.")
        if float(battery_capacity_wh) <= 0:
            raise ValueError("Battery capacity must be greater than zero.")

        initial_battery = float(current_battery_wh) if current_battery_wh is not None else float(battery_capacity_wh)
        if initial_battery < 0 or initial_battery > float(battery_capacity_wh):
            raise ValueError("Current battery must be between 0 and maximum battery capacity.")

        self.drone_code = drone_code.strip().upper()
        self.model_name = model_name.strip()
        self.maximum_payload_kg = maximum_payload_kg
        self.battery_capacity_wh = battery_capacity_wh
        self.current_battery_wh = initial_battery
        self.cruise_speed_kmh = cruise_speed_kmh
        self.status = status.value if isinstance(status, DroneStatus) else str(status).upper()

    @property
    def battery_percentage(self) -> float:
        """Calculate current battery percentage."""
        if not self.battery_capacity_wh or float(self.battery_capacity_wh) == 0:
            return 0.0
        return round((float(self.current_battery_wh) / float(self.battery_capacity_wh)) * 100.0, 2)

    def can_transition_to(self, target_status: str | DroneStatus) -> bool:
        """Validate whether the requested status transition conforms to state machine rules."""
        target = target_status if isinstance(target_status, DroneStatus) else DroneStatus(target_status)
        current = DroneStatus(self.status)
        return target in ALLOWED_DRONE_TRANSITIONS.get(current, set())

    def to_dict(self) -> dict:
        """Serialize drone model to dictionary."""
        return {
            "id": self.id,
            "drone_code": self.drone_code,
            "model_name": self.model_name,
            "maximum_payload_kg": float(self.maximum_payload_kg),
            "battery_capacity_wh": float(self.battery_capacity_wh),
            "current_battery_wh": float(self.current_battery_wh),
            "battery_percentage": self.battery_percentage,
            "cruise_speed_kmh": float(self.cruise_speed_kmh),
            "status": self.status,
            "is_decommissioned": self.is_decommissioned,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Drone code={self.drone_code} status={self.status} battery={self.battery_percentage}%>"
