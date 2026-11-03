"""Comprehensive Uber/Rapido-style drone booking lifecycle model."""

import enum
from datetime import datetime, timezone
import uuid
from app.extensions import db


class BookingStatus(str, enum.Enum):
    """Lifecycle statuses for requester drone bookings."""
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    DISPATCHED = "DISPATCHED"
    IN_FLIGHT = "IN_FLIGHT"
    WEATHER_CAUTION = "WEATHER_CAUTION"
    REROUTED = "REROUTED"
    DIVERTED = "DIVERTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    WEATHER_BLOCKED = "WEATHER_BLOCKED"
    EMERGENCY_REVIEW = "EMERGENCY_REVIEW"


class DroneBooking(db.Model):
    """Central booking transaction tying requester, drone, quote, delivery, and payments."""
    __tablename__ = "drone_bookings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    booking_reference = db.Column(
        db.String(64),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: f"BKG-{uuid.uuid4().hex[:10].upper()}",
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
    quote_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_quotes.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default=BookingStatus.DRAFT.value,
        index=True,
    )
    
    # Financial snapshots
    accepted_price = db.Column(db.Numeric(10, 2), nullable=False)
    final_price = db.Column(db.Numeric(10, 2), nullable=False)

    # Weather safety audit fields
    weather_condition_at_booking = db.Column(db.String(50), nullable=False, default="GREEN")
    weather_acknowledged_by_user = db.Column(db.Boolean, default=False, nullable=False)
    weather_block_reason = db.Column(db.String(255), nullable=True)

    notes = db.Column(db.Text, nullable=True)
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
    requester = db.relationship("User", backref=db.backref("bookings", lazy="dynamic"))
    drone = db.relationship("Drone", backref=db.backref("bookings", lazy="dynamic"))
    quote = db.relationship("DroneQuote", back_populates="booking")
    delivery_request = db.relationship(
        "DeliveryRequest",
        backref=db.backref("booking", uselist=False),
    )
    payment_transactions = db.relationship(
        "PaymentTransaction",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    refund_transactions = db.relationship(
        "RefundTransaction",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    weather_alerts = db.relationship(
        "WeatherAlert",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def latest_payment(self):
        """Fetch latest payment transaction."""
        from app.models.payment_transaction import PaymentTransaction
        return self.payment_transactions.order_by(
            PaymentTransaction.created_at.desc()
        ).first()

    def to_dict(self) -> dict:
        latest_pay = self.latest_payment
        return {
            "id": self.id,
            "booking_reference": self.booking_reference,
            "requester_id": self.requester_id,
            "drone_id": self.drone_id,
            "drone_code": self.drone.drone_code if self.drone else None,
            "drone_model": self.drone.model_name if self.drone else None,
            "quote_id": self.quote_id,
            "delivery_request_id": self.delivery_request_id,
            "status": self.status,
            "accepted_price": float(self.accepted_price),
            "final_price": float(self.final_price),
            "weather_condition_at_booking": self.weather_condition_at_booking,
            "weather_acknowledged_by_user": self.weather_acknowledged_by_user,
            "weather_block_reason": self.weather_block_reason,
            "payment_status": latest_pay.payment_status if latest_pay else "UNPAID",
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "quote": self.quote.to_dict() if self.quote else None,
        }
