"""In-app notification system across Requester, Operator, and Admin dashboards."""

import enum
from datetime import datetime, timezone
from app.extensions import db


class NotificationType(str, enum.Enum):
    DRONE_SEARCH = "DRONE_SEARCH"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    PAYMENT_FAILURE = "PAYMENT_FAILURE"
    WEATHER_WARNING = "WEATHER_WARNING"
    WEATHER_DETERIORATION = "WEATHER_DETERIORATION"
    DYNAMIC_REROUTING = "DYNAMIC_REROUTING"
    DELIVERY_DELAY = "DELIVERY_DELAY"
    EMERGENCY_DIVERSION = "EMERGENCY_DIVERSION"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    REFUND_INITIATED = "REFUND_INITIATED"
    REFUND_COMPLETED = "REFUND_COMPLETED"


class Notification(db.Model):
    """In-app alert persisted for users or operational roles."""
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_role = db.Column(db.String(20), nullable=True, index=True)  # ADMIN, OPERATOR, REQUESTER, or None (user-specific)
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_type = db.Column(
        db.String(40),
        nullable=False,
        default=NotificationType.BOOKING_CONFIRMED.value,
        index=True,
    )
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="INFO")  # INFO, WARNING, SUCCESS, DANGER
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship("User", backref=db.backref("notifications", lazy="dynamic"))
    booking = db.relationship("DroneBooking", back_populates="notifications")
    delivery_request = db.relationship("DeliveryRequest")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "target_role": self.target_role,
            "booking_id": self.booking_id,
            "delivery_request_id": self.delivery_request_id,
            "notification_type": self.notification_type,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
