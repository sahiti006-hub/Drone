import enum
import uuid
from datetime import datetime, timezone
from app.extensions import db


class RequestPriority(str, enum.Enum):
    """Priority levels for delivery requests."""
    CRITICAL = "CRITICAL"  # Life-threatening, immediate dispatch
    HIGH = "HIGH"          # Urgent, fast turnaround
    MEDIUM = "MEDIUM"      # Important, scheduled quickly
    LOW = "LOW"            # Routine transfer


class RequestStatus(str, enum.Enum):
    """Comprehensive lifecycle statuses for delivery requests."""
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    DRONE_ASSIGNED = "DRONE_ASSIGNED"
    PENDING = "PENDING"                  # Maintained for backwards compatibility
    ROUTE_CALCULATED = "ROUTE_CALCULATED" # Maintained for backwards compatibility
    ASSIGNED = "ASSIGNED"                # Maintained for backwards compatibility
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    APPROACHING = "APPROACHING"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    WEATHER_HOLD = "WEATHER_HOLD"
    REROUTED = "REROUTED"
    DIVERTED = "DIVERTED"
    EMERGENCY_REVIEW = "EMERGENCY_REVIEW"


class EmergencyType(str, enum.Enum):
    """Legacy medical and emergency payload categories (maintained for backwards compatibility)."""
    BLOOD_SUPPLY = "BLOOD_SUPPLY"
    ANTIVENOM = "ANTIVENOM"
    DEFIBRILLATOR = "DEFIBRILLATOR"
    EMERGENCY_MEDICINE = "EMERGENCY_MEDICINE"
    SURGICAL_KIT = "SURGICAL_KIT"
    DISASTER_RELIEF = "DISASTER_RELIEF"


class CargoCategory(str, enum.Enum):
    """Universal multipurpose cargo categories across all operational sectors."""
    MEDICAL_HEALTHCARE = "MEDICAL_HEALTHCARE"
    FOOD_GROCERIES = "FOOD_GROCERIES"
    DOCUMENTS_OFFICE = "DOCUMENTS_OFFICE"
    ELECTRONICS_TECH = "ELECTRONICS_TECH"
    INDUSTRIAL_SUPPLIES = "INDUSTRIAL_SUPPLIES"
    EMERGENCY_RELIEF = "EMERGENCY_RELIEF"
    PERSONAL_HOUSEHOLD = "PERSONAL_HOUSEHOLD"
    AGRICULTURE_RURAL = "AGRICULTURE_RURAL"
    CUSTOM_DELIVERY = "CUSTOM_DELIVERY"


# Extensible Category Registry with UI metadata and safety rules
CARGO_CATEGORY_REGISTRY = {
    "MEDICAL_HEALTHCARE": {
        "code": "MEDICAL_HEALTHCARE",
        "name": "Medical & Healthcare",
        "icon": "🩺",
        "description": "Blood supplies, medicines, vaccines, diagnostic samples, medical kits",
        "max_weight_kg": 5.0,
        "requires_temperature_control": True,
        "safety_notes": "Temperature-controlled medical container with shock dampening.",
    },
    "FOOD_GROCERIES": {
        "code": "FOOD_GROCERIES",
        "name": "Food & Groceries",
        "icon": "🍎",
        "description": "Food packages, fresh groceries, drinking water, essential provisions",
        "max_weight_kg": 5.0,
        "requires_temperature_control": False,
        "safety_notes": "Insulated food-safe compartment with leak protection.",
    },
    "DOCUMENTS_OFFICE": {
        "code": "DOCUMENTS_OFFICE",
        "name": "Documents & Office Deliveries",
        "icon": "📄",
        "description": "Official legal documents, contracts, certificates, office materials",
        "max_weight_kg": 2.0,
        "requires_temperature_control": False,
        "safety_notes": "Waterproof, tamper-evident sealed security pouch.",
    },
    "ELECTRONICS_TECH": {
        "code": "ELECTRONICS_TECH",
        "name": "Electronics & Technology",
        "icon": "💻",
        "description": "Mobile phones, electronic components, accessories, small gadgets",
        "max_weight_kg": 4.5,
        "requires_temperature_control": False,
        "safety_notes": "Padded anti-static enclosure with impact mitigation.",
    },
    "INDUSTRIAL_SUPPLIES": {
        "code": "INDUSTRIAL_SUPPLIES",
        "name": "Industrial & Business Supplies",
        "icon": "⚙️",
        "description": "Critical spare parts, small tools, hardware, manufacturing components",
        "max_weight_kg": 6.0,
        "requires_temperature_control": False,
        "safety_notes": "Rigid reinforced container with magnetic locking.",
    },
    "EMERGENCY_RELIEF": {
        "code": "EMERGENCY_RELIEF",
        "name": "Emergency & Disaster Relief",
        "icon": "🦺",
        "description": "Rescue supplies, emergency AED, survival kits, disaster relief items",
        "max_weight_kg": 5.0,
        "requires_temperature_control": False,
        "safety_notes": "High-visibility emergency deployment pod with beacon.",
    },
    "PERSONAL_HOUSEHOLD": {
        "code": "PERSONAL_HOUSEHOLD",
        "name": "Personal & Household Items",
        "icon": "👕",
        "description": "Clothing, personal belongings, household essentials, packages",
        "max_weight_kg": 4.0,
        "requires_temperature_control": False,
        "safety_notes": "Standard secure weather-resistant utility pod.",
    },
    "AGRICULTURE_RURAL": {
        "code": "AGRICULTURE_RURAL",
        "name": "Agriculture & Rural Supplies",
        "icon": "🌾",
        "description": "Seeds, agricultural tools, permitted farm supplies, equipment",
        "max_weight_kg": 5.5,
        "requires_temperature_control": False,
        "safety_notes": "Sealed agricultural transport container.",
    },
    "CUSTOM_DELIVERY": {
        "code": "CUSTOM_DELIVERY",
        "name": "Custom Delivery",
        "icon": "📦",
        "description": "Customized general-purpose delivery for any specific item or requirement",
        "max_weight_kg": 6.0,
        "requires_temperature_control": False,
        "safety_notes": "Verified custom cargo container subject to pre-flight safety check.",
    },
}

