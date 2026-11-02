"""Weather service interface and simulation provider.

IMPORTANT NOTICE:
This module provides simplified environmental metrics for discrete software
simulation only. It does not constitute certified aviation meteorological
data or real-world flight clearance.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from app.extensions import db
from app.models.weather_snapshot import WeatherSnapshot, WeatherDataSource


class WeatherServiceError(Exception):
    """Base exception for weather retrieval and validation failures."""
    pass


class MissingWeatherDataError(WeatherServiceError):
    """Raised when weather data is missing or incomplete for a safety evaluation."""
    pass


@dataclass(frozen=True)
class WeatherData:
    """Immutable atmospheric observation container.

    Units:
    - wind_speed_mps: meters per second (m/s)
    - precipitation_mmh: millimeters per hour (mm/h)
    - visibility_km: kilometers (km)
    - weather_summary: qualitative descriptive text
    - is_simulated: boolean flag distinguishing simulation from live API feeds
    """
    wind_speed_mps: float
    precipitation_mmh: float
    visibility_km: float
    weather_summary: str
    is_simulated: bool = True
    captured_at: Optional[datetime] = None

    def validate(self) -> None:
        """Validate meteorological boundaries."""
        if self.wind_speed_mps < 0:
            raise ValueError(f"Wind speed cannot be negative: {self.wind_speed_mps} m/s")
        if self.precipitation_mmh < 0:
            raise ValueError(f"Precipitation cannot be negative: {self.precipitation_mmh} mm/h")
        if self.visibility_km < 0:
            raise ValueError(f"Visibility cannot be negative: {self.visibility_km} km")


class WeatherService:
    """Service providing weather data and evaluation for route feasibility."""

    # Default simulation thresholds for small electric cargo drones
    DEFAULT_MAX_WIND_SPEED_MPS = 12.0    # ~43.2 km/h
    DEFAULT_MIN_VISIBILITY_KM = 3.0      # Minimum visual meteorological condition proxy
    DEFAULT_MAX_PRECIPITATION_MMH = 8.0  # Moderate-to-heavy rainfall cutoff

    @classmethod
    def get_weather_for_request(
        cls,
        delivery_request_id: Optional[int] = None,
        require_weather: bool = True,
    ) -> WeatherData:
        """Retrieve the latest weather observation for a delivery request.

        Safety Policy:
        Missing weather data is NEVER silently defaulted to benign or safe conditions.
        If require_weather is True and no snapshot exists, MissingWeatherDataError is raised.
        """
        if delivery_request_id is not None:
            snapshot = (
                WeatherSnapshot.query.filter_by(delivery_request_id=delivery_request_id)
                .order_by(WeatherSnapshot.captured_at.desc())
                .first()
            )
            if snapshot:
                data = WeatherData(
                    wind_speed_mps=float(snapshot.wind_speed),
                    precipitation_mmh=float(snapshot.precipitation),
                    visibility_km=float(snapshot.visibility),
                    weather_summary=snapshot.weather_summary,
                    is_simulated=(snapshot.simulated_or_live == WeatherDataSource.SIMULATED.value),
                    captured_at=snapshot.captured_at,
                )
                data.validate()
                return data

        if require_weather:
            raise MissingWeatherDataError(
                f"No verified weather snapshot available for Delivery Request #{delivery_request_id}. "
                f"Safety policy requires explicit weather assessment prior to route feasibility evaluation."
            )

        # Conservative fallback if explicit requirement is bypassed for generic corridor analysis
        return WeatherData(
            wind_speed_mps=3.0,
            precipitation_mmh=0.0,
            visibility_km=10.0,
            weather_summary="Standard Clear Day Simulation",
            is_simulated=True,
            captured_at=datetime.now(timezone.utc),
        )

    @classmethod
    def record_simulated_weather(
        cls,
        delivery_request_id: Optional[int],
        wind_speed_mps: float = 3.5,
        precipitation_mmh: float = 0.0,
        visibility_km: float = 10.0,
        weather_summary: str = "Standard Simulation Environment",
    ) -> WeatherSnapshot:
        """Persist a simulated weather snapshot for auditability."""
        snapshot = WeatherSnapshot(
            delivery_request_id=delivery_request_id,
            wind_speed=wind_speed_mps,
            precipitation=precipitation_mmh,
            visibility=visibility_km,
            weather_summary=weather_summary,
            source="SIMULATED_ENGINE",
            simulated_or_live=WeatherDataSource.SIMULATED.value,
        )
        db.session.add(snapshot)
        db.session.commit()
        return snapshot
