"""Deterministic route generator, feasibility validator, and multi-objective optimizer.

IMPORTANT SIMULATION NOTICE:
This module is a software simulation model intended solely for educational,
academic research, and comparative algorithmic evaluation. It does NOT
constitute a certified aviation flight-planning tool, autopilot controller,
or real-world flight safety clearance system. Candidate paths represent
simplified 2D/3D geometric corridors and must not be interpreted as legally
approved or physically conflict-free airspace corridors.
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from app.services.weather_service import WeatherData, MissingWeatherDataError


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

@dataclass(frozen=True)
class Waypoint:
    """Discrete geospatial waypoint in a candidate flight corridor.

    Units:
    - latitude: decimal degrees (-90.0 to +90.0)
    - longitude: decimal degrees (-180.0 to +180.0)
    - altitude_m: meters above ground level (AGL)
    """
    latitude: float
    longitude: float
    altitude_m: float = 50.0

    def validate(self) -> None:
        """Validate WGS84 boundary limits."""
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Latitude out of bounds: {self.latitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"Longitude out of bounds: {self.longitude}")
        if self.altitude_m < 0:
            raise ValueError(f"Altitude cannot be negative: {self.altitude_m}m")


@dataclass
class RouteCandidate:
    """Evaluated flight corridor candidate with estimated metrics."""
    candidate_id: str
    corridor_name: str
    waypoints: List[Waypoint]
    distance_km: float = 0.0
    duration_minutes: float = 0.0
    energy_wh: float = 0.0
    penalty_score: float = 0.0
    objective_score: float = 0.0
    is_feasible: bool = False
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize route candidate for reporting and JSON responses."""
        return {
            "candidate_id": self.candidate_id,
            "corridor_name": self.corridor_name,
            "waypoint_count": len(self.waypoints),
            "distance_km": round(self.distance_km, 3),
            "duration_minutes": round(self.duration_minutes, 2),
            "energy_wh": round(self.energy_wh, 2),
            "penalty_score": round(self.penalty_score, 4),
            "objective_score": round(self.objective_score, 4),
            "is_feasible": self.is_feasible,
            "rejection_reasons": self.rejection_reasons,
            "waypoints": [
                {"lat": w.latitude, "lng": w.longitude, "alt_m": w.altitude_m}
                for w in self.waypoints
            ],
        }


@dataclass
class OptimizationResult:
    """Structured result returned by the route optimization engine."""
    selected_route: Optional[RouteCandidate]
    algorithm_name: str
    candidate_count: int
    feasible_count: int
    candidates: List[RouteCandidate]
    rejected_candidates: List[Dict[str, any]]
    is_feasible: bool
    weights: Dict[str, float]
    configuration: Dict[str, any]
    summary_message: str

    def to_dict(self) -> dict:
        """Serialize optimization result."""
        return {
            "algorithm_name": self.algorithm_name,
            "is_feasible": self.is_feasible,
            "candidate_count": self.candidate_count,
            "feasible_count": self.feasible_count,
            "selected_route": self.selected_route.to_dict() if self.selected_route else None,
            "rejected_candidates": self.rejected_candidates,
            "weights": self.weights,
            "configuration": self.configuration,
            "summary_message": self.summary_message,
        }


