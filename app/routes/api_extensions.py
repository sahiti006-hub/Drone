"""API extensions for notifications, admin pricing configuration, and weather scenario injection."""

from decimal import Decimal
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from app.extensions import db, csrf
from app.models.user import UserRole
from app.models.pricing_configuration import PricingConfiguration
from app.services.auth_service import AuthService, login_required, role_required
from app.services.notification_service import NotificationService
from app.services.pricing_service import PricingService
from app.services.weather_intelligence_service import WeatherIntelligenceService

api_ext_bp = Blueprint("api_ext", __name__)


# ==============================================================================
# IN-APP NOTIFICATIONS API
# ==============================================================================

@api_ext_bp.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    """Retrieve recent notifications and unread count for current user."""
    user = AuthService.get_current_user()
    limit = int(request.args.get("limit", 20))
    unread_only = request.args.get("unread_only", "false").lower() == "true"

    notifications = NotificationService.get_notifications_for_user(
        user_id=user.id,
        user_role=user.role,
        limit=limit,
        unread_only=unread_only,
    )
    unread_count = NotificationService.get_unread_count(user_id=user.id, user_role=user.role)

    return jsonify({
        "status": "success",
        "unread_count": unread_count,
        "notifications": [n.to_dict() for n in notifications],
    }), 200


@api_ext_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id: int):
    """Mark single notification as read."""
    user = AuthService.get_current_user()
    success = NotificationService.mark_as_read(notification_id=notification_id, user_id=user.id)
    return jsonify({"status": "success" if success else "not_found"}), 200


