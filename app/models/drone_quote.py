"""Persisted delivery quote for price stability, transparency, and auditing."""

from datetime import datetime, timezone
import uuid
from app.extensions import db


class DroneQuote(db.Model):
    """Immutable snapshot of estimated flight distance, duration, energy, and charges."""
    __tablename__ = "drone_quotes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quote_reference = db.Column(
        db.String(64),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: f"QUO-{uuid.uuid4().hex[:10].upper()}",
    )
    requester_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    drone_id = db.Column(
        db.Integer,
        db.ForeignKey("drones.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    pricing_config_id = db.Column(
        db.Integer,
        db.ForeignKey("pricing_configurations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Mission spatial and payload parameters
    pickup_latitude = db.Column(db.Numeric(10, 7), nullable=False)
    pickup_longitude = db.Column(db.Numeric(10, 7), nullable=False)
    destination_latitude = db.Column(db.Numeric(10, 7), nullable=False)
    destination_longitude = db.Column(db.Numeric(10, 7), nullable=False)
    cargo_weight_kg = db.Column(db.Numeric(6, 2), nullable=False)
    cargo_category = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False)
    delivery_direction = db.Column(db.String(20), nullable=False, default="SEND", server_default="SEND")
    custom_item_name = db.Column(db.String(150), nullable=True)
    package_size = db.Column(db.String(30), nullable=True, default="SMALL")

    # Evaluated route performance
    corridor_name = db.Column(db.String(100), nullable=False)
    flight_distance_km = db.Column(db.Numeric(8, 3), nullable=False)
    ferry_distance_km = db.Column(db.Numeric(8, 3), nullable=False, default=0.0)
    estimated_pickup_duration_min = db.Column(db.Numeric(6, 2), nullable=False, default=2.0)
    estimated_delivery_duration_min = db.Column(db.Numeric(6, 2), nullable=False)
    estimated_energy_wh = db.Column(db.Numeric(8, 2), nullable=False)
    weather_classification = db.Column(db.String(20), nullable=False, default="GREEN")

    # Itemized price breakdown
    base_fare = db.Column(db.Numeric(10, 2), nullable=False)
    distance_charge = db.Column(db.Numeric(10, 2), nullable=False)
    weight_charge = db.Column(db.Numeric(10, 2), nullable=False)
    priority_charge = db.Column(db.Numeric(10, 2), nullable=False)
    service_fee = db.Column(db.Numeric(10, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)

    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    is_accepted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    requester = db.relationship("User", backref=db.backref("quotes", lazy="dynamic"))
    drone = db.relationship("Drone", backref=db.backref("quotes", lazy="dynamic"))
    pricing_config = db.relationship("PricingConfiguration")
    booking = db.relationship("DroneBooking", back_populates="quote", uselist=False)

    @property
    def distance_km(self) -> float:
        """Alias for flight_distance_km."""
        return float(self.flight_distance_km) if self.flight_distance_km is not None else 0.0

    @property
    def weight_kg(self) -> float:
        """Alias for cargo_weight_kg."""
        return float(self.cargo_weight_kg) if self.cargo_weight_kg is not None else 0.0

    @property
    def priority_fee(self) -> float:
        """Alias for priority_charge."""
        return float(self.priority_charge) if self.priority_charge is not None else 0.0

    @property
    def tax_rate_percent(self) -> float:
        """Tax percentage rate from configuration or standard 18%."""
        if self.pricing_config and hasattr(self.pricing_config, "tax_rate_percent"):
            return float(self.pricing_config.tax_rate_percent)
        return 18.0

    def is_expired(self) -> bool:
        """Verify whether quote has exceeded its time-to-live."""
        if not self.expires_at:
            return True
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "quote_reference": self.quote_reference,
            "drone_id": self.drone_id,
            "drone_code": self.drone.drone_code if self.drone else None,
            "drone_model": self.drone.model_name if self.drone else None,
            "pickup": {"lat": float(self.pickup_latitude), "lng": float(self.pickup_longitude)},
            "destination": {"lat": float(self.destination_latitude), "lng": float(self.destination_longitude)},
            "cargo_weight_kg": float(self.cargo_weight_kg),
            "cargo_category": self.cargo_category,
            "priority": self.priority,
            "delivery_direction": self.delivery_direction or "SEND",
            "custom_item_name": self.custom_item_name,
            "package_size": self.package_size or "SMALL",
            "corridor_name": self.corridor_name,
            "flight_distance_km": float(self.flight_distance_km),
            "ferry_distance_km": float(self.ferry_distance_km),
            "estimated_pickup_duration_min": float(self.estimated_pickup_duration_min),
            "estimated_delivery_duration_min": float(self.estimated_delivery_duration_min),
            "estimated_energy_wh": float(self.estimated_energy_wh),
            "weather_classification": self.weather_classification,
            "price_breakdown": {
                "base_fare": float(self.base_fare),
                "distance_charge": float(self.distance_charge),
                "weight_charge": float(self.weight_charge),
                "priority_charge": float(self.priority_charge),
                "service_fee": float(self.service_fee),
                "tax_amount": float(self.tax_amount),
                "total_price": float(self.total_price),
            },
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_expired": self.is_expired(),
            "is_accepted": self.is_accepted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
