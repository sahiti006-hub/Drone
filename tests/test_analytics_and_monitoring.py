"""Tests for analytics service, operational dashboard metrics, delivery monitoring, and CSV export."""

import io
import csv
import pytest
from app.extensions import db
from app.models.analysis_log import AnalysisLog, EvaluationStatus
from app.models.delivery_request import DeliveryRequest, EmergencyType, RequestPriority, RequestStatus
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.route_waypoint import RouteWaypoint
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.user import User, UserRole
from app.services.analytics_service import AnalyticsService


@pytest.fixture
def analytics_dataset(app):
    """Sets up a comprehensive dataset with multiple users, drones, requests, routes, simulations, and logs."""
    # Users
    admin = User("Admin User", "admin@emergency.org", "Pass123456!", UserRole.ADMIN.value)
    operator = User("Operator User", "op@emergency.org", "Pass123456!", UserRole.OPERATOR.value)
    req_user1 = User("Dr. Requester 1", "req1@cityhospital.org", "Pass123456!", UserRole.REQUESTER.value)
    req_user2 = User("Dr. Requester 2", "req2@traumacenter.org", "Pass123456!", UserRole.REQUESTER.value)
    db.session.add_all([admin, operator, req_user1, req_user2])
    db.session.commit()

    # Drones in various states
    drone_avail = Drone("DRONE-01", "Model A", 5.0, 1000.0, 1000.0, 60.0, DroneStatus.AVAILABLE.value)
    drone_transit = Drone("DRONE-02", "Model B", 6.0, 1200.0, 1100.0, 65.0, DroneStatus.IN_TRANSIT.value)
    drone_maint = Drone("DRONE-03", "Model C", 4.0, 800.0, 700.0, 55.0, DroneStatus.MAINTENANCE.value)
    drone_charge = Drone("DRONE-04", "Model D", 5.0, 1000.0, 150.0, 60.0, DroneStatus.CHARGING.value)
    db.session.add_all([drone_avail, drone_transit, drone_maint, drone_charge])
    db.session.commit()

    # Delivery Requests for Requester 1
    req1 = DeliveryRequest(
        requester_id=req_user1.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.5,
        priority=RequestPriority.CRITICAL.value,
        status=RequestStatus.IN_TRANSIT.value,
        description="Priority Blood Delivery Unit",
    )
    req2 = DeliveryRequest(
        requester_id=req_user1.id,
        emergency_type=EmergencyType.ANTIVENOM.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9100,
        destination_longitude=77.6400,
        payload_weight_kg=1.2,
        priority=RequestPriority.HIGH.value,
        status=RequestStatus.DELIVERED.value,
        description="Antivenom Serum Vial",
    )
    # Delivery Request for Requester 2
    req3 = DeliveryRequest(
        requester_id=req_user2.id,
        emergency_type=EmergencyType.DEFIBRILLATOR.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9500,
        destination_longitude=77.6100,
        payload_weight_kg=3.8,
        priority=RequestPriority.LOW.value,
        status=RequestStatus.PENDING.value,
        description="AED Defibrillator unit",
    )
    req4 = DeliveryRequest(
        requester_id=req_user2.id,
        emergency_type=EmergencyType.SURGICAL_KIT.value,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9200,
        destination_longitude=77.6500,
        payload_weight_kg=4.0,
        priority=RequestPriority.MEDIUM.value,
        status=RequestStatus.CANCELLED.value,
        description="Surgical supplies cancelled by hospital",
    )
    db.session.add_all([req1, req2, req3, req4])
    db.session.commit()

    # Routes (Baseline vs Optimizer & Infeasible)
    route_base1 = Route(
        delivery_request_id=req1.id,
        algorithm_name="BASELINE:CORRIDOR_DIRECT",
        estimated_distance_km=5.8,
        estimated_duration_minutes=6.2,
        estimated_energy_wh=62.0,
        feasibility_status=FeasibilityStatus.FEASIBLE.value,
    )
    route_opt1 = Route(
        delivery_request_id=req1.id,
        algorithm_name="WEIGHTED_OPTIMIZER:CORRIDOR_NORTH",
        estimated_distance_km=6.1,
        estimated_duration_minutes=6.4,
        estimated_energy_wh=64.0,
        feasibility_status=FeasibilityStatus.FEASIBLE.value,
    )
    route_infeas = Route(
        delivery_request_id=req1.id,
        algorithm_name="BASELINE:CORRIDOR_HIGH_ALTITUDE",
        estimated_distance_km=6.8,
        estimated_duration_minutes=7.5,
        estimated_energy_wh=85.0,
        feasibility_status=FeasibilityStatus.INFEASIBLE.value,
        rejection_reason="Battery reserve margin breached; Wind speed limit exceeded",
    )
    db.session.add_all([route_base1, route_opt1, route_infeas])
    db.session.commit()

    # Assignment & Simulation Run
    asg1 = DroneAssignment(
        delivery_request_id=req1.id,
        drone_id=drone_transit.id,
        route_id=route_opt1.id,
        status=AssignmentStatus.ACTIVE.value,
    )
    db.session.add(asg1)
    db.session.commit()

    sim1 = SimulationRun(
        run_code="SIM-TEST-ANALYTICS-01",
        parameters={"test": True},
        status=SimulationStatus.RUNNING.value,
        assignment_id=asg1.id,
        total_sim_seconds=360.0,
        remaining_distance_km=3.2,
        current_battery_wh=1150.0,
    )
    sim1.distance_covered_km = 2.9
    sim1.current_progress_percent = 47.5
    db.session.add(sim1)
    db.session.commit()

    # Analysis Log
    log1 = AnalysisLog(
        simulation_run_id=sim1.id,
        algorithm_name="WEIGHTED_OPTIMIZER",
        scenario_reference="REQ1_URGENT",
        predicted_metrics={"distance_km": 6.1, "duration_min": 6.4, "energy_wh": 64.0},
        actual_simulated_metrics={"distance_km": 6.1, "duration_min": 6.5, "energy_wh": 65.2, "status": "DELIVERED"},
        evaluation_status=EvaluationStatus.OPTIMAL.value,
        notes="High accuracy flight.",
    )
    db.session.add(log1)
    db.session.commit()

    return {
        "admin": admin,
        "operator": operator,
        "req1": req_user1,
        "req2": req_user2,
        "drones": [drone_avail, drone_transit, drone_maint, drone_charge],
        "requests": [req1, req2, req3, req4],
        "routes": [route_base1, route_opt1, route_infeas],
        "sim": sim1,
        "log": log1,
    }


