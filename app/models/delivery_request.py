import enum
from datetime import datetime, timezone
from app.extensions import db


class RequestPriority(str, enum.Enum):
    """Priority levels for emergency delivery requests."""
    CRITICAL = "CRITICAL"  # Life-threatening, immediate dispatch
    HIGH = "HIGH"          # Urgent, fast turnaround
    MEDIUM = "MEDIUM"      # Important, scheduled quickly
    LOW = "LOW"            # Routine transfer


class RequestStatus(str, enum.Enum):
    """Lifecycle statuses of an emergency delivery request."""
    PENDING = "PENDING"
    ROUTE_CALCULATED = "ROUTE_CALCULATED"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class EmergencyType(str, enum.Enum):
    """Categorization of emergency payloads."""
    BLOOD_SUPPLY = "BLOOD_SUPPLY"
    ANTIVENOM = "ANTIVENOM"
    DEFIBRILLATOR = "DEFIBRILLATOR"
    EMERGENCY_MEDICINE = "EMERGENCY_MEDICINE"
    SURGICAL_KIT = "SURGICAL_KIT"
    DISASTER_RELIEF = "DISASTER_RELIEF"


class DeliveryRequest(db.Model):
    """Emergency dispatch request submitted by a hospital, clinic, or emergency team."""
    __tablename__ = "delivery_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    requester_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    emergency_type = db.Column(db.String(50), nullable=False)
    pickup_latitude = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_longitude = db.Column(db.Numeric(10, 7), nullable=False)
    destination_latitude = db.Column(db.Numeric(10, 7), nullable=False)
    destination_longitude = db.Column(db.Numeric(10, 7), nullable=False)
    payload_weight_kg = db.Column(db.Numeric(6, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    priority = db.Column(
        db.String(20),
        nullable=False,
        default=RequestPriority.HIGH.value,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=RequestStatus.PENDING.value,
        index=True,
    )
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

    # Relationships
    requester = db.relationship("User", back_populates="delivery_requests")
    routes = db.relationship(
        "Route",
        back_populates="delivery_request",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    weather_snapshots = db.relationship(
        "WeatherSnapshot",
        back_populates="delivery_request",
        lazy="dynamic",
    )
    assignments = db.relationship(
        "DroneAssignment",
        back_populates="delivery_request",
        lazy="dynamic",
    )

    def __init__(
        self,
        requester_id: int,
        emergency_type: str,
        pickup_latitude: float,
        pickup_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        payload_weight_kg: float,
        priority: str = RequestPriority.HIGH.value,
        status: str = RequestStatus.PENDING.value,
        description: str = None,
    ):
        self.validate_coordinates(pickup_latitude, pickup_longitude, "Pickup")
        self.validate_coordinates(destination_latitude, destination_longitude, "Destination")

        lat1, lon1 = float(pickup_latitude), float(pickup_longitude)
        lat2, lon2 = float(destination_latitude), float(destination_longitude)
        if abs(lat1 - lat2) < 1e-6 and abs(lon1 - lon2) < 1e-6:
            raise ValueError("Pickup and destination cannot be identical locations.")

        payload_f = float(payload_weight_kg)
        if payload_f <= 0:
            raise ValueError("Payload weight must be strictly positive.")
        if payload_f > 100.0:
            raise ValueError("Payload weight exceeds maximum supported emergency drone payload (100.0 kg).")

        self.requester_id = requester_id
        self.emergency_type = emergency_type.value if isinstance(emergency_type, EmergencyType) else str(emergency_type)
        self.pickup_latitude = pickup_latitude
        self.pickup_longitude = pickup_longitude
        self.destination_latitude = destination_latitude
        self.destination_longitude = destination_longitude
        self.payload_weight_kg = payload_weight_kg
        self.priority = priority.value if isinstance(priority, RequestPriority) else str(priority).upper()
        self.status = status.value if isinstance(status, RequestStatus) else str(status).upper()
        self.description = description.strip() if description else None

    @staticmethod
    def validate_coordinates(lat: float, lng: float, label: str = "Coordinate") -> None:
        """Validate WGS84 latitude (-90 to +90) and longitude (-180 to +180)."""
        lat_f = float(lat)
        lng_f = float(lng)
        if not (-90.0 <= lat_f <= 90.0):
            raise ValueError(f"{label} latitude must be between -90.0 and +90.0 degrees.")
        if not (-180.0 <= lng_f <= 180.0):
            raise ValueError(f"{label} longitude must be between -180.0 and +180.0 degrees.")

    def to_dict(self) -> dict:
        """Serialize delivery request to dictionary."""
        return {
            "id": self.id,
            "requester_id": self.requester_id,
            "emergency_type": self.emergency_type,
            "pickup": {
                "latitude": float(self.pickup_latitude),
                "longitude": float(self.pickup_longitude),
            },
            "destination": {
                "latitude": float(self.destination_latitude),
                "longitude": float(self.destination_longitude),
            },
            "payload_weight_kg": float(self.payload_weight_kg),
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<DeliveryRequest id={self.id} type={self.emergency_type} priority={self.priority} status={self.status}>"
