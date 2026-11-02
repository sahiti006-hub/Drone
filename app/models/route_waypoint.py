from app.extensions import db


class RouteWaypoint(db.Model):
    """Simulated waypoint in a planned drone flight trajectory.

    Note: These are mathematical simulation coordinates and do not constitute
    certified aviation flight paths.
    """
    __tablename__ = "route_waypoints"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    route_id = db.Column(
        db.Integer,
        db.ForeignKey("routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number = db.Column(db.Integer, nullable=False)
    latitude = db.Column(db.Numeric(10, 7), nullable=False)
    longitude = db.Column(db.Numeric(10, 7), nullable=False)
    altitude_m = db.Column(db.Numeric(6, 2), nullable=False, default=50.00)  # Height above ground in meters

    # Constraints: Ensure unique waypoint order per route
    __table_args__ = (
        db.UniqueConstraint("route_id", "sequence_number", name="uq_route_waypoint_sequence"),
    )

    # Relationship
    route = db.relationship("Route", back_populates="waypoints")

    def __init__(
        self,
        route_id: int,
        sequence_number: int,
        latitude: float,
        longitude: float,
        altitude_m: float = 50.00,
    ):
        lat_f = float(latitude)
        lng_f = float(longitude)
        if not (-90.0 <= lat_f <= 90.0):
            raise ValueError("Waypoint latitude must be between -90.0 and +90.0 degrees.")
        if not (-180.0 <= lng_f <= 180.0):
            raise ValueError("Waypoint longitude must be between -180.0 and +180.0 degrees.")
        if float(altitude_m) < 0:
            raise ValueError("Altitude above ground level cannot be negative.")
        if int(sequence_number) < 0:
            raise ValueError("Sequence number must be non-negative.")

        self.route_id = route_id
        self.sequence_number = sequence_number
        self.latitude = latitude
        self.longitude = longitude
        self.altitude_m = altitude_m

    def to_dict(self) -> dict:
        """Serialize waypoint to dictionary."""
        return {
            "id": self.id,
            "route_id": self.route_id,
            "sequence_number": self.sequence_number,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "altitude_m": float(self.altitude_m),
        }

    def __repr__(self) -> str:
        return f"<RouteWaypoint route={self.route_id} seq={self.sequence_number} ({self.latitude}, {self.longitude}, {self.altitude_m}m)>"
