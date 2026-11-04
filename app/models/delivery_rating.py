"""Post-delivery customer rating and experience feedback model."""

from datetime import datetime, timezone
from app.extensions import db


class DeliveryRating(db.Model):
    """Customer experience ratings and service feedback collected after delivery completion."""
    __tablename__ = "delivery_ratings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5 stars
    feedback_text = db.Column(db.Text, nullable=True)
    booking_experience_score = db.Column(db.Integer, nullable=True)
    speed_score = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    booking = db.relationship(
        "DroneBooking",
        backref=db.backref("rating", uselist=False, cascade="all, delete-orphan"),
    )
    user = db.relationship(
        "User",
        backref=db.backref("ratings", lazy="dynamic"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "user_id": self.user_id,
            "rating": self.rating,
            "feedback_text": self.feedback_text,
            "booking_experience_score": self.booking_experience_score,
            "speed_score": self.speed_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
