import pytest
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User, UserRole
from app.models.delivery_request import (
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
)
from app.models.route import Route, FeasibilityStatus
from app.models.route_waypoint import RouteWaypoint
from app.models.weather_snapshot import WeatherSnapshot, WeatherDataSource


@pytest.fixture
def requester_user(app):
    """Fixture providing a persisted requester user."""
    user = User("Dr. Requester", "doctor@clinic.org", "DoctorPass123!", UserRole.REQUESTER)
    db.session.add(user)
    db.session.commit()
    return user


def test_delivery_request_validation(app, requester_user):
    """Test valid delivery request creation and coordinate bounds."""
    req = DeliveryRequest(
        requester_id=requester_user.id,
        emergency_type=EmergencyType.ANTIVENOM,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=1.8,
        priority=RequestPriority.CRITICAL,
    )
    db.session.add(req)
    db.session.commit()

    assert req.id is not None
    assert req.priority == "CRITICAL"
    assert req.status == "PENDING"
    assert req.requester.id == requester_user.id

    # Test invalid latitude (> 90)
    with pytest.raises(ValueError, match="latitude must be between -90.0 and \\+90.0"):
        DeliveryRequest(
            requester_id=requester_user.id,
            emergency_type=EmergencyType.ANTIVENOM,
            pickup_latitude=95.0,  # Invalid
            pickup_longitude=77.5946,
            destination_latitude=12.9352,
            destination_longitude=77.6245,
            payload_weight_kg=1.8,
        )

    # Test negative payload weight
    with pytest.raises(ValueError, match="strictly positive"):
        DeliveryRequest(
            requester_id=requester_user.id,
            emergency_type=EmergencyType.ANTIVENOM,
            pickup_latitude=12.9716,
            pickup_longitude=77.5946,
            destination_latitude=12.9352,
            destination_longitude=77.6245,
            payload_weight_kg=-0.5,
        )


def test_route_and_waypoints_relationships(app, requester_user):
    """Test route creation, waypoints ordering, and cascade deletion."""
    req = DeliveryRequest(
        requester_id=requester_user.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.0,
    )
    db.session.add(req)
    db.session.commit()

    route = Route(
        delivery_request_id=req.id,
        algorithm_name="DIJKSTRA_V1",
        estimated_distance_km=6.4,
        estimated_duration_minutes=7.5,
        estimated_energy_wh=75.0,
        route_score=0.88,
        feasibility_status=FeasibilityStatus.FEASIBLE,
    )
    db.session.add(route)
    db.session.commit()

    # Add waypoints in reverse sequence to verify ordering
    wp2 = RouteWaypoint(route.id, sequence_number=1, latitude=12.9500, longitude=77.6100, altitude_m=60.0)
    wp1 = RouteWaypoint(route.id, sequence_number=0, latitude=12.9716, longitude=77.5946, altitude_m=50.0)
    db.session.add_all([wp2, wp1])
    db.session.commit()

    # Refresh and check ordering
    fetched_route = db.session.get(Route, route.id)
    assert len(fetched_route.waypoints) == 2
    assert fetched_route.waypoints[0].sequence_number == 0
    assert fetched_route.waypoints[1].sequence_number == 1

    # Verify duplicate sequence number constraint
    dup_wp = RouteWaypoint(route.id, sequence_number=0, latitude=12.9600, longitude=77.6000)
    db.session.add(dup_wp)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    # Verify cascade deletion of routes and waypoints when request is deleted
    db.session.delete(req)
    db.session.commit()
    assert db.session.get(Route, route.id) is None
    assert RouteWaypoint.query.filter_by(route_id=route.id).count() == 0