def test_dashboard_metrics_calculation(analytics_dataset):
    """Test accurate database metrics calculation and zero-division protection."""
    admin = analytics_dataset["admin"]
    metrics = AnalyticsService.get_dashboard_metrics(admin)

    assert metrics["total_requests"] == 4
    assert metrics["pending_requests"] == 1  # req3
    assert metrics["completed_deliveries"] == 1  # req2
    assert metrics["cancelled_or_failed_deliveries"] == 1  # req4
    assert metrics["active_simulations"] == 1  # sim1
    assert metrics["available_drones"] == 1  # drone_avail
    assert metrics["in_transit_drones"] == 1  # drone_transit
    assert metrics["maintenance_drones"] == 1  # drone_maint
    assert metrics["charging_drones"] == 1  # drone_charge
    assert metrics["infeasible_routes_count"] == 1  # route_infeas
    assert metrics["feasible_routes_count"] == 2  # route_base1, route_opt1

    # Fleet utilization = 1 in_transit / 4 active drones = 25.0%
    assert metrics["fleet_utilization_pct"] == 25.0

    # Delivery success = 1 delivered / (1 delivered + 1 cancelled) = 50.0%
    assert metrics["delivery_success_pct"] == 50.0


def test_requester_role_scoping(analytics_dataset):
    """Test that a requester only receives their own requests in metrics and monitoring."""
    req1 = analytics_dataset["req1"]
    req2 = analytics_dataset["req2"]

    # Requester 1 has 2 requests (req1, req2)
    m1 = AnalyticsService.get_dashboard_metrics(req1)
    assert m1["total_requests"] == 2
    assert m1["completed_deliveries"] == 1
    assert m1["pending_requests"] == 0

    # Requester 2 has 2 requests (req3, req4)
    m2 = AnalyticsService.get_dashboard_metrics(req2)
    assert m2["total_requests"] == 2
    assert m2["pending_requests"] == 1
    assert m2["completed_deliveries"] == 0

    # Requester 1 monitoring data
    d1 = AnalyticsService.get_delivery_monitoring_data(req1)
    assert len(d1) == 2
    assert all(r["requester_id"] == req1.id for r in d1)

    # Admin monitoring data sees all 4
    d_admin = AnalyticsService.get_delivery_monitoring_data(analytics_dataset["admin"])
    assert len(d_admin) == 4


