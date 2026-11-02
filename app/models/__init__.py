"""SQLAlchemy models and database entities for Smart Emergency Drone System."""

from app.models.user import User, UserRole, ROLE_PERMISSIONS
from app.models.drone import Drone, DroneStatus, ALLOWED_DRONE_TRANSITIONS
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.weather_snapshot import WeatherSnapshot, WeatherDataSource
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.analysis_log import AnalysisLog, EvaluationStatus

__all__ = [
    "User",
    "UserRole",
    "ROLE_PERMISSIONS",
    "Drone",
    "DroneStatus",
    "ALLOWED_DRONE_TRANSITIONS",
    "DeliveryRequest",
    "RequestPriority",
    "RequestStatus",
    "EmergencyType",
    "Route",
    "FeasibilityStatus",
    "RouteWaypoint",
    "WeatherSnapshot",
    "WeatherDataSource",
    "DroneAssignment",
    "AssignmentStatus",
    "SimulationRun",
    "SimulationStatus",
    "AnalysisLog",
    "EvaluationStatus",
]
