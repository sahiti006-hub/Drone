"""Configurable pricing rules and financial fee parameters."""

from datetime import datetime, timezone
from app.extensions import db


class PricingConfiguration(db.Model):
    """Admin-controlled fee rules for drone delivery calculation."""
    __tablename__ = "pricing_configurations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False, default="DEFAULT", unique=True)
    base_fare = db.Column(db.Numeric(10, 2), nullable=False, default=100.00)
    price_per_km = db.Column(db.Numeric(10, 2), nullable=False, default=25.00)
    price_per_kg = db.Column(db.Numeric(10, 2), nullable=False, default=15.00)
    
    # Priority charges
    priority_charge_critical = db.Column(db.Numeric(10, 2), nullable=False, default=150.00)
    priority_charge_high = db.Column(db.Numeric(10, 2), nullable=False, default=80.00)
    priority_charge_medium = db.Column(db.Numeric(10, 2), nullable=False, default=40.00)
    priority_charge_low = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)

    # Service fee and boundaries
    service_fee = db.Column(db.Numeric(10, 2), nullable=False, default=30.00)
    minimum_fare = db.Column(db.Numeric(10, 2), nullable=False, default=150.00)
    maximum_fare = db.Column(db.Numeric(10, 2), nullable=False, default=5000.00)
    tax_rate_percent = db.Column(db.Numeric(5, 2), nullable=False, default=5.00)

    # Time-to-live and cancellation policy
    quote_ttl_minutes = db.Column(db.Integer, nullable=False, default=15)
    cancellation_fee_fixed = db.Column(db.Numeric(10, 2), nullable=False, default=50.00)
    cancellation_fee_percent = db.Column(db.Numeric(5, 2), nullable=False, default=10.00)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "base_fare": float(self.base_fare),
            "price_per_km": float(self.price_per_km),
            "price_per_kg": float(self.price_per_kg),
            "priority_charges": {
                "CRITICAL": float(self.priority_charge_critical),
                "HIGH": float(self.priority_charge_high),
                "MEDIUM": float(self.priority_charge_medium),
                "LOW": float(self.priority_charge_low),
            },
            "service_fee": float(self.service_fee),
            "minimum_fare": float(self.minimum_fare),
            "maximum_fare": float(self.maximum_fare),
            "tax_rate_percent": float(self.tax_rate_percent),
            "quote_ttl_minutes": self.quote_ttl_minutes,
            "cancellation_fee_fixed": float(self.cancellation_fee_fixed),
            "cancellation_fee_percent": float(self.cancellation_fee_percent),
            "is_active": self.is_active,
        }