@api_ext_bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read for current user."""
    user = AuthService.get_current_user()
    count = NotificationService.mark_all_as_read(user_id=user.id, user_role=user.role)
    return jsonify({"status": "success", "marked_read_count": count}), 200


# ==============================================================================
# SAFE DIVERSION LOCATIONS API
# ==============================================================================

@api_ext_bp.route("/api/diversions", methods=["GET"])
@login_required
def list_diversion_locations():
    """Return active safe diversion helipads and clearings."""
    locations = WeatherIntelligenceService.get_or_seed_diversion_locations()
    return jsonify({
        "status": "success",
        "locations": [loc.to_dict() for loc in locations],
    }), 200


# ==============================================================================
# SAVED LOCATIONS API (Uber/Rapido Address Book)
# ==============================================================================

@api_ext_bp.route("/api/saved-locations", methods=["GET", "POST"])
@login_required
def handle_saved_locations():
    """List or create saved delivery locations for current user."""
    user = AuthService.get_current_user()
    from app.models.saved_location import SavedLocation

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        label = data.get("label", "").strip()
        loc_type = data.get("location_type", "HOSPITAL").upper()
        address = data.get("address", "").strip()
        try:
            lat = float(data.get("latitude", 0))
            lng = float(data.get("longitude", 0))
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Valid numerical coordinates are required."}), 400

        if not label or lat == 0 or lng == 0:
            return jsonify({"status": "error", "message": "Label and valid coordinates are required."}), 400

        loc = SavedLocation(
            user_id=user.id,
            label=label,
            location_type=loc_type,
            address=address,
            latitude=Decimal(str(round(lat, 7))),
            longitude=Decimal(str(round(lng, 7))),
        )
        db.session.add(loc)
        db.session.commit()
        return jsonify({"status": "success", "location": loc.to_dict()}), 201

    locations = user.saved_locations.order_by(SavedLocation.created_at.desc()).all()
    # If user has no saved locations yet, initialize with standard regional hospital hubs
    if not locations:
        default_hubs = [
            {"label": "Victoria Hospital Trauma Center", "location_type": "HOSPITAL", "address": "Fort Road, Kalasipalya", "latitude": 12.9634, "longitude": 77.5756},
            {"label": "Bowring & Lady Curzon Hospital", "location_type": "HOSPITAL", "address": "Shivaji Nagar", "latitude": 12.9833, "longitude": 77.6044},
            {"label": "NIMHANS Neurological Center", "location_type": "HOSPITAL", "address": "Hosur Road, Lakkasandra", "latitude": 12.9392, "longitude": 77.5975},
            {"label": "KC General Hospital", "location_type": "HOSPITAL", "address": "5th Cross, Malleswaram", "latitude": 12.9996, "longitude": 77.5709},
        ]
        for dh in default_hubs:
            db.session.add(SavedLocation(
                user_id=user.id,
                label=dh["label"],
                location_type=dh["location_type"],
                address=dh["address"],
                latitude=Decimal(str(dh["latitude"])),
                longitude=Decimal(str(dh["longitude"])),
            ))
        db.session.commit()
        locations = user.saved_locations.all()

    return jsonify({"status": "success", "locations": [loc.to_dict() for loc in locations]}), 200


@api_ext_bp.route("/api/saved-locations/<int:location_id>", methods=["DELETE"])
@login_required
def delete_saved_location(location_id: int):
    """Delete a saved delivery location."""
    user = AuthService.get_current_user()
    from app.models.saved_location import SavedLocation
    loc = db.session.get(SavedLocation, location_id)
    if not loc or loc.user_id != user.id:
        return jsonify({"status": "error", "message": "Location not found or unauthorized."}), 404

    db.session.delete(loc)
    db.session.commit()
    return jsonify({"status": "success"}), 200


# ==============================================================================
# LOCATION AUTOCOMPLETE & GEOCODING API
# ==============================================================================

@api_ext_bp.route("/api/locations/search", methods=["GET"])
def search_locations():
    """Geocode search suggestions with OpenStreetMap Nominatim and trusted local medical hubs."""
    query = request.args.get("q", "").strip().lower()
    if not query or len(query) < 2:
        return jsonify({"status": "success", "results": []}), 200

    # Trusted regional medical landmark directory for instantaneous, offline-resilient matching
    LOCAL_LANDMARKS = [
        {"name": "Victoria Hospital Trauma Center", "address": "Fort Road, Kalasipalya, Bangalore", "lat": 12.9634, "lng": 77.5756, "type": "hospital"},
        {"name": "Bowring & Lady Curzon Hospital", "address": "Shivaji Nagar, Bangalore", "lat": 12.9833, "lng": 77.6044, "type": "hospital"},
        {"name": "NIMHANS Neuro & Psychiatric Center", "address": "Hosur Road, Lakkasandra, Bangalore", "lat": 12.9392, "lng": 77.5975, "type": "hospital"},
        {"name": "KC General Hospital", "address": "5th Cross, Malleswaram, Bangalore", "lat": 12.9996, "lng": 77.5709, "type": "hospital"},
        {"name": "Manipal Hospital Central Hub", "address": "HAL Airport Road, Bangalore", "lat": 12.9592, "lng": 77.6444, "type": "hospital"},
        {"name": "Narayana Health City Hub", "address": "Bommasandra Industrial Area, Bangalore", "lat": 12.8258, "lng": 77.6897, "type": "hospital"},
        {"name": "Central Red Cross Blood Bank", "address": "Race Course Road, Bangalore", "lat": 12.9815, "lng": 77.5840, "type": "blood_bank"},
        {"name": "Indira Gandhi Institute of Child Health", "address": "South Hospital Complex, Bangalore", "lat": 12.9348, "lng": 77.5938, "type": "hospital"},
        {"name": "St. John's Medical College Hospital", "address": "Sarjapur Road, Koramangala, Bangalore", "lat": 12.9304, "lng": 77.6186, "type": "hospital"},
        {"name": "Central Drone Operations Base Depot", "address": "Cubbon Park Airway Hub, Bangalore", "lat": 12.9716, "lng": 77.5946, "type": "depot"},
    ]

    results = []
    for lm in LOCAL_LANDMARKS:
        if query in lm["name"].lower() or query in lm["address"].lower():
            results.append({
                "display_name": f"{lm['name']}, {lm['address']}",
                "name": lm["name"],
                "lat": lm["lat"],
                "lng": lm["lng"],
                "type": lm["type"],
                "source": "verified_medical_hub",
            })

    # Query Nominatim if fewer than 3 matches locally
    if len(results) < 3:
        try:
            import urllib.request
            import urllib.parse
            import json
            encoded = urllib.parse.quote(f"{query}, Bangalore")
            url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=4&addressdetails=1"
            req = urllib.request.Request(url, headers={"User-Agent": "DroneDispatchEmergencySystem/2.0"})
            with urllib.request.urlopen(req, timeout=1.2) as response:
                osm_data = json.loads(response.read().decode())
                for item in osm_data:
                    results.append({
                        "display_name": item.get("display_name"),
                        "name": item.get("name") or item.get("display_name").split(",")[0],
                        "lat": float(item.get("lat")),
                        "lng": float(item.get("lon")),
                        "type": item.get("type", "address"),
                        "source": "openstreetmap_nominatim",
                    })
        except Exception:
            pass

    return jsonify({"status": "success", "results": results[:6]}), 200


# ==============================================================================
# QUICK PRICE & DURATION ESTIMATOR API
# ==============================================================================

@api_ext_bp.route("/api/booking/estimate", methods=["POST"])
def get_quick_estimate():
    """Quick preliminary fare and duration estimate without locking fleet resources."""
    from app.services.route_optimizer import haversine_distance
    from app.services.pricing_service import PricingService
    data = request.get_json(silent=True) or request.form

    try:
        p_lat = float(data.get("pickup_latitude", 0))
        p_lng = float(data.get("pickup_longitude", 0))
        d_lat = float(data.get("destination_latitude", 0))
        d_lng = float(data.get("destination_longitude", 0))
        weight = float(data.get("cargo_weight_kg", 1.0))
        priority = data.get("priority", "HIGH")

        dist_km = haversine_distance(p_lat, p_lng, d_lat, d_lng)
        if dist_km < 0.05:
            return jsonify({"status": "error", "message": "Pickup and destination must be distinct (minimum 50m)."}), 400

        breakdown = PricingService.calculate_price_breakdown(
            flight_distance_km=dist_km,
            cargo_weight_kg=weight,
            priority=priority,
        )
        est_duration_min = max(2.0, round((dist_km / 60.0) * 60.0, 1))

        return jsonify({
            "status": "success",
            "distance_km": round(dist_km, 2),
            "estimated_duration_min": est_duration_min,
            "estimated_price": breakdown["total_price"],
            "price_breakdown": breakdown,
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ==============================================================================
# ADMIN PRICING CONFIGURATION
# ==============================================================================

@api_ext_bp.route("/admin/pricing", methods=["GET", "POST"])
@login_required
@role_required(UserRole.ADMIN)
def manage_pricing():
    """View and adjust live pricing rules (Admin only)."""
    user = AuthService.get_current_user()
    cfg = PricingService.get_or_create_active_config()

    if request.method == "POST":
        try:
            PricingService.update_pricing_config(
                base_fare=request.form.get("base_fare"),
                price_per_km=request.form.get("price_per_km"),
                price_per_kg=request.form.get("price_per_kg"),
                priority_charge_critical=request.form.get("priority_charge_critical"),
                priority_charge_high=request.form.get("priority_charge_high"),
                priority_charge_medium=request.form.get("priority_charge_medium"),
                priority_charge_low=request.form.get("priority_charge_low"),
                service_fee=request.form.get("service_fee"),
                minimum_fare=request.form.get("minimum_fare"),
                maximum_fare=request.form.get("maximum_fare"),
                tax_rate_percent=request.form.get("tax_rate_percent"),
                quote_ttl_minutes=int(request.form.get("quote_ttl_minutes", 15)),
                cancellation_fee_fixed=request.form.get("cancellation_fee_fixed"),
            )
            flash("Pricing configuration updated successfully.", "success")
        except Exception as e:
            flash(f"Failed to update pricing: {str(e)}", "danger")

        return redirect(url_for("api_ext.manage_pricing"))

    return render_template(
        "dashboard/admin_pricing.html",
        current_user=user,
        config=cfg,
    )


# ==============================================================================
# ADMIN WEATHER SCENARIO INJECTION (Demonstrations)
# ==============================================================================

@api_ext_bp.route("/admin/weather", methods=["GET", "POST"])
@login_required
@role_required(UserRole.ADMIN, UserRole.OPERATOR)
def manage_weather_scenario():
    """Configure atmospheric scenarios or inject demonstration hazards."""
    user = AuthService.get_current_user()

    if request.method == "POST":
        action = request.form.get("action", "inject")
        if action == "reset":
            WeatherIntelligenceService.clear_demonstration_scenario()
            flash("Weather scenario reset to standard deterministic simulation.", "info")
        else:
            wind = float(request.form.get("wind_speed_mps", 4.0))
            rain = float(request.form.get("precipitation_mmh", 0.0))
            vis = float(request.form.get("visibility_km", 10.0))
            summary = request.form.get("summary", "Demonstration Scenario")
            segment = request.form.get("affected_segment", "Corridor Central Sector")

            WeatherIntelligenceService.set_demonstration_scenario(
                wind_speed_mps=wind,
                precipitation_mmh=rain,
                visibility_km=vis,
                summary=summary,
                affected_segment=segment,
            )
            flash(f"Weather scenario injected: Wind {wind} m/s, Rain {rain} mm/h.", "warning")

        return redirect(url_for("api_ext.manage_weather_scenario"))

    active_scenario = WeatherIntelligenceService._demonstration_scenario
    diversions = WeatherIntelligenceService.get_or_seed_diversion_locations()

    return render_template(
        "dashboard/admin_weather.html",
        current_user=user,
        active_scenario=active_scenario,
        diversion_locations=diversions,
    )
