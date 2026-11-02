import enum
from datetime import datetime, timezone
from app.extensions import db


class FeasibilityStatus(str, enum.Enum):
    """Feasibility classification of a calculated route candidate."""
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"


class Route(db.Model):
    """Candidate or selected flight route generated for a delivery request."""
    __tablename__ = "routes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    algorithm_name = db.Column(db.String(50), nullable=False)  # e.g., "A_STAR", "DIJKSTRA"
    estimated_distance_km = db.Column(db.Numeric(8, 3), nullable=False)
    estimated_duration_minutes = db.Column(db.Numeric(8, 2), nullable=False)
    estimated_energy_wh = db.Column(db.Numeric(8, 2), nullable=False)
    route_score = db.Column(db.Numeric(8, 4), nullable=True)  # Lower or higher composite optimization score
    feasibility_status = db.Column(
        db.String(20),
        nullable=False,
        default=FeasibilityStatus.FEASIBLE.value,
        index=True,
    )
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    delivery_request = db.relationship("DeliveryRequest", back_populates="routes")
    waypoints = db.relationship(
        "RouteWaypoint",
        back_populates="route",
        order_by="RouteWaypoint.sequence_number",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    assignments = db.relationship(
        "DroneAssignment",
        back_populates="route",
        lazy="dynamic",
    )

    def __init__(
        self,
        delivery_request_id: int,
        algorithm_name: str,
        estimated_distance_km: float,
        estimated_duration_minutes: float,
        estimated_energy_wh: float,
        route_score: float = None,
        feasibility_status: str = FeasibilityStatus.FEASIBLE.value,
        rejection_reason: str = None,
    ):
        if float(estimated_distance_km) < 0:
            raise ValueError("Estimated distance cannot be negative.")
        if float(estimated_duration_minutes) < 0:
            raise ValueError("Estimated duration cannot be negative.")
        if float(estimated_energy_wh) < 0:
            raise ValueError("Estimated energy consumption cannot be negative.")

        self.delivery_request_id = delivery_request_id
        self.algorithm_name = algorithm_name.strip()
        self.estimated_distance_km = estimated_distance_km
        self.estimated_duration_minutes = estimated_duration_minutes
        self.estimated_energy_wh = estimated_energy_wh
        self.route_score = route_score
        self.feasibility_status = (
            feasibility_status.value
            if isinstance(feasibility_status, FeasibilityStatus)
            else str(feasibility_status).upper()
        )
        self.rejection_reason = rejection_reason

    def to_dict(self, include_waypoints: bool = True) -> dict:
        """Serialize route model to dictionary."""
        data = {
            "id": self.id,
            "delivery_request_id": self.delivery_request_id,
            "algorithm_name": self.algorithm_name,
            "estimated_distance_km": float(self.estimated_distance_km),
            "estimated_duration_minutes": float(self.estimated_duration_minutes),
            "estimated_energy_wh": float(self.estimated_energy_wh),
            "route_score": float(self.route_score) if self.route_score is not None else None,
            "feasibility_status": self.feasibility_status,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_waypoints:
            data["waypoints"] = [wp.to_dict() for wp in self.waypoints]
        return data

    def __repr__(self) -> str:
        return f"<Route id={self.id} algo={self.algorithm_name} distance={self.estimated_distance_km}km status={self.feasibility_status}>"
