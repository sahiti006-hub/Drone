"""Automated unit and integration tests for Weather Intelligence and Safety Diversions."""

import pytest
from app.extensions import db
from app.models.weather_intelligence import (
    WeatherClassification,
    SafeDiversionLocation,
)
from app.services.weather_intelligence_service import (
    WeatherIntelligenceService,
    WeatherConditionSummary,
)
from app.services.route_optimizer import Waypoint


def test_weather_classification_thresholds(app):
    """Verify GREEN, YELLOW, and RED classification rules."""
    # Green conditions
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=5.0, precipitation_mmh=1.0, visibility_km=8.0
    ) == WeatherClassification.GREEN

    # Yellow conditions: moderate wind
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=10.0, precipitation_mmh=1.0, visibility_km=8.0
    ) == WeatherClassification.YELLOW

    # Yellow conditions: moderate precipitation
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=5.0, precipitation_mmh=4.0, visibility_km=8.0
    ) == WeatherClassification.YELLOW

    # Yellow conditions: reduced visibility
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=5.0, precipitation_mmh=1.0, visibility_km=4.0
    ) == WeatherClassification.YELLOW

    # Red conditions: severe wind
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=15.0, precipitation_mmh=0.0, visibility_km=10.0
    ) == WeatherClassification.RED

    # Red conditions: heavy rain
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=4.0, precipitation_mmh=12.0, visibility_km=10.0
    ) == WeatherClassification.RED

    # Red conditions: thick fog
    assert WeatherIntelligenceService.classify_conditions(
        wind_speed_mps=4.0, precipitation_mmh=0.0, visibility_km=1.5
    ) == WeatherClassification.RED


def test_demonstration_scenario_injection(app):
    """Test manual injection of atmospheric scenario override."""
    WeatherIntelligenceService.clear_demonstration_scenario()

    # Nominal check
    obs_nominal = WeatherIntelligenceService.sample_weather_at_coordinate(12.9716, 77.5946)
    assert obs_nominal.source == "SIMULATION"

    # Inject storm override
    WeatherIntelligenceService.set_demonstration_scenario(
        wind_speed_mps=18.0,
        precipitation_mmh=25.0,
        visibility_km=1.0,
        summary="Severe squall front simulation",
    )

    obs_injected = WeatherIntelligenceService.sample_weather_at_coordinate(12.9716, 77.5946)
    assert obs_injected.source == "SCENARIO_INJECTION"
    assert float(obs_injected.wind_speed_mps) == 18.0
    assert float(obs_injected.precipitation_mmh) == 25.0
    assert obs_injected.classification == WeatherClassification.RED.value

    # Corridor evaluation under injected scenario
    wps = [
        Waypoint(12.9716, 77.5946, 60.0),
        Waypoint(12.9500, 77.6100, 60.0),
    ]
    summary = WeatherIntelligenceService.evaluate_corridor_weather(wps)
    assert summary.classification == WeatherClassification.RED

    # Reset
    WeatherIntelligenceService.clear_demonstration_scenario()
    obs_reset = WeatherIntelligenceService.sample_weather_at_coordinate(12.9716, 77.5946)
    assert obs_reset.source == "SIMULATION"


def test_safe_diversion_discovery(app):
    """Test seeding and querying nearest reachable emergency helipad."""
    locations = WeatherIntelligenceService.get_or_seed_diversion_locations()
    assert len(locations) >= 3

    # Query from near South Lake
    nearest = WeatherIntelligenceService.find_nearest_safe_diversion(
        current_lat=12.9625,
        current_lng=77.6085,
        remaining_battery_wh=100.0,
    )
    assert nearest is not None
    assert "South Lake" in nearest["name"] or "DIV-SOUTH" in nearest["code"]
    assert nearest["is_reachable"] is True
