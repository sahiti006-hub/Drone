"""Weather intelligence and safety diversion entities."""

import enum
from datetime import datetime, timezone
from app.extensions import db


class WeatherClassification(str, enum.Enum):
    """Visual safety indicator classifications."""
    GREEN = "GREEN"    # Safe within all limits
    YELLOW = "YELLOW"  # Advisory caution, approaching limits
    RED = "RED"        # Infeasible / hazardous, flight blocked


class WeatherObservation(db.Model):
    """Persisted observation at a specific spatial coordinate or flight corridor segment."""
    __tablename__ = "weather_observations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    latitude = db.Column(db.Numeric(10, 7), nullable=False, index=True)
    longitude = db.Column(db.Numeric(10, 7), nullable=False, index=True)
    wind_speed_mps = db.Column(db.Numeric(6, 2), nullable=False)
    precipitation_mmh = db.Column(db.Numeric(6, 2), nullable=False)
    visibility_km = db.Column(db.Numeric(6, 2), nullable=False)
    temperature_c = db.Column(db.Numeric(5, 2), nullable=False, default=25.0)
    weather_summary = db.Column(db.String(100), nullable=False)
    classification = db.Column(db.String(20), nullable=False, default=WeatherClassification.GREEN.value, index=True)
    source = db.Column(db.String(30), nullable=False, default="SIMULATION")
    captured_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "wind_speed_mps": float(self.wind_speed_mps),
            "precipitation_mmh": float(self.precipitation_mmh),
            "visibility_km": float(self.visibility_km),
            "temperature_c": float(self.temperature_c),
            "weather_summary": self.weather_summary,
            "classification": self.classification,
            "source": self.source,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }


class WeatherAlert(db.Model):
    """Safety alerts generated when conditions enter caution or hazard categories."""
    __tablename__ = "weather_alerts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_bookings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    simulation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("simulation_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    alert_level = db.Column(db.String(20), nullable=False)  # CAUTION, HAZARD, CRITICAL
    weather_classification = db.Column(db.String(20), nullable=False)  # YELLOW, RED
    affected_segment = db.Column(db.String(100), nullable=True)
    warning_description = db.Column(db.String(255), nullable=False)
    recommended_action = db.Column(db.String(255), nullable=False)
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    booking = db.relationship("DroneBooking", back_populates="weather_alerts")
    simulation_run = db.relationship("SimulationRun")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "simulation_run_id": self.simulation_run_id,
            "alert_level": self.alert_level,
            "weather_classification": self.weather_classification,
            "affected_segment": self.affected_segment,
            "warning_description": self.warning_description,
            "recommended_action": self.recommended_action,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SafeDiversionLocation(db.Model):
    """Pre-designated emergency landing helipads or safe clearings."""
    __tablename__ = "safe_diversion_locations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(30), unique=True, index=True, nullable=False)
    latitude = db.Column(db.Numeric(10, 7), nullable=False)
    longitude = db.Column(db.Numeric(10, 7), nullable=False)
    elevation_m = db.Column(db.Numeric(6, 2), nullable=False, default=50.0)
    max_drone_capacity = db.Column(db.Integer, nullable=False, default=5)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    has_charging_station = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "elevation_m": float(self.elevation_m),
            "max_drone_capacity": self.max_drone_capacity,
            "is_active": self.is_active,
            "has_charging_station": self.has_charging_station,
            "description": self.description,
        }
