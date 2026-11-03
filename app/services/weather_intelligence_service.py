"""Weather intelligence, route-wide risk evaluation, and emergency diversion service."""

from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Dict, List, Optional, Tuple, Any
from app.extensions import db
from app.models.weather_intelligence import (
    WeatherClassification,
    WeatherObservation,
    WeatherAlert,
    SafeDiversionLocation,
)
from app.services.route_optimizer import haversine_distance, Waypoint


class WeatherIntelligenceError(Exception):
    """Base exception for weather intelligence operations."""
    pass


class WeatherConditionSummary:
    """Structured report of weather safety classification along a mission path."""
    def __init__(
        self,
        classification: WeatherClassification,
        max_wind_speed_mps: float,
        max_precipitation_mmh: float,
        min_visibility_km: float,
        average_temperature_c: float,
        weather_summary: str,
        affected_segment: Optional[str] = None,
        warning_description: Optional[str] = None,
        recommended_action: Optional[str] = None,
        observations: Optional[List[WeatherObservation]] = None,
    ):
        self.classification = classification
        self.max_wind_speed_mps = round(max_wind_speed_mps, 2)
        self.max_precipitation_mmh = round(max_precipitation_mmh, 2)
        self.min_visibility_km = round(min_visibility_km, 2)
        self.average_temperature_c = round(average_temperature_c, 1)
        self.weather_summary = weather_summary
        self.affected_segment = affected_segment or "Global Route Corridor"
        self.warning_description = warning_description or "Conditions nominal for automated simulation dispatch."
        self.recommended_action = recommended_action or "Dispatch authorized under standard operating procedures."
        self.observations = observations or []
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "max_wind_speed_mps": self.max_wind_speed_mps,
            "max_precipitation_mmh": self.max_precipitation_mmh,
            "min_visibility_km": self.min_visibility_km,
            "average_temperature_c": self.average_temperature_c,
            "weather_summary": self.weather_summary,
            "affected_segment": self.affected_segment,
            "warning_description": self.warning_description,
            "recommended_action": self.recommended_action,
            "timestamp": self.timestamp.isoformat(),
            "observations_count": len(self.observations),
        }


