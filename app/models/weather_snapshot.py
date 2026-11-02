import enum
from datetime import datetime, timezone
from app.extensions import db


class WeatherDataSource(str, enum.Enum):
    """Origin of weather snapshot information."""
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"


class WeatherSnapshot(db.Model):
    """Environmental and atmospheric conditions captured for a delivery dispatch.

    Units:
    - wind_speed: Meters per second (m/s). Directly impacts aerodynamic drag and battery drain.
    - precipitation: Millimeters per hour (mm/h). Values > 10 mm/h trigger weather warning.
    - visibility: Kilometers (km). Meteorological optical range.
    """
    __tablename__ = "weather_snapshots"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    delivery_request_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source = db.Column(db.String(50), nullable=False, default="SIMULATED_ENGINE")
    simulated_or_live = db.Column(
        db.String(20),
        nullable=False,
        default=WeatherDataSource.SIMULATED.value,
        index=True,
    )
    wind_speed = db.Column(db.Numeric(6, 2), nullable=False)  # m/s
    precipitation = db.Column(db.Numeric(6, 2), nullable=False, default=0.00)  # mm/h
    visibility = db.Column(db.Numeric(6, 2), nullable=False, default=10.00)  # km
    weather_summary = db.Column(db.String(100), nullable=False, default="Clear conditions")
    captured_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    delivery_request = db.relationship("DeliveryRequest", back_populates="weather_snapshots")

    def __init__(
        self,
        wind_speed: float,
        precipitation: float = 0.00,
        visibility: float = 10.00,
        weather_summary: str = "Clear conditions",
        source: str = "SIMULATED_ENGINE",
        simulated_or_live: str = WeatherDataSource.SIMULATED.value,
        delivery_request_id: int = None,
    ):
        if float(wind_speed) < 0:
            raise ValueError("Wind speed cannot be negative.")
        if float(precipitation) < 0:
            raise ValueError("Precipitation cannot be negative.")
        if float(visibility) < 0:
            raise ValueError("Visibility cannot be negative.")

        self.wind_speed = wind_speed
        self.precipitation = precipitation
        self.visibility = visibility
        self.weather_summary = weather_summary.strip()
        self.source = source.strip()
        self.simulated_or_live = (
            simulated_or_live.value
            if isinstance(simulated_or_live, WeatherDataSource)
            else str(simulated_or_live).upper()
        )
        self.delivery_request_id = delivery_request_id

    def to_dict(self) -> dict:
        """Serialize weather snapshot to dictionary with units."""
        return {
            "id": self.id,
            "delivery_request_id": self.delivery_request_id,
            "source": self.source,
            "simulated_or_live": self.simulated_or_live,
            "wind_speed_mps": float(self.wind_speed),
            "precipitation_mmh": float(self.precipitation),
            "visibility_km": float(self.visibility),
            "weather_summary": self.weather_summary,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }

    def __repr__(self) -> str:
        return f"<WeatherSnapshot id={self.id} type={self.simulated_or_live} wind={self.wind_speed}m/s>"
