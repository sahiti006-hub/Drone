import pytest
from app.models.delivery_request import (
    CargoCategory,
    CARGO_CATEGORY_REGISTRY,
    normalize_cargo_category,
    DeliveryRequest,
    EmergencyType,
    RequestPriority
)
from app.models.user import User, UserRole
from app.services.delivery_service import DeliveryService
from app.extensions import db


def test_cargo_category_registry_completeness():
    """Ensure all 9 universal delivery categories are properly defined and configured."""
    expected_categories = [
        "MEDICAL_HEALTHCARE",
        "FOOD_GROCERIES",
        "DOCUMENTS_OFFICE",
        "ELECTRONICS_TECH",
        "INDUSTRIAL_SUPPLIES",
        "EMERGENCY_RELIEF",
        "PERSONAL_HOUSEHOLD",
        "AGRICULTURE_RURAL",
        "CUSTOM_DELIVERY"
    ]
    for cat in expected_categories:
        assert cat in CARGO_CATEGORY_REGISTRY
        config = CARGO_CATEGORY_REGISTRY[cat]
        assert "name" in config
        assert "icon" in config
        assert "max_weight_kg" in config
        assert config["max_weight_kg"] > 0
        assert "safety_notes" in config


def test_cargo_category_normalization_and_legacy_compatibility():
    """Ensure all legacy categories map transparently to universal categories."""
    assert normalize_cargo_category("EMERGENCY_MEDICINE") == "MEDICAL_HEALTHCARE"
    assert normalize_cargo_category("BLOOD_SUPPLY") == "MEDICAL_HEALTHCARE"
    assert normalize_cargo_category("ANTIVENOM") == "MEDICAL_HEALTHCARE"
    assert normalize_cargo_category("FOOD_ESSENTIALS") == "FOOD_GROCERIES"
    assert normalize_cargo_category("DOCUMENTS_PARCELS") == "DOCUMENTS_OFFICE"
    assert normalize_cargo_category("ELECTRONICS") == "ELECTRONICS_TECH"
    assert normalize_cargo_category("DEFIBRILLATOR") == "EMERGENCY_RELIEF"
    assert normalize_cargo_category("DISASTER_RELIEF") == "EMERGENCY_RELIEF"
    assert normalize_cargo_category("CUSTOM_ITEM") == "CUSTOM_DELIVERY"

    # Universal categories pass through untouched
    assert normalize_cargo_category("INDUSTRIAL_SUPPLIES") == "INDUSTRIAL_SUPPLIES"
    assert normalize_cargo_category("AGRICULTURE_RURAL") == "AGRICULTURE_RURAL"
    assert normalize_cargo_category("PERSONAL_HOUSEHOLD") == "PERSONAL_HOUSEHOLD"


def test_universal_delivery_request_creation(app):
    """Test creating deliveries across non-medical categories with extended payload metadata."""
    with app.app_context():
        user = User.query.filter_by(email="universal.tester@example.com").first()
        if not user:
            user = User("Universal Requester", "universal.tester@example.com", "Password123!", UserRole.REQUESTER.value)
            db.session.add(user)
            db.session.commit()

        # 1. Industrial Supplies delivery
        req1 = DeliveryService.create_request(
            requester_id=user.id,
            emergency_type="INDUSTRIAL_SUPPLIES",
            pickup_latitude=12.9716,
            pickup_longitude=77.5946,
            destination_latitude=13.0100,
            destination_longitude=77.6300,
            payload_weight_kg=4.0,
            priority="HIGH",
            custom_item_name="Precision CNC Titanium Drill Bit",
            package_dimensions="20x10x8",
            package_count=2,
            handling_instructions="Handle with care - sharp edges",
            pickup_contact_name="Warehouse Foreman Suresh",
            pickup_contact_phone="+919876543210",
            delivery_contact_name="Site Engineer Ramesh",
            delivery_contact_phone="+919876543211",
            special_instructions="Deliver to Gate 4 Workshop"
        )
        assert req1 is not None
        assert req1.cargo_category == "INDUSTRIAL_SUPPLIES"
        assert req1.custom_item_name == "Precision CNC Titanium Drill Bit"
        assert req1.package_count == 2
        assert req1.package_dimensions == "20x10x8"
        assert req1.request_reference.startswith("REQ-")

        # 2. Maximum payload violation check
        with pytest.raises(ValueError, match="exceeds maximum permitted payload"):
            DeliveryService.create_request(
                requester_id=user.id,
                emergency_type="DOCUMENTS_OFFICE",
                pickup_latitude=12.9716,
                pickup_longitude=77.5946,
                destination_latitude=13.0100,
                destination_longitude=77.6300,
                payload_weight_kg=15.0  # Max for documents is 3.0 kg
            )