# Legacy category alias mapping
LEGACY_CATEGORY_MAP = {
    "BLOOD_SUPPLY": "MEDICAL_HEALTHCARE",
    "ANTIVENOM": "MEDICAL_HEALTHCARE",
    "EMERGENCY_MEDICINE": "MEDICAL_HEALTHCARE",
    "SURGICAL_KIT": "MEDICAL_HEALTHCARE",
    "DEFIBRILLATOR": "EMERGENCY_RELIEF",
    "DISASTER_RELIEF": "EMERGENCY_RELIEF",
    "FOOD_ESSENTIALS": "FOOD_GROCERIES",
    "DOCUMENTS_PARCELS": "DOCUMENTS_OFFICE",
    "ELECTRONICS": "ELECTRONICS_TECH",
    "CUSTOM_ITEM": "CUSTOM_DELIVERY",
}


def normalize_cargo_category(category_name: str) -> str:
    """Normalize any category code or legacy alias to the standardized category code."""
    if not category_name:
        return CargoCategory.CUSTOM_DELIVERY.value
    raw = str(category_name).strip().upper()
    if raw in CARGO_CATEGORY_REGISTRY:
        return raw
    if raw in LEGACY_CATEGORY_MAP:
        return LEGACY_CATEGORY_MAP[raw]
    return raw


