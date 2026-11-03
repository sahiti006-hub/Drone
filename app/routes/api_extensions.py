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
