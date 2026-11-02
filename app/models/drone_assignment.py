import enum
from datetime import datetime, timezone
from app.extensions import db


class AssignmentStatus(str, enum.Enum):
    """Execution status of a drone delivery assignment."""
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class DroneAssignment(db.Model):
    """Operational dispatch associating a drone, delivery request, and route."""
    __tablename__ = "drone_assignments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    drone_id = db.Column(
        db.Integer,
        db.ForeignKey("drones.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    route_id = db.Column(
        db.Integer,
        db.ForeignKey("routes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=AssignmentStatus.ACTIVE.value,
        index=True,
    )
    assigned_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Composite index to optimize lookups for active drone assignments
    __table_args__ = (
        db.Index("idx_active_drone_assignment", "drone_id", "status"),
        db.Index("idx_active_request_assignment", "delivery_request_id", "status"),
    )

    # Relationships
    delivery_request = db.relationship("DeliveryRequest", back_populates="assignments")
    drone = db.relationship("Drone", back_populates="assignments")
    route = db.relationship("Route", back_populates="assignments")

    def __init__(
        self,
        delivery_request_id: int,
        drone_id: int,
        route_id: int,
        status: str = AssignmentStatus.ACTIVE.value,
        assigned_at: datetime = None,
    ):
        self.delivery_request_id = delivery_request_id
        self.drone_id = drone_id
        self.route_id = route_id
        self.status = status.value if isinstance(status, AssignmentStatus) else str(status).upper()
        self.assigned_at = assigned_at or datetime.now(timezone.utc)

    def mark_completed(self) -> None:
        """Mark assignment as successfully delivered."""
        self.status = AssignmentStatus.COMPLETED.value
        self.completed_at = datetime.now(timezone.utc)

    def mark_aborted(self) -> None:
        """Mark assignment as aborted due to emergency or hazard."""
        self.status = AssignmentStatus.ABORTED.value
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self) -> None:
        """Mark assignment as failed."""
        self.status = AssignmentStatus.FAILED.value
        self.completed_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Serialize assignment to dictionary."""
        return {
            "id": self.id,
            "delivery_request_id": self.delivery_request_id,
            "drone_id": self.drone_id,
            "route_id": self.route_id,
            "status": self.status,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self) -> str:
        return f"<DroneAssignment id={self.id} drone={self.drone_id} request={self.delivery_request_id} status={self.status}>"
