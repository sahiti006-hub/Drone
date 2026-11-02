"""Business logic and data access services."""

from app.services.drone_service import (
    DroneService,
    DroneServiceError,
    InvalidDroneTransitionError,
    DroneNotFoundError,
)
from app.services.delivery_service import (
    DeliveryService,
    DeliveryServiceError,
    DeliveryRequestNotFoundError,
    InvalidRequestStateError,
    DeliveryPermissionDeniedError,
)
from app.services.assignment_service import (
    AssignmentService,
    AssignmentServiceError,
    ConflictingAssignmentError,
    InfeasibleAssignmentError,
)
from app.services.user_service import UserService, UserServiceError
from app.services.auth_service import AuthService, login_required, role_required
from app.services.weather_service import (
    WeatherService,
    WeatherData,
    WeatherServiceError,
    MissingWeatherDataError,
)
from app.services.route_optimizer import (
    Waypoint,
    RouteCandidate,
    OptimizationResult,
    CandidateRouteGenerator,
    FeasibilityChecker,
    RouteOptimizer,
    haversine_distance,
    compute_path_distance,
    estimate_travel_time,
    estimate_energy_consumption,
)
from app.services.drone_allocation_service import (
    DroneAllocationService,
    AllocationServiceError,
)

__all__ = [
    "DroneService",
    "DroneServiceError",
    "InvalidDroneTransitionError",
    "DroneNotFoundError",
    "DeliveryService",
    "DeliveryServiceError",
    "DeliveryRequestNotFoundError",
    "InvalidRequestStateError",
    "DeliveryPermissionDeniedError",
    "AssignmentService",
    "AssignmentServiceError",
    "ConflictingAssignmentError",
    "InfeasibleAssignmentError",
    "UserService",
    "UserServiceError",
    "AuthService",
    "login_required",
    "role_required",
    "WeatherService",
    "WeatherData",
    "WeatherServiceError",
    "MissingWeatherDataError",
    "Waypoint",
    "RouteCandidate",
    "OptimizationResult",
    "CandidateRouteGenerator",
    "FeasibilityChecker",
    "RouteOptimizer",
    "haversine_distance",
    "compute_path_distance",
    "estimate_travel_time",
    "estimate_energy_consumption",
    "DroneAllocationService",
    "AllocationServiceError",
]
