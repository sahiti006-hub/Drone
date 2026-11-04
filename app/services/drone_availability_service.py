"""Real-time drone fleet availability evaluation and atomic reservation engine."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from app.extensions import db
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import DroneAssignment, AssignmentStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.drone_quote import DroneQuote
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.weather_intelligence import WeatherClassification
from app.services.route_optimizer import (
    RouteOptimizer,
    CandidateRouteGenerator,
    haversine_distance,
    compute_path_distance,
    estimate_travel_time,
    estimate_energy_consumption,
    Waypoint,
)
from app.services.pricing_service import PricingService, QuoteExpiredError
from app.services.weather_intelligence_service import WeatherIntelligenceService, WeatherConditionSummary


class DroneAvailabilityError(Exception):
    """Base exception for availability calculation."""
    pass


class ConcurrencyLockError(DroneAvailabilityError):
    """Raised when another user has booked or locked the requested drone."""
    pass


class InfeasibleBookingError(DroneAvailabilityError):
    """Raised when a selected drone violates safety or battery constraints upon confirmation."""
    pass


class DroneAvailabilityService:
    """Evaluates fleet eligibility, estimates flight performance, and locks bookings atomically."""

    # Central Depot Base Coordinates (e.g., Central Bangalore Hospital Hub)
    DEFAULT_DEPOT_LAT = 12.9716000
    DEFAULT_DEPOT_LNG = 77.5946000

    @classmethod
    def search_available_drones(
        cls,
        requester_id: int,
        pickup_lat: float,
        pickup_lng: float,
        dest_lat: float,
        dest_lng: float,
        cargo_weight_kg: float,
        cargo_category: str = "EMERGENCY_MEDICINE",
        priority: str = "HIGH",
        delivery_direction: str = "SEND",
        custom_item_name: Optional[str] = None,
        package_size: Optional[str] = "SMALL",
    ) -> Dict[str, Any]:
        """Search and categorize all drones for a proposed delivery mission."""
        cargo_weight = float(cargo_weight_kg)
        if cargo_weight <= 0:
            raise DroneAvailabilityError("Cargo weight must be strictly positive.")

        # Geodesic flight distance
        flight_distance_km = haversine_distance(pickup_lat, pickup_lng, dest_lat, dest_lng)
        if flight_distance_km < 0.05:
            raise DroneAvailabilityError("Pickup and destination locations must be distinct (minimum 50 meters).")

        # Generate candidate 3D flight corridors
        candidate_corridors = CandidateRouteGenerator.generate_candidates(
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
        )
        if not candidate_corridors:
            raise DroneAvailabilityError("Unable to construct airspace flight corridors between specified coordinates.")

        # Select primary candidate corridor (direct corridor default)
        primary_corridor = candidate_corridors[0]

        # Evaluate comprehensive weather intelligence across corridor
        weather_summary: WeatherConditionSummary = WeatherIntelligenceService.evaluate_corridor_weather(
            primary_corridor.waypoints
        )

        all_drones = Drone.query.filter_by(is_decommissioned=False).all()

        available_cards: List[Dict[str, Any]] = []
        limited_cards: List[Dict[str, Any]] = []
        unavailable_cards: List[Dict[str, Any]] = []

        for drone in all_drones:
            card = cls._evaluate_drone_card(
                drone=drone,
                requester_id=requester_id,
                pickup_lat=pickup_lat,
                pickup_lng=pickup_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                cargo_weight_kg=cargo_weight,
                cargo_category=cargo_category,
                priority=priority,
                primary_corridor=primary_corridor,
                weather_summary=weather_summary,
                delivery_direction=delivery_direction,
                custom_item_name=custom_item_name,
                package_size=package_size,
            )

            status = card["availability_status"]
            if status == "AVAILABLE":
                available_cards.append(card)
            elif status == "LIMITED":
                limited_cards.append(card)
            else:
                unavailable_cards.append(card)

        # Sort available and limited cards by total price (ascending)
        available_cards.sort(key=lambda x: x["pricing"]["total_price"])
        limited_cards.sort(key=lambda x: x["pricing"]["total_price"])

        return {
            "search_query": {
                "pickup": {"lat": pickup_lat, "lng": pickup_lng},
                "destination": {"lat": dest_lat, "lng": dest_lng},
                "cargo_weight_kg": cargo_weight,
                "cargo_category": cargo_category,
                "priority": priority,
                "delivery_direction": delivery_direction,
                "custom_item_name": custom_item_name,
                "package_size": package_size,
                "flight_distance_km": round(flight_distance_km, 3),
            },
            "corridors": [c.to_dict() for c in candidate_corridors],
            "weather": weather_summary.to_dict(),
            "summary": {
                "total_drones_evaluated": len(all_drones),
                "available_count": len(available_cards),
                "limited_count": len(limited_cards),
                "unavailable_count": len(unavailable_cards),
            },
            "available_drones": available_cards,
            "limited_drones": limited_cards,
            "unavailable_drones": unavailable_cards,
        }

    @classmethod
    def _evaluate_drone_card(
        cls,
        drone: Drone,
        requester_id: int,
        pickup_lat: float,
        pickup_lng: float,
        dest_lat: float,
        dest_lng: float,
        cargo_weight_kg: float,
        cargo_category: str,
        priority: str,
        primary_corridor: Any,
        weather_summary: WeatherConditionSummary,
        delivery_direction: str = "SEND",
        custom_item_name: Optional[str] = None,
        package_size: Optional[str] = "SMALL",
    ) -> Dict[str, Any]:
        """Compute detailed performance, quote, and feasibility categorization for one drone."""
        unavailability_reasons: List[str] = []
        cautions: List[str] = []

        # 1. Operational status
        if drone.status != DroneStatus.AVAILABLE.value:
            unavailability_reasons.append(f"Drone is currently in '{drone.status}' state.")

        # Check active assignment locks
        active_assignment = DroneAssignment.query.filter_by(
            drone_id=drone.id,
            status=AssignmentStatus.ACTIVE.value,
        ).first()
        if active_assignment:
            unavailability_reasons.append("Drone is actively assigned to another mission.")

        # 2. Payload capacity
        max_payload = float(drone.maximum_payload_kg)
        if cargo_weight_kg > max_payload:
            unavailability_reasons.append(
                f"Cargo mass ({cargo_weight_kg:.2f} kg) exceeds maximum payload ({max_payload:.2f} kg)."
            )

        # 3. Ferry distance & estimated pickup arrival
        drone_base_lat = cls.DEFAULT_DEPOT_LAT
        drone_base_lng = cls.DEFAULT_DEPOT_LNG
        ferry_dist_km = haversine_distance(drone_base_lat, drone_base_lng, pickup_lat, pickup_lng)
        cruise_speed = float(drone.cruise_speed_kmh)
        pickup_time_min = round((ferry_dist_km / cruise_speed) * 60.0 + 1.0, 1)

        # 4. Delivery flight duration & energy consumption
        delivery_dist_km = primary_corridor.distance_km or haversine_distance(pickup_lat, pickup_lng, dest_lat, dest_lng)
        delivery_time_min = estimate_travel_time(
            distance_km=delivery_dist_km,
            cruise_speed_kmh=cruise_speed,
            wind_headwind_mps=weather_summary.max_wind_speed_mps,
        )

        ferry_energy = estimate_energy_consumption(
            distance_km=ferry_dist_km,
            duration_minutes=pickup_time_min,
            payload_weight_kg=0.0,
            cruise_speed_kmh=cruise_speed,
        )
        delivery_energy = estimate_energy_consumption(
            distance_km=delivery_dist_km,
            duration_minutes=delivery_time_min,
            payload_weight_kg=cargo_weight_kg,
            cruise_speed_kmh=cruise_speed,
            include_return_trip=True,
        )
        total_required_energy_wh = ferry_energy + delivery_energy

        # 5. Battery reserve checks
        current_battery = float(drone.current_battery_wh)
        battery_capacity = float(drone.battery_capacity_wh)
        battery_pct = round((current_battery / battery_capacity) * 100.0, 1) if battery_capacity > 0 else 0.0

        # Mandatory 15% non-depletable reserve
        usable_battery_wh = current_battery * 0.85
        if total_required_energy_wh > usable_battery_wh:
            unavailability_reasons.append(
                f"Insufficient battery: mission requires {total_required_energy_wh:.1f} Wh "
                f"(usable: {usable_battery_wh:.1f} Wh with mandatory 15% reserve)."
            )
        else:
            remaining_after = current_battery - total_required_energy_wh
            remaining_ratio = remaining_after / battery_capacity
            if remaining_ratio < 0.22:
                cautions.append(f"Tight battery margin: estimated arrival reserve is {remaining_ratio*100:.1f}%.")

        # 6. Weather evaluation
        if weather_summary.classification == WeatherClassification.RED:
            unavailability_reasons.append(
                f"Severe atmospheric hazard along corridor: {weather_summary.warning_description}"
            )
        elif weather_summary.classification == WeatherClassification.YELLOW:
            cautions.append(
                f"Weather Advisory: {weather_summary.warning_description}"
            )

        if ferry_dist_km > 6.0:
            cautions.append(f"Extended ferry distance ({ferry_dist_km:.1f} km from depot).")

        # 7. Generate Price Quote
        price_breakdown = PricingService.calculate_price_breakdown(
            flight_distance_km=delivery_dist_km,
            cargo_weight_kg=cargo_weight_kg,
            priority=priority,
        )

        # Persist quote record for future booking reference
        quote = PricingService.generate_and_persist_quote(
            requester_id=requester_id,
            drone_id=drone.id,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            cargo_weight_kg=cargo_weight_kg,
            cargo_category=cargo_category,
            priority=priority,
            corridor_name=primary_corridor.corridor_name,
            flight_distance_km=delivery_dist_km,
            ferry_distance_km=ferry_dist_km,
            estimated_pickup_duration_min=pickup_time_min,
            estimated_delivery_duration_min=delivery_time_min,
            estimated_energy_wh=total_required_energy_wh,
            weather_classification=weather_summary.classification.value,
            delivery_direction=delivery_direction or "SEND",
            custom_item_name=custom_item_name,
            package_size=package_size or "SMALL",
        )

        # Determine categorization
        if unavailability_reasons:
            category = "UNAVAILABLE"
            bookable = False
        elif cautions:
            category = "LIMITED"
            bookable = True
        else:
            category = "AVAILABLE"
            bookable = True

        return {
            "drone_id": drone.id,
            "drone_code": drone.drone_code,
            "drone_model": drone.model_name,
            "maximum_payload_kg": max_payload,
            "battery_capacity_wh": battery_capacity,
            "current_battery_wh": current_battery,
            "battery_percent": battery_pct,
            "cruise_speed_kmh": cruise_speed,
            "ferry_distance_km": round(ferry_dist_km, 2),
            "estimated_pickup_time_min": pickup_time_min,
            "flight_distance_km": round(delivery_dist_km, 2),
            "estimated_delivery_duration_min": delivery_time_min,
            "estimated_energy_wh": round(total_required_energy_wh, 1),
            "corridor_name": primary_corridor.corridor_name,
            "weather_status": weather_summary.classification.value,
            "delivery_direction": delivery_direction or "SEND",
            "custom_item_name": custom_item_name,
            "package_size": package_size or "SMALL",
            "availability_status": category,
            "is_bookable": bookable,
            "rejection_reasons": unavailability_reasons,
            "cautions": cautions,
            "quote_id": quote.id,
            "quote_reference": quote.quote_reference,
            "pricing": price_breakdown,
        }

    @classmethod
    def confirm_and_lock_booking(
        cls,
        quote_id: int,
        requester_id: int,
        weather_acknowledged: bool = False,
        notes: Optional[str] = None,
        delivery_direction: Optional[str] = None,
        collection_contact_name: Optional[str] = None,
        collection_contact_phone: Optional[str] = None,
        collection_readiness: Optional[str] = None,
        collection_instructions: Optional[str] = None,
        custom_item_name: Optional[str] = None,
        custom_item_description: Optional[str] = None,
        package_size: Optional[str] = None,
        package_dimensions: Optional[str] = None,
        package_count: Optional[int] = 1,
        handling_instructions: Optional[str] = None,
        pickup_contact_name: Optional[str] = None,
        pickup_contact_phone: Optional[str] = None,
        delivery_contact_name: Optional[str] = None,
        delivery_contact_phone: Optional[str] = None,
        special_instructions: Optional[str] = None,
    ) -> DroneBooking:
        """Atomically confirm booking, lock drone, and instantiate delivery request.

        Concurrency & ACID Guarantees:
        - Validates quote expiration inside transaction.
        - Obtains row-level or verified active locks on the Drone.
        - Prevents two requesters from booking the same drone simultaneously.
        - Updates drone state to RESERVED.
        - Re-evaluates weather safety.
        """
        try:
            # 1. Fetch and validate quote
            quote = db.session.get(DroneQuote, quote_id)
            if not quote:
                raise DroneAvailabilityError(f"Quote #{quote_id} not found.")

            if quote.requester_id != requester_id:
                raise DroneAvailabilityError("Quote does not belong to authenticated requester.")

            if quote.is_accepted:
                raise DroneAvailabilityError("This quote has already been accepted.")

            if quote.is_expired():
                raise QuoteExpiredError(f"Quote #{quote.quote_reference} has expired. Please search again.")

            # 2. Acquire Drone Lock and verify availability
            drone = db.session.query(Drone).filter_by(id=quote.drone_id).with_for_update().first()
            if not drone:
                drone = db.session.get(Drone, quote.drone_id)

            if not drone or drone.is_decommissioned:
                raise InfeasibleBookingError(f"Drone is decommissioned or unavailable.")

            if drone.status != DroneStatus.AVAILABLE.value:
                raise ConcurrencyLockError(
                    f"Drone {drone.drone_code} was just claimed by another mission (current status: {drone.status}). "
                    f"Please select another available drone."
                )

            # Check for existing active assignment
            active_assign = DroneAssignment.query.filter_by(
                drone_id=drone.id,
                status=AssignmentStatus.ACTIVE.value,
            ).first()
            if active_assign:
                raise ConcurrencyLockError(f"Drone {drone.drone_code} has an active flight assignment.")

            # 3. Weather check before booking confirmation
            # Sample weather at pickup and destination
            pickup_obs = WeatherIntelligenceService.sample_weather_at_coordinate(
                float(quote.pickup_latitude), float(quote.pickup_longitude)
            )
            dest_obs = WeatherIntelligenceService.sample_weather_at_coordinate(
                float(quote.destination_latitude), float(quote.destination_longitude)
            )

            p_class = WeatherClassification(pickup_obs.classification)
            d_class = WeatherClassification(dest_obs.classification)

            if p_class == WeatherClassification.RED or d_class == WeatherClassification.RED:
                raise InfeasibleBookingError(
                    "Atmospheric conditions have deteriorated to RED. Mandatory safety policy blocks dispatch."
                )

            is_caution = (p_class == WeatherClassification.YELLOW or d_class == WeatherClassification.YELLOW)
            if is_caution and not weather_acknowledged:
                raise InfeasibleBookingError(
                    "Weather conditions have entered the YELLOW caution band. "
                    "Requester must acknowledge the weather advisory before confirmation."
                )

            # Determine effective delivery direction and item details
            eff_direction = (delivery_direction or getattr(quote, "delivery_direction", None) or "SEND").upper()
            eff_item_name = custom_item_name or getattr(quote, "custom_item_name", None)
            eff_pkg_size = package_size or getattr(quote, "package_size", None) or "SMALL"

            # 4. Create and link DeliveryRequest
            from app.models.delivery_request import DeliveryRequest, RequestStatus, RequestPriority
            from app.models.request_activity import RequestActivity
            delivery_req = DeliveryRequest(
                requester_id=requester_id,
                emergency_type=quote.cargo_category,
                pickup_latitude=float(quote.pickup_latitude),
                pickup_longitude=float(quote.pickup_longitude),
                destination_latitude=float(quote.destination_latitude),
                destination_longitude=float(quote.destination_longitude),
                payload_weight_kg=float(quote.cargo_weight_kg),
                priority=quote.priority,
                delivery_direction=eff_direction,
                description=notes or f"Smart Drone Booking [{quote.quote_reference}]",
                custom_item_name=eff_item_name,
                package_dimensions=package_dimensions,
                package_count=package_count or 1,
                handling_instructions=handling_instructions,
                pickup_contact_name=pickup_contact_name,
                pickup_contact_phone=pickup_contact_phone,
                delivery_contact_name=delivery_contact_name or collection_contact_name,
                delivery_contact_phone=delivery_contact_phone or collection_contact_phone,
                special_instructions=special_instructions or collection_instructions,
            )
            delivery_req.status = RequestStatus.ROUTE_CALCULATED.value
            db.session.add(delivery_req)
            db.session.flush()

            db.session.add(RequestActivity(
                delivery_request_id=delivery_req.id,
                actor_id=requester_id,
                actor_role="REQUESTER",
                from_status=None,
                to_status=RequestStatus.CONFIRMED.value,
                action="BOOKING_RESERVED",
                reason=f"Booking confirmed against Quote #{quote.quote_reference}.",
            ))

            # Persist candidate 3D flight routes and waypoints for dispatch execution
            candidate_corridors = CandidateRouteGenerator.generate_candidates(
                pickup_lat=float(quote.pickup_latitude),
                pickup_lng=float(quote.pickup_longitude),
                dest_lat=float(quote.destination_latitude),
                dest_lng=float(quote.destination_longitude),
            )
            for c in candidate_corridors:
                route_entity = Route(
                    delivery_request_id=delivery_req.id,
                    algorithm_name=f"OPTIMIZED_{c.corridor_name}",
                    estimated_distance_km=c.distance_km,
                    estimated_duration_minutes=c.duration_minutes,
                    estimated_energy_wh=c.energy_wh,
                    route_score=1.0,
                    feasibility_status=FeasibilityStatus.FEASIBLE.value,
                )
                db.session.add(route_entity)
                db.session.flush()

                for idx, wp in enumerate(c.waypoints):
                    db.session.add(RouteWaypoint(
                        route_id=route_entity.id,
                        sequence_number=idx,
                        latitude=wp.latitude,
                        longitude=wp.longitude,
                        altitude_m=wp.altitude_m,
                    ))

            # 5. Lock Drone into RESERVED status
            drone.status = DroneStatus.RESERVED.value

            # 6. Mark Quote accepted
            quote.is_accepted = True

            # 7. Create DroneBooking record
            booking = DroneBooking(
                requester_id=requester_id,
                drone_id=drone.id,
                quote_id=quote.id,
                delivery_request_id=delivery_req.id,
                status=BookingStatus.CONFIRMED.value,
                accepted_price=quote.total_price,
                final_price=quote.total_price,
                weather_condition_at_booking="YELLOW" if is_caution else "GREEN",
                weather_acknowledged_by_user=weather_acknowledged,
                delivery_direction=eff_direction,
                custom_item_name=eff_item_name,
                custom_item_description=custom_item_description,
                package_size=eff_pkg_size,
                collection_readiness=collection_readiness,
                collection_contact_name=collection_contact_name,
                collection_contact_phone=collection_contact_phone,
                collection_instructions=collection_instructions,
                notes=notes,
            )
            db.session.add(booking)
            db.session.commit()

            # Create Notification
            from app.services.notification_service import NotificationService
            NotificationService.create_notification(
                user_id=requester_id,
                booking_id=booking.id,
                delivery_request_id=delivery_req.id,
                notification_type="BOOKING_CONFIRMED",
                title=f"Booking Confirmed [{booking.booking_reference}]",
                message=f"Drone {drone.drone_code} reserved for {quote.cargo_category} delivery. Total: ₹{float(booking.accepted_price):.2f}.",
                severity="SUCCESS",
            )

            return booking

        except Exception:
            db.session.rollback()
            raise