def test_delivery_monitoring_filters_and_sorting(analytics_dataset):
    """Test status, priority, and text search filters as well as triage sorting."""
    admin = analytics_dataset["admin"]

    # Status filter
    delivered = AnalyticsService.get_delivery_monitoring_data(admin, status_filter="DELIVERED")
    assert len(delivered) == 1
    assert delivered[0]["emergency_type"] == EmergencyType.ANTIVENOM.value

    # Priority filter
    critical = AnalyticsService.get_delivery_monitoring_data(admin, priority_filter="CRITICAL")
    assert len(critical) == 1
    assert critical[0]["emergency_type"] == EmergencyType.BLOOD_SUPPLY.value

    # Emergency type filter
    defib = AnalyticsService.get_delivery_monitoring_data(admin, emergency_type_filter="DEFIBRILLATOR")
    assert len(defib) == 1
    assert defib[0]["id"] == analytics_dataset["requests"][2].id

    # Text search
    search_res = AnalyticsService.get_delivery_monitoring_data(admin, search_query="Serum")
    assert len(search_res) == 1
    assert search_res[0]["emergency_type"] == EmergencyType.ANTIVENOM.value

    # Priority sort: CRITICAL first, then HIGH, MEDIUM, LOW
    sorted_prio = AnalyticsService.get_delivery_monitoring_data(admin, sort_by="priority_desc")
    priorities = [r["priority"] for r in sorted_prio]
    assert priorities == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def test_route_analytics_comparison_with_pandas(analytics_dataset):
    """Test Pandas aggregation comparing baseline vs optimizer and failure breakdowns."""
    comp = AnalyticsService.get_route_analytics_comparison()

    assert comp["total_scenarios_evaluated"] >= 1
    assert "baseline" in comp
    assert "optimizer" in comp
    assert comp["baseline"]["avg_distance_km"] == 6.3  # (5.8 + 6.8) / 2
    assert comp["optimizer"]["avg_distance_km"] == 6.1
    assert comp["baseline"]["avg_energy_wh"] == 73.5   # (62.0 + 85.0) / 2
    assert comp["optimizer"]["avg_energy_wh"] == 64.0

    # Check root causes breakdown
    reasons = comp["reasons_distribution"]
    assert "Battery Reserve Margin Breached" in reasons
    assert "Wind Speed Limit Exceeded" in reasons

    # Check prediction accuracy error
    acc = comp["accuracy_metrics"]
    assert acc["total_audited_missions"] == 1
    assert acc["energy_mean_error_wh"] == 1.2
    assert acc["duration_mean_error_min"] == 0.1


def test_csv_export_authorization_and_sanitization(analytics_dataset):
    """Test CSV report generation, field values, and formula injection sanitization."""
    admin = analytics_dataset["admin"]
    csv_str = AnalyticsService.export_deliveries_csv(admin)

    reader = csv.reader(io.StringIO(csv_str))
    rows = list(reader)
    header = rows[0]
    assert "Request ID" in header
    assert "Emergency Type" in header
    assert "Lifecycle Status" in header
    assert "Payload (kg)" in header

    # Test formula sanitization
    db.session.add(DeliveryRequest(
        requester_id=admin.id,
        emergency_type="=1+1",
        pickup_latitude=10.0,
        pickup_longitude=10.0,
        destination_latitude=10.1,
        destination_longitude=10.1,
        payload_weight_kg=1.0,
        priority=RequestPriority.LOW.value,
        description="@SUM(A1:A10)",
    ))
    db.session.commit()

    sanitized_csv = AnalyticsService.export_deliveries_csv(admin)
    assert "'=1+1" in sanitized_csv


def test_analytics_endpoints_and_permissions(client, analytics_dataset):
    """Test HTTP route accessibility and role-based permissions."""
    # 1. Unauthenticated -> 302 to login
    res = client.get("/analytics")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    # 2. Requester cannot access /analytics dashboard (403 Forbidden)
    client.post("/login", data={"email": "req1@cityhospital.org", "password": "Pass123456!"}, follow_redirects=True)
    res_req = client.get("/analytics")
    assert res_req.status_code == 403

    # Requester CAN access delivery monitor
    res_monitor = client.get("/analytics/deliveries")
    assert res_monitor.status_code == 200

    # Requester CAN export own CSV
    res_csv = client.get("/analytics/export/deliveries.csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["Content-Type"]
    client.get("/logout")

    # 3. Operator CAN access /analytics dashboard
    client.post("/login", data={"email": "op@emergency.org", "password": "Pass123456!"}, follow_redirects=True)
    res_op = client.get("/analytics")
    assert res_op.status_code == 200

    # Operator API summary
    res_api = client.get("/analytics/api/summary")
    assert res_api.status_code == 200
    assert res_api.get_json()["success"] is True