def test_weather_snapshot_units(app, requester_user):
    """Test weather snapshot logging and explicit units."""
    req = DeliveryRequest(
        requester_id=requester_user.id,
        emergency_type=EmergencyType.DEFIBRILLATOR,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=3.5,
    )
    db.session.add(req)
    db.session.commit()

    weather = WeatherSnapshot(
        delivery_request_id=req.id,
        wind_speed=4.5,       # 4.5 m/s
        precipitation=0.0,    # 0.0 mm/h
        visibility=12.0,      # 12.0 km
        weather_summary="Clear sunny skies",
        source="SIMULATED_TEST",
        simulated_or_live=WeatherDataSource.SIMULATED,
    )
    db.session.add(weather)
    db.session.commit()

    snap_dict = weather.to_dict()
    assert snap_dict["wind_speed_mps"] == 4.5
    assert snap_dict["precipitation_mmh"] == 0.0
    assert snap_dict["visibility_km"] == 12.0
    assert snap_dict["simulated_or_live"] == "SIMULATED"


def test_canonical_request_detail_view_renders_route_optimization_controls(client, app, requester_user):
    """Regression test: verify /requests/<id> routes to canonical delivery.view_detail with full optimization controls."""
    operator = User("Operator Chief", "operator.chief@emergency.org", "ChiefPass123!", UserRole.OPERATOR.value)
    db.session.add(operator)
    db.session.commit()

    req = DeliveryRequest(
        requester_id=requester_user.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.442000,
        destination_longitude=78.388000,
        payload_weight_kg=2.0,
        priority=RequestPriority.CRITICAL.value,
    )
    db.session.add(req)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["_fresh"] = True

    resp = client.get(f"/requests/{req.id}")
    assert resp.status_code == 200
    assert b"Calculated Flight Routes" in resp.data
    assert b"Run Route Optimization" in resp.data
    assert b"Back to Requests" in resp.data


def test_simulation_view_by_assignment_error_redirects_to_canonical_detail(client, app, requester_user):
    """Regression test: verify simulation error redirection targets delivery.view_detail rather than broken endpoint."""
    operator = User("Operator Ops", "operator.ops@emergency.org", "OpsPass123!", UserRole.OPERATOR.value)
    from app.models.drone import Drone, DroneStatus
    drone = Drone("UAV-ERR-TEST", "Carrier-X", 5.0, 500.0, 500.0, 60.0, DroneStatus.AVAILABLE.value)
    db.session.add_all([operator, drone])
    db.session.commit()

    req = DeliveryRequest(
        requester_id=requester_user.id,
        emergency_type=EmergencyType.ANTIVENOM.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.442000,
        destination_longitude=78.388000,
        payload_weight_kg=1.5,
        priority=RequestPriority.HIGH.value,
    )
    db.session.add(req)
    db.session.commit()

    route = Route(req.id, "TEST_ALGO", 10.0, 10.0, 60.0, 0.5, FeasibilityStatus.FEASIBLE.value)
    db.session.add(route)
    db.session.commit()

    from app.models.drone_assignment import DroneAssignment, AssignmentStatus
    # Create an ABORTED assignment (cannot be simulated)
    asg = DroneAssignment(req.id, drone.id, route.id, AssignmentStatus.ABORTED.value)
    db.session.add(asg)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = operator.id
        sess["_fresh"] = True

    # Accessing simulation for aborted assignment triggers InvalidAssignmentStateError
    resp = client.get(f"/simulation/assignment/{asg.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/requests/{req.id}" in resp.headers["Location"]


def test_stateless_ml_prediction_csrf_exemption(app):
    """Regression test: verify that stateless POST to /analytics/api/ml-model/predict succeeds with CSRF protection enabled."""
    with app.app_context():
        operator = User("Operator CSRF", "csrf.op@emergency.org", "CsrfPass123!", UserRole.OPERATOR.value)
        db.session.add(operator)
        db.session.commit()
        op_id = operator.id

    orig_csrf = app.config.get("WTF_CSRF_ENABLED", False)
    try:
        app.config["WTF_CSRF_ENABLED"] = True
        test_client = app.test_client()

        with test_client.session_transaction() as sess:
            sess["user_id"] = op_id
            sess["_fresh"] = True

        payload = {
            "distance_km": 12.0,
            "payload_weight_kg": 2.0,
            "wind_speed_mps": 3.0,
            "cruise_speed_kmh": 60.0,
        }
        # Send POST without CSRF token
        resp = test_client.post("/analytics/api/ml-model/predict", json=payload)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
    finally:
        app.config["WTF_CSRF_ENABLED"] = orig_csrf

