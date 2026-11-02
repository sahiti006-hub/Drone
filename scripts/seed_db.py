"""Database demonstration dataset seeder.

Populates the database with labeled demo users, multi-class drones,
emergency requests, calculated routes, waypoints, weather snapshots,
and simulated analysis logs.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from app import create_app
from app.extensions import db
from app.models import (
    User,
    UserRole,
    Drone,
    DroneStatus,
    DeliveryRequest,
    RequestPriority,
    RequestStatus,
    EmergencyType,
    Route,
    FeasibilityStatus,
    RouteWaypoint,
    WeatherSnapshot,
    WeatherDataSource,
    SimulationRun,
    SimulationStatus,
    AnalysisLog,
    EvaluationStatus,
)


def seed_database():
    """Populate database with demonstration data."""
    app = create_app()

    with app.app_context():
        print("[*] Starting database demonstration dataset seeding...")

        # 1. Seed Demonstration Users
        demo_users = [
            {
                "full_name": "Dr. Elena Rostova (Admin)",
                "email": "admin@emergencydrone.org",
                "password": "AdminSecurePassword123!",
                "role": UserRole.ADMIN.value,
            },
            {
                "full_name": "Marcus Vance (Fleet Operator)",
                "email": "operator@emergencydrone.org",
                "password": "OperatorSecurePassword123!",
                "role": UserRole.OPERATOR.value,
            },
            {
                "full_name": "Dr. Sarah Lin (City Hospital Requester)",
                "email": "requester@hospital.org",
                "password": "RequesterSecurePassword123!",
                "role": UserRole.REQUESTER.value,
            },
        ]

        users_dict = {}
        for user_data in demo_users:
            existing = User.query.filter_by(email=user_data["email"]).first()
            if not existing:
                u = User(
                    full_name=user_data["full_name"],
                    email=user_data["email"],
                    password=user_data["password"],
                    role=user_data["role"],
                )
                db.session.add(u)
                db.session.flush()
                users_dict[user_data["email"]] = u
                print(f"[+] Created User: {u.full_name} [{u.role}]")
            else:
                users_dict[user_data["email"]] = existing
                print(f"[-] User {existing.email} already exists.")

        # 2. Seed Demonstration Drones
        demo_drones = [
            {
                "drone_code": "DRONE-ALPHA-01",
                "model_name": "SkyMedic Hexacopter X6",
                "maximum_payload_kg": 5.0,
                "battery_capacity_wh": 850.0,
                "current_battery_wh": 850.0,
                "cruise_speed_kmh": 65.0,
                "status": DroneStatus.AVAILABLE.value,
            },
            {
                "drone_code": "DRONE-BETA-02",
                "model_name": "AeroRescue HeavyLifter H8",
                "maximum_payload_kg": 8.5,
                "battery_capacity_wh": 1200.0,
                "current_battery_wh": 1200.0,
                "cruise_speed_kmh": 55.0,
                "status": DroneStatus.AVAILABLE.value,
            },
            {
                "drone_code": "DRONE-GAMMA-03",
                "model_name": "RapidDart Courier V2",
                "maximum_payload_kg": 2.5,
                "battery_capacity_wh": 500.0,
                "current_battery_wh": 120.0,  # Low battery, needs charging
                "cruise_speed_kmh": 80.0,
                "status": DroneStatus.CHARGING.value,
            },
            {
                "drone_code": "DRONE-DELTA-04",
                "model_name": "SkyMedic Hexacopter X6",
                "maximum_payload_kg": 5.0,
                "battery_capacity_wh": 850.0,
                "current_battery_wh": 780.0,
                "cruise_speed_kmh": 65.0,
                "status": DroneStatus.MAINTENANCE.value,
            },
        ]

        for drone_data in demo_drones:
            existing = Drone.query.filter_by(drone_code=drone_data["drone_code"]).first()
            if not existing:
                d = Drone(**drone_data)
                db.session.add(d)
                print(f"[+] Created Drone: {d.drone_code} ({d.model_name}) [{d.status}]")
            else:
                print(f"[-] Drone {existing.drone_code} already exists.")

        # 3. Seed Demonstration Delivery Requests
        requester_user = users_dict.get("requester@hospital.org") or User.query.filter_by(role=UserRole.REQUESTER.value).first()

        req1 = DeliveryRequest.query.filter_by(emergency_type=EmergencyType.BLOOD_SUPPLY.value).first()
        if not req1 and requester_user:
            req1 = DeliveryRequest(
                requester_id=requester_user.id,
                emergency_type=EmergencyType.BLOOD_SUPPLY.value,
                pickup_latitude=12.9716000,
                pickup_longitude=77.5946000,  # Central Blood Bank
                destination_latitude=12.9352000,
                destination_longitude=77.6245000,  # District Trauma Care
                payload_weight_kg=2.20,
                priority=RequestPriority.CRITICAL.value,
                status=RequestStatus.ROUTE_CALCULATED.value,
            )
            db.session.add(req1)
            db.session.flush()
            print(f"[+] Created Delivery Request: Blood Supply (Priority: {req1.priority})")

            # 4. Seed Route & Waypoints for Request 1
            route1 = Route(
                delivery_request_id=req1.id,
                algorithm_name="A_STAR_OPTIMIZED",
                estimated_distance_km=5.850,
                estimated_duration_minutes=6.20,
                estimated_energy_wh=68.50,
                route_score=0.9420,
                feasibility_status=FeasibilityStatus.FEASIBLE.value,
            )
            db.session.add(route1)
            db.session.flush()

            waypoints = [
                RouteWaypoint(route1.id, 0, 12.9716000, 77.5946000, 50.0),
                RouteWaypoint(route1.id, 1, 12.9620000, 77.6050000, 65.0),
                RouteWaypoint(route1.id, 2, 12.9480000, 77.6180000, 65.0),
                RouteWaypoint(route1.id, 3, 12.9352000, 77.6245000, 20.0),
            ]
            db.session.add_all(waypoints)
            print(f"[+] Created Route #{route1.id} with 4 waypoints for Request #{req1.id}")

            # 5. Seed Weather Snapshot
            weather1 = WeatherSnapshot(
                delivery_request_id=req1.id,
                wind_speed=3.20,  # 3.2 m/s
                precipitation=0.00,  # 0 mm/h
                visibility=10.00,  # 10 km
                weather_summary="Clear daylight conditions, light breeze",
                source="SIMULATED_ENGINE",
                simulated_or_live=WeatherDataSource.SIMULATED.value,
            )
            db.session.add(weather1)
            print(f"[+] Created Weather Snapshot for Request #{req1.id}")

        # 6. Seed Simulation Run & Analysis Log
        sim_code = "SIM-20261102-DEMO01"
        existing_sim = SimulationRun.query.filter_by(run_code=sim_code).first()
        if not existing_sim:
            sim_run = SimulationRun(
                run_code=sim_code,
                parameters={
                    "fleet_size": 4,
                    "dispatch_policy": "HIGHEST_PRIORITY_FIRST",
                    "weather_condition": "CLEAR",
                    "wind_speed_mps": 3.2,
                },
                status=SimulationStatus.COMPLETED.value,
            )
            sim_run.start_time = datetime.now(timezone.utc)
            sim_run.complete({
                "total_dispatches": 1,
                "successful_deliveries": 1,
                "failed_deliveries": 0,
                "avg_delivery_duration_min": 6.2,
                "avg_energy_consumed_wh": 70.2,
            })
            db.session.add(sim_run)
            db.session.flush()

            analysis_log = AnalysisLog(
                simulation_run_id=sim_run.id,
                algorithm_name="A_STAR_OPTIMIZED_V1",
                scenario_reference="URBAN_HOSPITAL_CORRIDOR",
                predicted_metrics={"distance_km": 5.85, "duration_min": 6.20, "energy_wh": 68.50},
                actual_simulated_metrics={"distance_km": 5.86, "duration_min": 6.35, "energy_wh": 70.20},
                evaluation_status=EvaluationStatus.OPTIMAL.value,
                notes="Route achieved 97.6% energy prediction accuracy within safety tolerance.",
            )
            db.session.add(analysis_log)
            print(f"[+] Created Simulation Run {sim_run.run_code} and Analysis Log")

        db.session.commit()
        print("[+] Demonstration dataset seeding complete.")


if __name__ == "__main__":
    seed_database()
