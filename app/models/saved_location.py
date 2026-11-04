"""User saved delivery locations model."""

from datetime import datetime, timezone
from app.extensions import db


class SavedLocation(db.Model):
    """Frequent or saved delivery coordinates for rapid one-click booking."""
    __tablename__ = "saved_locations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = db.Column(db.String(100), nullable=False)
    location_type = db.Column(db.String(30), nullable=False, default="HOSPITAL")
    address = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.Numeric(10, 7), nullable=False)
    longitude = db.Column(db.Numeric(10, 7), nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship(
        "User",
        backref=db.backref("saved_locations", lazy="dynamic", cascade="all, delete-orphan"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "label": self.label,
            "location_type": self.location_type,
            "address": self.address,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