class WeatherIntelligenceService:
    """Evaluates atmospheric conditions along complete flight corridors."""

    # Default thresholds for simulation risk classification
    THRESHOLD_GREEN_MAX_WIND = 8.0        # m/s
    THRESHOLD_YELLOW_MAX_WIND = 12.0      # m/s (mandatory cutoff)
    THRESHOLD_GREEN_MAX_RAIN = 2.0        # mm/h
    THRESHOLD_YELLOW_MAX_RAIN = 8.0       # mm/h (mandatory cutoff)
    THRESHOLD_GREEN_MIN_VISIBILITY = 5.0  # km
    THRESHOLD_YELLOW_MIN_VISIBILITY = 3.0 # km (mandatory cutoff)

    # In-memory scenario override for interactive academic demonstrations
    _demonstration_scenario: Optional[Dict[str, Any]] = None

    @classmethod
    def set_demonstration_scenario(
        cls,
        wind_speed_mps: Optional[float] = None,
        precipitation_mmh: Optional[float] = None,
        visibility_km: Optional[float] = None,
        summary: Optional[str] = None,
        affected_segment: Optional[str] = None,
    ) -> None:
        """Inject manual atmospheric scenario for live academic demonstrations."""
        if wind_speed_mps is None and precipitation_mmh is None and visibility_km is None:
            cls._demonstration_scenario = None
        else:
            cls._demonstration_scenario = {
                "wind_speed_mps": wind_speed_mps if wind_speed_mps is not None else 4.0,
                "precipitation_mmh": precipitation_mmh if precipitation_mmh is not None else 0.0,
                "visibility_km": visibility_km if visibility_km is not None else 10.0,
                "summary": summary or "Scenario Injection Demonstration Condition",
                "affected_segment": affected_segment or "Waypoint 2-3 High Turbulence Zone",
            }

    @classmethod
    def clear_demonstration_scenario(cls) -> None:
        """Reset scenario injection to standard deterministic simulation."""
        cls._demonstration_scenario = None

    @classmethod
    def sample_weather_at_coordinate(
        cls,
        lat: float,
        lng: float,
        alt_m: float = 60.0,
    ) -> WeatherObservation:
        """Generate or retrieve atmospheric observation at specific coordinate."""
        # Check active demonstration injection
        if cls._demonstration_scenario:
            wind = float(cls._demonstration_scenario["wind_speed_mps"])
            rain = float(cls._demonstration_scenario["precipitation_mmh"])
            vis = float(cls._demonstration_scenario["visibility_km"])
            summary = cls._demonstration_scenario["summary"]
            classification = cls.classify_conditions(wind, rain, vis)
            return WeatherObservation(
                latitude=Decimal(str(round(lat, 7))),
                longitude=Decimal(str(round(lng, 7))),
                wind_speed_mps=Decimal(str(wind)),
                precipitation_mmh=Decimal(str(rain)),
                visibility_km=Decimal(str(vis)),
                temperature_c=Decimal("24.5"),
                weather_summary=summary,
                classification=classification.value,
                source="SCENARIO_INJECTION",
            )

        # Deterministic spatial micro-meteorology based on coordinates
        # Generates smooth geographic atmospheric variation for simulation realism
        lat_factor = math.sin(math.radians(lat * 100.0))
        lng_factor = math.cos(math.radians(lng * 100.0))
        alt_factor = max(0.0, (alt_m - 50.0) / 100.0)

        # Base nominal benign wind ~ 3.5 m/s + geographic micro-gusts + altitude shear
        wind = round(3.5 + (1.8 * lat_factor) + (1.2 * lng_factor) + (2.5 * alt_factor), 2)
        wind = max(0.5, wind)

        rain = round(max(0.0, 0.4 * (lat_factor + lng_factor)), 2)
        vis = round(max(4.0, 10.0 - (0.8 * rain)), 2)
        temp = round(26.0 - (0.0065 * alt_m), 1)

        summary = "Clear Skies & Moderate Breeze"
        if wind > 8.0:
            summary = "Fresh Breeze with High-Altitude Wind Shear"
        if rain > 1.0:
            summary = "Passing Light Rain Showers"

        classification = cls.classify_conditions(wind, rain, vis)

        obs = WeatherObservation(
            latitude=Decimal(str(round(lat, 7))),
            longitude=Decimal(str(round(lng, 7))),
            wind_speed_mps=Decimal(str(wind)),
            precipitation_mmh=Decimal(str(rain)),
            visibility_km=Decimal(str(vis)),
            temperature_c=Decimal(str(temp)),
            weather_summary=summary,
            classification=classification.value,
            source="SIMULATION",
        )
        return obs

    @classmethod
    def classify_conditions(
        cls,
        wind_speed_mps: float,
        precipitation_mmh: float,
        visibility_km: float,
    ) -> WeatherClassification:
        """Classify atmospheric severity into GREEN, YELLOW, or RED."""
        if (
            wind_speed_mps > cls.THRESHOLD_YELLOW_MAX_WIND
            or precipitation_mmh > cls.THRESHOLD_YELLOW_MAX_RAIN
            or visibility_km < cls.THRESHOLD_YELLOW_MIN_VISIBILITY
        ):
            return WeatherClassification.RED

        if (
            wind_speed_mps > cls.THRESHOLD_GREEN_MAX_WIND
            or precipitation_mmh > cls.THRESHOLD_GREEN_MAX_RAIN
            or visibility_km < cls.THRESHOLD_GREEN_MIN_VISIBILITY
        ):
            return WeatherClassification.YELLOW

        return WeatherClassification.GREEN

    @classmethod
    def evaluate_corridor_weather(
        cls,
        waypoints: List[Waypoint],
    ) -> WeatherConditionSummary:
        """Evaluate atmospheric conditions across an entire candidate flight corridor."""
        if not waypoints:
            return WeatherConditionSummary(
                classification=WeatherClassification.GREEN,
                max_wind_speed_mps=3.0,
                max_precipitation_mmh=0.0,
                min_visibility_km=10.0,
                average_temperature_c=25.0,
                weather_summary="Nominal conditions",
            )

        observations = []
        max_wind = 0.0
        max_rain = 0.0
        min_vis = 999.0
        temp_sum = 0.0
        worst_classification = WeatherClassification.GREEN
        worst_segment = None

        for idx, wp in enumerate(waypoints):
            obs = cls.sample_weather_at_coordinate(wp.latitude, wp.longitude, wp.altitude_m)
            observations.append(obs)

            w = float(obs.wind_speed_mps)
            r = float(obs.precipitation_mmh)
            v = float(obs.visibility_km)
            t = float(obs.temperature_c)

            max_wind = max(max_wind, w)
            max_rain = max(max_rain, r)
            min_vis = min(min_vis, v)
            temp_sum += t

            segment_class = WeatherClassification(obs.classification)
            if segment_class == WeatherClassification.RED:
                worst_classification = WeatherClassification.RED
                worst_segment = f"Waypoint {idx + 1} ({round(wp.latitude, 4)}, {round(wp.longitude, 4)})"
            elif segment_class == WeatherClassification.YELLOW and worst_classification != WeatherClassification.RED:
                worst_classification = WeatherClassification.YELLOW
                worst_segment = f"Waypoint {idx + 1} Corridor Segment"

        avg_temp = temp_sum / len(waypoints) if waypoints else 25.0

        if worst_classification == WeatherClassification.RED:
            warning = (
                f"Severe atmospheric hazard: Peak wind {max_wind:.1f} m/s or rain {max_rain:.1f} mm/h "
                f"exceeds simulation safety limits (wind limit: {cls.THRESHOLD_YELLOW_MAX_WIND} m/s)."
            )
            action = "Dispatch blocked. In-flight missions must reroute or divert to designated safe landing site."
            summary = "Hazardous Meteorological Conditions - Flight Prohibited"
        elif worst_classification == WeatherClassification.YELLOW:
            warning = (
                f"Weather Advisory: Approaching limits along corridor. Observed wind {max_wind:.1f} m/s "
                f"(caution threshold {cls.THRESHOLD_GREEN_MAX_WIND} m/s). Travel times may extend."
            )
            action = "Requester caution acknowledgment required before dispatch."
            summary = "Cautionary Atmospheric Inflow - Advisory Active"
        else:
            warning = "Atmospheric parameters within ideal flight envelope."
            action = "Standard dispatch authorized."
            summary = "Optimal Green Airspace Conditions"

        return WeatherConditionSummary(
            classification=worst_classification,
            max_wind_speed_mps=max_wind,
            max_precipitation_mmh=max_rain,
            min_visibility_km=min_vis,
            average_temperature_c=avg_temp,
            weather_summary=summary,
            affected_segment=worst_segment or "All Waypoint Segments",
            warning_description=warning,
            recommended_action=action,
            observations=observations,
        )

    @classmethod
    def get_or_seed_diversion_locations(cls) -> List[SafeDiversionLocation]:
        """Retrieve pre-designated safe emergency landing locations or seed default campus helipads."""
        locations = SafeDiversionLocation.query.filter_by(is_active=True).all()
        if not locations:
            defaults = [
                SafeDiversionLocation(
                    name="North Campus Emergency Helipad A",
                    code="DIV-NORTH-01",
                    latitude=Decimal("12.9780000"),
                    longitude=Decimal("77.5950000"),
                    elevation_m=Decimal("55.0"),
                    max_drone_capacity=6,
                    has_charging_station=True,
                    description="Elevated hospital rooftop helipad equipped with automated charging tether.",
                ),
                SafeDiversionLocation(
                    name="South Lake Emergency Clearing B",
                    code="DIV-SOUTH-02",
                    latitude=Decimal("12.9620000"),
                    longitude=Decimal("77.6080000"),
                    elevation_m=Decimal("45.0"),
                    max_drone_capacity=4,
                    has_charging_station=False,
                    description="Open public park clearing designated for emergency multi-rotor diversion.",
                ),
                SafeDiversionLocation(
                    name="Central Tech Depot Helipad C",
                    code="DIV-CENTRAL-03",
                    latitude=Decimal("12.9716000"),
                    longitude=Decimal("77.5946000"),
                    elevation_m=Decimal("60.0"),
                    max_drone_capacity=10,
                    has_charging_station=True,
                    description="Primary drone maintenance depot with rapid automated recovery.",
                ),
            ]
            db.session.add_all(defaults)
            db.session.commit()
            locations = defaults
        return locations

    @classmethod
    def find_nearest_safe_diversion(
        cls,
        current_lat: float,
        current_lng: float,
        remaining_battery_wh: float,
    ) -> Optional[Dict[str, Any]]:
        """Identify nearest active emergency diversion helipad reachable within remaining battery."""
        locations = cls.get_or_seed_diversion_locations()
        if not locations:
            return None

        candidates = []
        for loc in locations:
            dist_km = haversine_distance(current_lat, current_lng, float(loc.latitude), float(loc.longitude))
            # Rough energy estimate: ~12 Wh per km + climb
            est_energy_wh = dist_km * 14.0
            is_reachable = remaining_battery_wh >= est_energy_wh

            candidates.append({
                "id": loc.id,
                "name": loc.name,
                "code": loc.code,
                "latitude": float(loc.latitude),
                "longitude": float(loc.longitude),
                "distance_km": round(dist_km, 3),
                "estimated_energy_wh": round(est_energy_wh, 2),
                "is_reachable": is_reachable,
                "has_charging": loc.has_charging_station,
                "description": loc.description,
            })

        # Sort by distance
        candidates.sort(key=lambda x: x["distance_km"])
        reachable_candidates = [c for c in candidates if c["is_reachable"]]

        return reachable_candidates[0] if reachable_candidates else candidates[0]
