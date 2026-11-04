"""Request activity and status audit entity."""

import json
from datetime import datetime, timezone
from app.extensions import db


class RequestActivity(db.Model):
    """Immutable audit trail for delivery request and booking lifecycle events."""
    __tablename__ = "request_activities"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_role = db.Column(db.String(30), nullable=True)
    from_status = db.Column(db.String(50), nullable=True)
    to_status = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    actor = db.relationship("User", backref=db.backref("activities_performed", lazy="dynamic"))

    def __init__(
        self,
        delivery_request_id: int,
        to_status: str,
        action: str,
        booking_id: int = None,
        actor_id: int = None,
        actor_role: str = None,
        from_status: str = None,
        reason: str = None,
        metadata: dict = None,
    ):
        self.delivery_request_id = delivery_request_id
        self.booking_id = booking_id
        self.actor_id = actor_id
        self.actor_role = actor_role
        self.from_status = from_status
        self.to_status = to_status
        self.action = action
        self.reason = reason
        self.metadata_json = json.dumps(metadata) if isinstance(metadata, dict) else (metadata or None)

    def get_metadata(self) -> dict:
        """Parse metadata JSON."""
        return json.loads(self.metadata_json) if self.metadata_json else {}

    def to_dict(self) -> dict:
        """Serialize activity record to dictionary."""
        return {
            "id": self.id,
            "delivery_request_id": self.delivery_request_id,
            "booking_id": self.booking_id,
            "actor_id": self.actor_id,
            "actor_name": self.actor.full_name if self.actor else "System",
            "actor_role": self.actor_role or (self.actor.role if self.actor else "SYSTEM"),
            "from_status": self.from_status,
            "to_status": self.to_status,
            "action": self.action,
            "reason": self.reason,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<RequestActivity id={self.id} req={self.delivery_request_id} action={self.action} to={self.to_status}>"