class DeliveryRequest(db.Model):
    """Central delivery request entity supporting universal multipurpose drone deliveries."""
    __tablename__ = "delivery_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    request_reference = db.Column(
        db.String(64),
        unique=True,
        index=True,
        nullable=True,
        default=lambda: f"REQ-{uuid.uuid4().hex[:10].upper()}",
    )
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
    delivery_direction = db.Column(
        db.String(20),
        nullable=False,
        default="SEND",
        server_default="SEND",
        index=True,
    )
    description = db.Column(db.String(255), nullable=True)
    priority = db.Column(
        db.String(20),
        nullable=False,
        default=RequestPriority.HIGH.value,
        index=True,
    )
    status = db.Column(
        db.String(30),
        nullable=False,
        default=RequestStatus.PENDING.value,
        index=True,
    )

    # Universal & Custom Cargo Attributes
    custom_item_name = db.Column(db.String(150), nullable=True)
    package_dimensions = db.Column(db.String(50), nullable=True)
    package_count = db.Column(db.Integer, nullable=True, default=1)
    handling_instructions = db.Column(db.String(255), nullable=True)
    pickup_contact_name = db.Column(db.String(100), nullable=True)
    pickup_contact_phone = db.Column(db.String(50), nullable=True)
    delivery_contact_name = db.Column(db.String(100), nullable=True)
    delivery_contact_phone = db.Column(db.String(50), nullable=True)
    special_instructions = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
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
    activities = db.relationship(
        "RequestActivity",
        backref="delivery_request",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="RequestActivity.created_at.asc()",
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
        delivery_direction: str = "SEND",
        request_reference: str = None,
        custom_item_name: str = None,
        package_dimensions: str = None,
        package_count: int = 1,
        handling_instructions: str = None,
        pickup_contact_name: str = None,
        pickup_contact_phone: str = None,
        delivery_contact_name: str = None,
        delivery_contact_phone: str = None,
        special_instructions: str = None,
        rejection_reason: str = None,
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
        self.emergency_type = emergency_type.value if isinstance(emergency_type, (EmergencyType, CargoCategory)) else str(emergency_type)
        self.pickup_latitude = pickup_latitude
        self.pickup_longitude = pickup_longitude
        self.destination_latitude = destination_latitude
        self.destination_longitude = destination_longitude
        self.payload_weight_kg = payload_weight_kg
        self.priority = priority.value if isinstance(priority, RequestPriority) else str(priority).upper()
        self.status = status.value if isinstance(status, RequestStatus) else str(status).upper()
        self.description = description.strip() if description else None
        self.delivery_direction = (delivery_direction or "SEND").upper()
        self.request_reference = request_reference or f"REQ-{uuid.uuid4().hex[:10].upper()}"
        self.custom_item_name = custom_item_name.strip() if custom_item_name else None
        self.package_dimensions = package_dimensions
        self.package_count = int(package_count or 1)
        self.handling_instructions = handling_instructions
        self.pickup_contact_name = pickup_contact_name
        self.pickup_contact_phone = pickup_contact_phone
        self.delivery_contact_name = delivery_contact_name
        self.delivery_contact_phone = delivery_contact_phone
        self.special_instructions = special_instructions
        self.rejection_reason = rejection_reason

    @property
    def display_reference(self) -> str:
        """Formatted user-friendly reference identifier."""
        return self.request_reference or f"REQ-{self.id:06d}"

    @property
    def cargo_category(self) -> str:
        """Standardized universal category code."""
        return self.cargo_category_meta["code"]

    @property
    def cargo_category_meta(self) -> dict:
        """Retrieve rich category metadata from registry."""
        norm = normalize_cargo_category(self.emergency_type)
        return CARGO_CATEGORY_REGISTRY.get(norm, CARGO_CATEGORY_REGISTRY["CUSTOM_DELIVERY"])

    @property
    def user_friendly_status(self) -> str:
        """Translates internal status enum to customer-friendly wording."""
        labels = {
            "SUBMITTED": "Request Submitted",
            "PENDING": "Pending Review",
            "UNDER_REVIEW": "Under Review",
            "APPROVED": "Approved",
            "ROUTE_CALCULATED": "Corridor Ready",
            "QUOTED": "Price Quoted",
            "CONFIRMED": "Booking Confirmed",
            "ASSIGNED": "Drone Assigned",
            "DRONE_ASSIGNED": "Drone Assigned",
            "DISPATCHED": "Dispatched",
            "IN_TRANSIT": "In Flight",
            "APPROACHING": "Approaching Destination",
            "ARRIVED": "Arrived at Site",
            "DELIVERED": "Successfully Delivered",
            "CANCELLED": "Cancelled",
            "REJECTED": "Rejected",
            "WEATHER_HOLD": "Weather Hold",
            "REROUTED": "Weather Rerouted",
            "DIVERTED": "Diverted to Safety",
            "EMERGENCY_REVIEW": "Safety Review",
        }
        return labels.get(self.status, self.status.replace("_", " ").title())

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
            "request_reference": self.display_reference,
            "requester_id": self.requester_id,
            "emergency_type": self.emergency_type,
            "cargo_category": self.cargo_category_meta["code"],
            "cargo_category_name": self.cargo_category_meta["name"],
            "cargo_category_icon": self.cargo_category_meta["icon"],
            "custom_item_name": self.custom_item_name,
            "pickup": {
                "latitude": float(self.pickup_latitude),
                "longitude": float(self.pickup_longitude),
                "contact_name": self.pickup_contact_name,
                "contact_phone": self.pickup_contact_phone,
            },
            "destination": {
                "latitude": float(self.destination_latitude),
                "longitude": float(self.destination_longitude),
                "contact_name": self.delivery_contact_name,
                "contact_phone": self.delivery_contact_phone,
            },
            "payload_weight_kg": float(self.payload_weight_kg),
            "package_dimensions": self.package_dimensions,
            "package_count": self.package_count,
            "delivery_direction": getattr(self, "delivery_direction", "SEND") or "SEND",
            "description": self.description,
            "handling_instructions": self.handling_instructions,
            "special_instructions": self.special_instructions,
            "priority": self.priority,
            "status": self.status,
            "status_label": self.user_friendly_status,
            "rejection_reason": self.rejection_reason,
            "activity_count": self.activities.count() if hasattr(self, "activities") else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<DeliveryRequest id={self.id} ref={self.display_reference} type={self.emergency_type} status={self.status}>"