# ==============================================================================
# INDEPENDENT MATHEMATICAL & METRIC ESTIMATION FUNCTIONS
# ==============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth surface.

    Assumptions & Limitations:
    - Assumes a spherical Earth with mean radius R = 6,371.0 kilometers.
    - Neglects ellipsoidal flattening of the WGS84 geoid (error < 0.5% for local drone flights).
    - Ignores vertical altitude delta in horizontal distance.

    Returns:
        float: Horizontal distance in kilometers.
    """
    R = 6371.0  # Mean radius of Earth in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Clip to avoid floating point domain errors in sqrt
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c


def compute_path_distance(waypoints: List[Waypoint]) -> float:
    """Compute total cumulative distance across an ordered waypoint sequence in km."""
    if len(waypoints) < 2:
        return 0.0

    total_km = 0.0
    for i in range(len(waypoints) - 1):
        w1, w2 = waypoints[i], waypoints[i + 1]
        total_km += haversine_distance(w1.latitude, w1.longitude, w2.latitude, w2.longitude)

    return total_km


def estimate_travel_time(
    distance_km: float,
    cruise_speed_kmh: float = 60.0,
    wind_headwind_mps: float = 0.0,
    transition_buffer_minutes: float = 1.0,
) -> float:
    """Estimate simulated flight travel time in minutes.

    Assumptions & Limitations:
    - Constant cruise airspeed in steady-state horizontal flight.
    - Simplified linear headwind penalty: effective speed v_eff = v_cruise - 0.75 * v_headwind.
    - Fixed 1.0 minute transition buffer added for simulated vertical takeoff, climb, and descent.
    - Minimum effective speed is clamped at 15.0 km/h to prevent zero/negative velocity.
    """
    if distance_km <= 0:
        return 0.0

    headwind_kmh = wind_headwind_mps * 3.6
    effective_speed_kmh = max(15.0, cruise_speed_kmh - (0.75 * headwind_kmh))

    flight_minutes = (distance_km / effective_speed_kmh) * 60.0
    return round(flight_minutes + transition_buffer_minutes, 2)


def estimate_energy_consumption(
    distance_km: float,
    duration_minutes: float,
    payload_weight_kg: float,
    cruise_speed_kmh: float = 60.0,
    base_power_watts: float = 240.0,
    payload_factor_watts_per_kg: float = 38.0,
    aerodynamic_factor: float = 0.016,
    include_return_trip: bool = False,
) -> float:
    """Estimate electric energy consumption in Watt-hours (Wh).

    SIMPLIFIED SIMULATION MODEL (Not a validated aeronautical wind-tunnel model):
    - Outbound flight power (loaded with payload):
        P_outbound = P_base + (c_payload * m_payload) + (c_aero * v_cruise^2)  [Watts]
    - Outbound energy consumption:
        E_outbound = P_outbound * (duration_minutes / 60.0)  [Watt-hours]
    - If include_return_trip is True:
        Models drone returning empty to base (payload = 0 kg) at standard cruise speed:
        P_return = P_base + (c_aero * v_cruise^2)  [Watts]
        E_return = P_return * (duration_minutes / 60.0)  [Watt-hours]
        E_total = E_outbound + E_return
    """
    if distance_km <= 0 or duration_minutes <= 0:
        return 0.0

    duration_hours = duration_minutes / 60.0

    # Outbound leg power (with cargo)
    p_outbound = (
        base_power_watts
        + (payload_factor_watts_per_kg * payload_weight_kg)
        + (aerodynamic_factor * (cruise_speed_kmh ** 2))
    )
    e_outbound = p_outbound * duration_hours

    if not include_return_trip:
        return round(e_outbound, 2)

    # Return leg power (empty payload)
    p_return = base_power_watts + (aerodynamic_factor * (cruise_speed_kmh ** 2))
    e_return = p_return * duration_hours

    return round(e_outbound + e_return, 2)


# ==============================================================================
# CANDIDATE ROUTE GENERATOR
# ==============================================================================

class CandidateRouteGenerator:
    """Generates alternative 2D geometric flight corridors between two points.

    Does NOT route along ground street networks. Generates clean airspace corridors:
    1. DIRECT: Straight-line corridor with intermediate altitude checks.
    2. NORTH_DETOUR: Lateral perpendicular arc offset to the north.
    3. SOUTH_DETOUR: Lateral perpendicular arc offset to the south.
    4. HIGH_ALTITUDE: Direct path with elevated cruise ceiling (e.g. 90m AGL).
    """

    @classmethod
    def generate_candidates(
        cls,
        pickup_lat: float,
        pickup_lng: float,
        dest_lat: float,
        dest_lng: float,
        lateral_offset_km: float = 0.85,
        default_altitude_m: float = 50.0,
        high_altitude_m: float = 90.0,
    ) -> List[RouteCandidate]:
        """Generate alternative candidate waypoint sequences.

        Returns empty list if coordinates are identical or invalid.
        """
        # Validate coordinates
        for lat, lng, label in [
            (pickup_lat, pickup_lng, "Pickup"),
            (dest_lat, dest_lng, "Destination"),
        ]:
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
                return []

        straight_distance = haversine_distance(pickup_lat, pickup_lng, dest_lat, dest_lng)
        if straight_distance < 0.05:  # Identical or under 50m apart
            return []

        p_start = Waypoint(pickup_lat, pickup_lng, altitude_m=default_altitude_m)
        p_end = Waypoint(dest_lat, dest_lng, altitude_m=default_altitude_m)

        # Midpoint calculation
        mid_lat = (pickup_lat + dest_lat) / 2.0
        mid_lng = (pickup_lng + dest_lng) / 2.0

        # Approximate perpendicular unit vector in latitude/longitude degrees
        # (1 deg latitude ~ 111 km, 1 deg longitude ~ 111 * cos(lat) km)
        delta_lat = dest_lat - pickup_lat
        delta_lng = dest_lng - pickup_lng
        cos_mid = max(0.2, math.cos(math.radians(mid_lat)))

        perp_lat = -delta_lng * cos_mid
        perp_lng = delta_lat / cos_mid
        perp_mag = math.sqrt(perp_lat ** 2 + perp_lng ** 2) or 1.0

        lat_deg_offset = (lateral_offset_km / 111.0) * (perp_lat / perp_mag)
        lng_deg_offset = (lateral_offset_km / (111.0 * cos_mid)) * (perp_lng / perp_mag)

        candidates = []

        # 1. Direct Corridor
        quarter_lat = pickup_lat + 0.33 * delta_lat
        quarter_lng = pickup_lng + 0.33 * delta_lng
        three_q_lat = pickup_lat + 0.67 * delta_lat
        three_q_lng = pickup_lng + 0.67 * delta_lng

        direct_wps = [
            p_start,
            Waypoint(quarter_lat, quarter_lng, altitude_m=default_altitude_m),
            Waypoint(three_q_lat, three_q_lng, altitude_m=default_altitude_m),
            p_end,
        ]
        candidates.append(
            RouteCandidate(
                candidate_id="CORRIDOR_DIRECT",
                corridor_name="Direct Air Corridor",
                waypoints=direct_wps,
            )
        )

        # 2. North / Lateral Positive Detour Corridor
        north_mid = Waypoint(
            latitude=min(90.0, max(-90.0, mid_lat + lat_deg_offset)),
            longitude=min(180.0, max(-180.0, mid_lng + lng_deg_offset)),
            altitude_m=default_altitude_m + 10.0,
        )
        north_wps = [p_start, north_mid, p_end]
        candidates.append(
            RouteCandidate(
                candidate_id="CORRIDOR_NORTH_DETOUR",
                corridor_name="Northern Peripheral Corridor",
                waypoints=north_wps,
            )
        )

        # 3. South / Lateral Negative Detour Corridor
        south_mid = Waypoint(
            latitude=min(90.0, max(-90.0, mid_lat - lat_deg_offset)),
            longitude=min(180.0, max(-180.0, mid_lng - lng_deg_offset)),
            altitude_m=default_altitude_m + 10.0,
        )
        south_wps = [p_start, south_mid, p_end]
        candidates.append(
            RouteCandidate(
                candidate_id="CORRIDOR_SOUTH_DETOUR",
                corridor_name="Southern Peripheral Corridor",
                waypoints=south_wps,
            )
        )

        # 4. High Altitude Corridor (Overflights / obstacle clearance)
        high_alt_wps = [
            Waypoint(pickup_lat, pickup_lng, altitude_m=default_altitude_m),
            Waypoint(mid_lat, mid_lng, altitude_m=high_altitude_m),
            Waypoint(dest_lat, dest_lng, altitude_m=default_altitude_m),
        ]
        candidates.append(
            RouteCandidate(
                candidate_id="CORRIDOR_HIGH_ALTITUDE",
                corridor_name="High Altitude Safety Corridor",
                waypoints=high_alt_wps,
            )
        )

        return candidates


# ==============================================================================
# FEASIBILITY VALIDATOR
# ==============================================================================

class FeasibilityChecker:
    """Evaluates candidate routes against physical drone capacities and environmental rules."""

    def __init__(
        self,
        maximum_payload_kg: float,
        battery_capacity_wh: float,
        current_battery_wh: float,
        battery_reserve_margin: float = 0.15,  # 15% mandatory non-depletable reserve
        max_wind_speed_mps: float = 12.0,
        min_visibility_km: float = 3.0,
        max_precipitation_mmh: float = 8.0,
        include_return_trip: bool = False,
    ):
        self.maximum_payload_kg = float(maximum_payload_kg)
        self.battery_capacity_wh = float(battery_capacity_wh)
        self.current_battery_wh = float(current_battery_wh)
        self.battery_reserve_margin = float(battery_reserve_margin)
        self.max_wind_speed_mps = float(max_wind_speed_mps)
        self.min_visibility_km = float(min_visibility_km)
        self.max_precipitation_mmh = float(max_precipitation_mmh)
        self.include_return_trip = bool(include_return_trip)

    def evaluate_candidate(
        self,
        candidate: RouteCandidate,
        payload_weight_kg: float,
        weather: Optional[WeatherData],
    ) -> bool:
        """Evaluate if candidate satisfies all physical and meteorological constraints.

        Modifies candidate.is_feasible and appends rejection_reasons.
        """
        rejection_reasons = []

        # 1. Payload Constraint
        if float(payload_weight_kg) > self.maximum_payload_kg:
            rejection_reasons.append(
                f"Payload exceeds capacity: cargo is {payload_weight_kg} kg, "
                f"drone maximum is {self.maximum_payload_kg} kg."
            )

        # 2. Battery Reserve Constraint
        # Drone cannot deplete beyond reserve margin (e.g., remaining >= 15%)
        usable_battery_wh = self.current_battery_wh * (1.0 - self.battery_reserve_margin)
        if candidate.energy_wh > usable_battery_wh:
            rejection_reasons.append(
                f"Insufficient battery: route requires {candidate.energy_wh} Wh, "
                f"usable battery is {round(usable_battery_wh, 2)} Wh "
                f"(current: {self.current_battery_wh} Wh with {int(self.battery_reserve_margin * 100)}% mandatory reserve)."
            )

        # 3. Environmental Weather Constraints
        if weather is None:
            rejection_reasons.append(
                "Missing verified weather observation: policy prohibits dispatch without atmospheric verification."
            )
        else:
            if weather.wind_speed_mps > self.max_wind_speed_mps:
                rejection_reasons.append(
                    f"Wind speed exceeds safety threshold: observed {weather.wind_speed_mps} m/s, "
                    f"threshold is {self.max_wind_speed_mps} m/s."
                )

            if weather.visibility_km < self.min_visibility_km:
                rejection_reasons.append(
                    f"Visibility below minimum requirement: observed {weather.visibility_km} km, "
                    f"minimum required is {self.min_visibility_km} km."
                )

            if weather.precipitation_mmh > self.max_precipitation_mmh:
                rejection_reasons.append(
                    f"Precipitation exceeds flight tolerance: observed {weather.precipitation_mmh} mm/h, "
                    f"threshold is {self.max_precipitation_mmh} mm/h."
                )

        candidate.rejection_reasons = rejection_reasons
        candidate.is_feasible = (len(rejection_reasons) == 0)
        return candidate.is_feasible


# ==============================================================================
# ROUTE OPTIMIZATION ENGINE
# ==============================================================================

class RouteOptimizer:
    """Multi-objective deterministic route optimization engine."""

    DEFAULT_WEIGHTS = {
        "distance": 0.25,
        "duration": 0.35,
        "energy": 0.30,
        "penalty": 0.10,
    }

    @classmethod
    def optimize(
        cls,
        pickup_lat: float,
        pickup_lng: float,
        dest_lat: float,
        dest_lng: float,
        payload_weight_kg: float,
        drone_cruise_speed_kmh: float,
        drone_max_payload_kg: float,
        drone_battery_capacity_wh: float,
        drone_current_battery_wh: float,
        weather: Optional[WeatherData],
        weights: Optional[Dict[str, float]] = None,
        include_return_trip: bool = False,
        battery_reserve_margin: float = 0.15,
        algorithm_name: str = "WEIGHTED_MULTI_OBJECTIVE",
    ) -> OptimizationResult:
        """Execute deterministic candidate generation, metric scoring, feasibility checking, and selection."""
        config = {
            "pickup": {"lat": pickup_lat, "lng": pickup_lng},
            "destination": {"lat": dest_lat, "lng": dest_lng},
            "payload_weight_kg": payload_weight_kg,
            "drone_specs": {
                "cruise_speed_kmh": drone_cruise_speed_kmh,
                "max_payload_kg": drone_max_payload_kg,
                "battery_capacity_wh": drone_battery_capacity_wh,
                "current_battery_wh": drone_current_battery_wh,
                "battery_reserve_margin": battery_reserve_margin,
            },
            "include_return_trip": include_return_trip,
            "weather_checked": weather is not None,
        }

        # 1. Generate Candidates
        candidates = CandidateRouteGenerator.generate_candidates(
            pickup_lat, pickup_lng, dest_lat, dest_lng
        )

        if not candidates:
            return OptimizationResult(
                selected_route=None,
                algorithm_name=algorithm_name,
                candidate_count=0,
                feasible_count=0,
                candidates=[],
                rejected_candidates=[],
                is_feasible=False,
                weights=weights or cls.DEFAULT_WEIGHTS,
                configuration=config,
                summary_message="No candidates could be generated. Check coordinate validity and ensure pickup and destination are distinct.",
            )

        # 2. Compute Independent Metrics for all candidates
        headwind = weather.wind_speed_mps if weather else 0.0

        for candidate in candidates:
            dist = compute_path_distance(candidate.waypoints)
            candidate.distance_km = dist
            candidate.duration_minutes = estimate_travel_time(
                distance_km=dist,
                cruise_speed_kmh=drone_cruise_speed_kmh,
                wind_headwind_mps=headwind,
            )
            candidate.energy_wh = estimate_energy_consumption(
                distance_km=dist,
                duration_minutes=candidate.duration_minutes,
                payload_weight_kg=payload_weight_kg,
                cruise_speed_kmh=drone_cruise_speed_kmh,
                include_return_trip=include_return_trip,
            )
            # Route penalty: slight penalty for lateral deviation and altitude steps
            alt_diff = sum(
                abs(candidate.waypoints[i].altitude_m - candidate.waypoints[i - 1].altitude_m)
                for i in range(1, len(candidate.waypoints))
            )
            detour_ratio = dist / max(0.1, haversine_distance(pickup_lat, pickup_lng, dest_lat, dest_lng))
            candidate.penalty_score = (alt_diff * 0.01) + ((detour_ratio - 1.0) * 1.5)

        # 3. Evaluate Feasibility
        checker = FeasibilityChecker(
            maximum_payload_kg=drone_max_payload_kg,
            battery_capacity_wh=drone_battery_capacity_wh,
            current_battery_wh=drone_current_battery_wh,
            battery_reserve_margin=battery_reserve_margin,
            include_return_trip=include_return_trip,
        )

        for candidate in candidates:
            checker.evaluate_candidate(candidate, payload_weight_kg, weather)

        feasible_candidates = [c for c in candidates if c.is_feasible]
        rejected_list = [
            {"candidate_id": c.candidate_id, "corridor_name": c.corridor_name, "reasons": c.rejection_reasons}
            for c in candidates if not c.is_feasible
        ]

        if not feasible_candidates:
            return OptimizationResult(
                selected_route=None,
                algorithm_name=algorithm_name,
                candidate_count=len(candidates),
                feasible_count=0,
                candidates=candidates,
                rejected_candidates=rejected_list,
                is_feasible=False,
                weights=weights or cls.DEFAULT_WEIGHTS,
                configuration=config,
                summary_message="All generated route candidates were rejected as infeasible.",
            )

        # 4. Multi-Objective Normalization & Scoring
        opt_weights = weights or cls.DEFAULT_WEIGHTS
        w_dist = opt_weights.get("distance", 0.25)
        w_time = opt_weights.get("duration", 0.35)
        w_energy = opt_weights.get("energy", 0.30)
        w_penalty = opt_weights.get("penalty", 0.10)

        # Normalize metrics across candidate set using min-max bounds
        min_dist = min(c.distance_km for c in feasible_candidates)
        max_dist = max(c.distance_km for c in feasible_candidates)
        min_time = min(c.duration_minutes for c in feasible_candidates)
        max_time = max(c.duration_minutes for c in feasible_candidates)
        min_energy = min(c.energy_wh for c in feasible_candidates)
        max_energy = max(c.energy_wh for c in feasible_candidates)
        min_pen = min(c.penalty_score for c in feasible_candidates)
        max_pen = max(c.penalty_score for c in feasible_candidates)

        for c in feasible_candidates:
            norm_dist = (c.distance_km - min_dist) / (max_dist - min_dist) if max_dist > min_dist else 0.0
            norm_time = (c.duration_minutes - min_time) / (max_time - min_time) if max_time > min_time else 0.0
            norm_energy = (c.energy_wh - min_energy) / (max_energy - min_energy) if max_energy > min_energy else 0.0
            norm_pen = (c.penalty_score - min_pen) / (max_pen - min_pen) if max_pen > min_pen else 0.0

            c.objective_score = (
                (w_dist * norm_dist)
                + (w_time * norm_time)
                + (w_energy * norm_energy)
                + (w_penalty * norm_pen)
            )

        # 5. Deterministic Selection & Tie-Breaking
        # If algorithm is SHORTEST_FEASIBLE, sort strictly by distance
        if algorithm_name == "SHORTEST_FEASIBLE":
            feasible_candidates.sort(
                key=lambda c: (c.distance_km, c.energy_wh, c.duration_minutes, c.candidate_id)
            )
        else:
            # Multi-objective: sort by objective_score, then energy, then distance, then deterministic candidate_id
            feasible_candidates.sort(
                key=lambda c: (round(c.objective_score, 4), round(c.energy_wh, 2), round(c.distance_km, 3), c.candidate_id)
            )

        selected = feasible_candidates[0]

        return OptimizationResult(
            selected_route=selected,
            algorithm_name=algorithm_name,
            candidate_count=len(candidates),
            feasible_count=len(feasible_candidates),
            candidates=candidates,
            rejected_candidates=rejected_list,
            is_feasible=True,
            weights=opt_weights,
            configuration=config,
            summary_message=(
                f"Selected optimal corridor '{selected.corridor_name}' ({selected.distance_km:.2f} km, "
                f"{selected.duration_minutes:.1f} min, {selected.energy_wh:.1f} Wh, score: {selected.objective_score:.4f})."
            ),
        )
