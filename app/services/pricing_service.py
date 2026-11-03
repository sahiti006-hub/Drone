"""Dynamic pricing engine for simulated emergency drone delivery."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from app.extensions import db
from app.models.pricing_configuration import PricingConfiguration
from app.models.drone_quote import DroneQuote


class PricingServiceError(Exception):
    """Base exception for pricing calculation errors."""
    pass


class QuoteExpiredError(PricingServiceError):
    """Raised when attempting to confirm an expired quote."""
    pass


class PricingService:
    """Configurable pricing calculation and immutable quote management."""

    DEFAULT_CONFIG_NAME = "DEFAULT"

    @classmethod
    def get_or_create_active_config(cls) -> PricingConfiguration:
        """Retrieve the active pricing configuration or initialize defaults."""
        config = PricingConfiguration.query.filter_by(is_active=True).first()
        if not config:
            config = PricingConfiguration(
                name=cls.DEFAULT_CONFIG_NAME,
                base_fare=Decimal("100.00"),
                price_per_km=Decimal("25.00"),
                price_per_kg=Decimal("15.00"),
                priority_charge_critical=Decimal("150.00"),
                priority_charge_high=Decimal("80.00"),
                priority_charge_medium=Decimal("40.00"),
                priority_charge_low=Decimal("0.00"),
                service_fee=Decimal("30.00"),
                minimum_fare=Decimal("150.00"),
                maximum_fare=Decimal("5000.00"),
                tax_rate_percent=Decimal("5.00"),
                quote_ttl_minutes=15,
                cancellation_fee_fixed=Decimal("50.00"),
                cancellation_fee_percent=Decimal("10.00"),
                is_active=True,
            )
            db.session.add(config)
            db.session.commit()
        return config

    @classmethod
    def calculate_price_breakdown(
        cls,
        flight_distance_km: float,
        cargo_weight_kg: float,
        priority: str = "HIGH",
        config: Optional[PricingConfiguration] = None,
    ) -> Dict[str, Any]:
        """Compute transparent itemized price breakdown using active configuration rules."""
        cfg = config or cls.get_or_create_active_config()

        dist_d = Decimal(str(round(flight_distance_km, 3)))
        weight_d = Decimal(str(round(cargo_weight_kg, 2)))

        base_fare = Decimal(str(cfg.base_fare))
        price_per_km = Decimal(str(cfg.price_per_km))
        price_per_kg = Decimal(str(cfg.price_per_kg))

        distance_charge = (dist_d * price_per_km).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        weight_charge = (weight_d * price_per_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        prio_upper = (priority or "HIGH").upper()
        if prio_upper == "CRITICAL":
            priority_charge = Decimal(str(cfg.priority_charge_critical))
        elif prio_upper == "HIGH":
            priority_charge = Decimal(str(cfg.priority_charge_high))
        elif prio_upper == "MEDIUM":
            priority_charge = Decimal(str(cfg.priority_charge_medium))
        else:
            priority_charge = Decimal(str(cfg.priority_charge_low))

        service_fee = Decimal(str(cfg.service_fee))
        
        subtotal = base_fare + distance_charge + weight_charge + priority_charge + service_fee

        min_fare = Decimal(str(cfg.minimum_fare))
        max_fare = Decimal(str(cfg.maximum_fare))
        clamped_subtotal = max(min_fare, min(max_fare, subtotal))

        tax_rate = Decimal(str(cfg.tax_rate_percent))
        tax_amount = (clamped_subtotal * (tax_rate / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_price = clamped_subtotal + tax_amount

        return {
            "base_fare": float(base_fare),
            "distance_charge": float(distance_charge),
            "weight_charge": float(weight_charge),
            "priority_charge": float(priority_charge),
            "service_fee": float(service_fee),
            "subtotal": float(clamped_subtotal),
            "tax_rate_percent": float(tax_rate),
            "tax_amount": float(tax_amount),
            "total_price": float(total_price),
            "is_minimum_applied": clamped_subtotal == min_fare and subtotal < min_fare,
            "is_maximum_applied": clamped_subtotal == max_fare and subtotal > max_fare,
        }

    @classmethod
    def generate_and_persist_quote(
        cls,
        requester_id: int,
        drone_id: int,
        pickup_lat: float,
        pickup_lng: float,
        dest_lat: float,
        dest_lng: float,
        cargo_weight_kg: float,
        cargo_category: str,
        priority: str,
        corridor_name: str,
        flight_distance_km: float,
        ferry_distance_km: float,
        estimated_pickup_duration_min: float,
        estimated_delivery_duration_min: float,
        estimated_energy_wh: float,
        weather_classification: str = "GREEN",
    ) -> DroneQuote:
        """Create and persist an immutable quote with strict time-to-live."""
        cfg = cls.get_or_create_active_config()
        breakdown = cls.calculate_price_breakdown(
            flight_distance_km=flight_distance_km,
            cargo_weight_kg=cargo_weight_kg,
            priority=priority,
            config=cfg,
        )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=cfg.quote_ttl_minutes)

        quote = DroneQuote(
            requester_id=requester_id,
            drone_id=drone_id,
            pricing_config_id=cfg.id,
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lng,
            destination_latitude=dest_lat,
            destination_longitude=dest_lng,
            cargo_weight_kg=cargo_weight_kg,
            cargo_category=cargo_category,
            priority=priority.upper(),
            corridor_name=corridor_name,
            flight_distance_km=flight_distance_km,
            ferry_distance_km=ferry_distance_km,
            estimated_pickup_duration_min=estimated_pickup_duration_min,
            estimated_delivery_duration_min=estimated_delivery_duration_min,
            estimated_energy_wh=estimated_energy_wh,
            weather_classification=weather_classification,
            base_fare=Decimal(str(breakdown["base_fare"])),
            distance_charge=Decimal(str(breakdown["distance_charge"])),
            weight_charge=Decimal(str(breakdown["weight_charge"])),
            priority_charge=Decimal(str(breakdown["priority_charge"])),
            service_fee=Decimal(str(breakdown["service_fee"])),
            tax_amount=Decimal(str(breakdown["tax_amount"])),
            total_price=Decimal(str(breakdown["total_price"])),
            expires_at=expires_at,
            is_accepted=False,
        )
        db.session.add(quote)
        db.session.commit()
        return quote

    @classmethod
    def validate_quote(cls, quote_id: int) -> DroneQuote:
        """Validate quote existence and verify expiry."""
        quote = db.session.get(DroneQuote, quote_id)
        if not quote:
            raise PricingServiceError(f"Quote #{quote_id} not found.")

        if quote.is_expired():
            raise QuoteExpiredError(
                f"Quote #{quote.quote_reference} expired at {quote.expires_at.isoformat()}. "
                f"Please refresh search results to obtain current pricing."
            )
        return quote

    @classmethod
    def update_pricing_config(cls, **kwargs) -> PricingConfiguration:
        """Update active pricing parameters (Admin only)."""
        cfg = cls.get_or_create_active_config()
        for key, val in kwargs.items():
            if hasattr(cfg, key) and val is not None:
                if isinstance(getattr(cfg, key), Decimal):
                    setattr(cfg, key, Decimal(str(val)))
                else:
                    setattr(cfg, key, val)
        db.session.commit()
        return cfg
