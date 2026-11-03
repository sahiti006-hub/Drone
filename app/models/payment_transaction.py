"""Financial ledger models for simulated payments, idempotency, and refunds."""

import enum
from datetime import datetime, timezone
import uuid
from app.extensions import db


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    UNDER_REVIEW = "UNDER_REVIEW"


class PaymentMethod(str, enum.Enum):
    SIMULATED_WALLET = "SIMULATED_WALLET"
    SIMULATED_UPI = "SIMULATED_UPI"
    SIMULATED_CARD = "SIMULATED_CARD"
    SIMULATED_NETBANKING = "SIMULATED_NETBANKING"


class PaymentTransaction(db.Model):
    """Simulated payment transaction ledger with idempotency controls."""
    __tablename__ = "payment_transactions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    transaction_reference = db.Column(
        db.String(64),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: f"TXN-{uuid.uuid4().hex[:12].upper()}",
    )
    idempotency_key = db.Column(db.String(64), unique=True, index=True, nullable=False)
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    quoted_amount = db.Column(db.Numeric(10, 2), nullable=False)
    final_amount = db.Column(db.Numeric(10, 2), nullable=False)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    payment_method = db.Column(
        db.String(30),
        nullable=False,
        default=PaymentMethod.SIMULATED_UPI.value,
    )
    payment_status = db.Column(
        db.String(30),
        nullable=False,
        default=PaymentStatus.PENDING.value,
        index=True,
    )
    gateway_response_code = db.Column(db.String(50), nullable=True)
    reason_for_adjustment = db.Column(db.String(255), nullable=True)
    
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    refunded_at = db.Column(db.DateTime(timezone=True), nullable=True)
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
    booking = db.relationship("DroneBooking", back_populates="payment_transactions")
    delivery_request = db.relationship("DeliveryRequest")
    requester = db.relationship("User")
    refunds = db.relationship("RefundTransaction", back_populates="payment_transaction", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "transaction_reference": self.transaction_reference,
            "idempotency_key": self.idempotency_key,
            "booking_id": self.booking_id,
            "delivery_request_id": self.delivery_request_id,
            "requester_id": self.requester_id,
            "quoted_amount": float(self.quoted_amount),
            "final_amount": float(self.final_amount),
            "refund_amount": float(self.refund_amount),
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "gateway_response_code": self.gateway_response_code,
            "reason_for_adjustment": self.reason_for_adjustment,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "refunded_at": self.refunded_at.isoformat() if self.refunded_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RefundTransaction(db.Model):
    """Detailed record of full, partial, or weather-induced refunds."""
    __tablename__ = "refund_transactions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    refund_reference = db.Column(
        db.String(64),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: f"REF-{uuid.uuid4().hex[:12].upper()}",
    )
    payment_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("payment_transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    refund_type = db.Column(db.String(30), nullable=False)  # FULL, PARTIAL, WEATHER_CANCEL, DIVERSION_COMPENSATION
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="COMPLETED")
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    payment_transaction = db.relationship("PaymentTransaction", back_populates="refunds")
    booking = db.relationship("DroneBooking", back_populates="refund_transactions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "refund_reference": self.refund_reference,
            "payment_transaction_id": self.payment_transaction_id,
            "booking_id": self.booking_id,
            "amount": float(self.amount),
            "refund_type": self.refund_type,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
