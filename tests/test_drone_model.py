import pytest
from app.extensions import db
from app.models.drone import Drone, DroneStatus
from app.services.drone_service import (
    DroneService,
    InvalidDroneTransitionError,
    DroneServiceError,
    DroneNotFoundError,
)


def test_drone_creation_validation(app):
    """Test valid drone creation and parameter validation."""
    drone = Drone(
        drone_code="DRONE-TEST-01",
        model_name="SkyMedic Hexacopter",
        maximum_payload_kg=5.0,
        battery_capacity_wh=800.0,
        current_battery_wh=600.0,
        cruise_speed_kmh=65.0,
    )
    assert drone.drone_code == "DRONE-TEST-01"
    assert drone.battery_percentage == 75.0
    assert drone.status == DroneStatus.AVAILABLE.value

    # Negative payload validation
    with pytest.raises(ValueError, match="payload must be greater than zero"):
        Drone("BAD-01", "Model", -1.0, 500.0)

    # Battery exceeded validation
    with pytest.raises(ValueError, match="between 0 and maximum battery"):
        Drone("BAD-02", "Model", 5.0, 500.0, current_battery_wh=600.0)


def test_drone_state_transitions(app):
    """Test allowed and disallowed status transitions in the state machine."""
    drone = DroneService.register_drone(
        drone_code="DRONE-SM-01",
        model_name="Test Flyer",
        maximum_payload_kg=4.0,
        battery_capacity_wh=600.0,
    )
    assert drone.status == DroneStatus.AVAILABLE.value

    # Legal: AVAILABLE -> RESERVED
    DroneService.update_drone_status(drone.id, DroneStatus.RESERVED)
    assert drone.status == DroneStatus.RESERVED.value

    # Legal: RESERVED -> IN_TRANSIT
    DroneService.update_drone_status(drone.id, DroneStatus.IN_TRANSIT)
    assert drone.status == DroneStatus.IN_TRANSIT.value

    # Legal: IN_TRANSIT -> CHARGING
    DroneService.update_drone_status(drone.id, DroneStatus.CHARGING)
    assert drone.status == DroneStatus.CHARGING.value

    # Illegal: CHARGING -> IN_TRANSIT directly (must go to AVAILABLE first)
    with pytest.raises(InvalidDroneTransitionError):
        DroneService.update_drone_status(drone.id, DroneStatus.IN_TRANSIT)


def test_drone_decommission_preserves_history(app):
    """Decommissioning marks the drone inactive without deleting audit records."""
    drone = DroneService.register_drone(
        drone_code="DRONE-RETIRE-01",
        model_name="Retiree",
        maximum_payload_kg=3.0,
        battery_capacity_wh=400.0,
    )
    decommissioned = DroneService.decommission_drone(drone.id)
    assert decommissioned.is_decommissioned is True
    assert decommissioned.status == DroneStatus.MAINTENANCE.value

    # Trying to change status of a decommissioned drone must fail
    with pytest.raises(DroneServiceError, match="decommissioned"):
        DroneService.update_drone_status(drone.id, DroneStatus.AVAILABLE)
