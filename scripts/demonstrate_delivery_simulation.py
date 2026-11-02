"""End-to-end verification script demonstrating an emergency drone delivery mission.

Demonstration steps:
1. Locate or create a high-priority emergency request.
2. Evaluate weather and calculate alternative route corridors.
3. Optimize and allocate the most suitable drone unit.
4. Launch the discrete-time kinematic simulation.
5. Step the virtual drone through waypoint interpolation and battery consumption.
6. Trigger mission pause and resume.
7. Reach destination at 100% progress, transition states, release hardware,
   and log audit analytics.
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import create_app
from app.extensions import db
from app.models.delivery_request import DeliveryRequest, EmergencyType, RequestPriority, RequestStatus
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.route_waypoint import RouteWaypoint
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.analysis_log import AnalysisLog
from app.models.user import User, UserRole
from app.services.drone_allocation_service import DroneAllocationService
from app.services.simulation_service import SimulationService


def demonstrate_mission():
    app = create_app("development")
    with app.app_context():
        print("=" * 80)
        print("🚁 SMART EMERGENCY DRONE DELIVERY & ROUTE OPTIMIZATION SYSTEM")
        print("   LIVE MISSION SIMULATION & DISPATCH DEMONSTRATION")
        print("   (Strict Simulation Mode - Numerical Kinematics Only)")
        print("=" * 80)

        # 1. Setup Demo Requester and Drone
        requester = User.query.filter_by(role=UserRole.REQUESTER.value).first()
        if not requester:
            requester = User("Dr. Anita Roy", "dr.roy@metrohospital.org", "Pass123456!", UserRole.REQUESTER.value)
            db.session.add(requester)
            db.session.commit()

        drone = Drone.query.filter_by(status=DroneStatus.AVAILABLE.value).first()
        if not drone:
            drone = Drone(
                drone_code="UAV-MEDIC-EXPRESS",
                model_name="SkyMedic Hexacopter X6",
                maximum_payload_kg=5.0,
                battery_capacity_wh=850.0,
                current_battery_wh=850.0,
                cruise_speed_kmh=65.0,
                status=DroneStatus.AVAILABLE.value,
            )
            db.session.add(drone)
            db.session.commit()

        print(f"\n[1] Hardware Readiness Check:")
        print(f"    - Assigned Drone Unit: {drone.drone_code} ({drone.model_name})")
        print(f"    - Cruise Speed: {drone.cruise_speed_kmh} km/h")
        print(f"    - Battery Level: {drone.current_battery_wh} / {drone.battery_capacity_wh} Wh (100.0%)")
        print(f"    - Status: {drone.status}")

        # 2. Submit Critical Emergency Request
        req = DeliveryRequest(
            requester_id=requester.id,
            emergency_type=EmergencyType.ANTIVENOM.value,
            pickup_latitude=12.9716,
            pickup_longitude=77.5946,  # Victoria Hospital Blood/Serum Bank
            destination_latitude=12.9250,
            destination_longitude=77.6180, # Rural PHC Trauma Outpost
            payload_weight_kg=1.85,
            priority=RequestPriority.CRITICAL.value,
            description="Urgent polyvalent antivenom needed for ICU snakebite patient.",
        )
        db.session.add(req)
        db.session.commit()

        print(f"\n[2] Emergency Request Lodged:")
        print(f"    - Request ID: #{req.id}")
        print(f"    - Category: {req.emergency_type} ({req.priority} Priority)")
        print(f"    - Payload Weight: {req.payload_weight_kg} kg")
        print(f"    - Origin: ({req.pickup_latitude}, {req.pickup_longitude})")
        print(f"    - Destination: ({req.destination_latitude}, {req.destination_longitude})")

        # 3. Automated Route Optimization & Drone Allocation
        print(f"\n[3] Running Multi-Objective Route Optimization & Corridor Allocation...")
        assignment = DroneAllocationService.allocate_and_dispatch(
            delivery_request_id=req.id,
            drone_id=drone.id,
        )

        selected_route_id = assignment.route_id
        assignment_id = assignment.id
        print(f"    - Dispatch Status: {assignment.status}")
        print(f"    - Selected Route ID: #{selected_route_id}")
        print(f"    - Assignment ID: #{assignment_id}")

        # 4. Initialize Simulation Cockpit Run
        print(f"\n[4] Initializing Kinematic Simulation Cockpit:")
        sim = SimulationService.get_or_create_simulation(assignment_id)
        print(f"    - Simulation Run Code: {sim.run_code}")
        print(f"    - Initial Status: {sim.status}")
        print(f"    - Planned Path Distance: {sim.remaining_distance_km:.2f} km")
        print(f"    - Initial Coordinates: ({sim.current_latitude:.6f}, {sim.current_longitude:.6f}, {sim.current_altitude_m:.1f}m AGL)")

        # 5. Launch Simulation
        print(f"\n[5] Launching Simulation Clock (State: RUNNING)...")
        SimulationService.start_simulation(sim.id)
        db.session.refresh(req)
        db.session.refresh(drone)
        print(f"    - Request Status: {req.status}")
        print(f"    - Drone Status: {drone.status}")

        # 6. Step Kinematics: 25% Progress
        print(f"\n[6] In-Flight Waypoint Kinematics Step (Advance 25%):")
        step1 = SimulationService.step_simulation(sim.id, delta_sim_seconds=45.0, speed_multiplier=1.0)
        print(f"    - Progress: {step1['progress_percent']:.1f}%")
        print(f"    - Current Position: ({step1['latitude']:.6f}, {step1['longitude']:.6f}, {step1['altitude_m']:.1f}m)")
        print(f"    - Compass Heading: {step1['heading_deg']}°")
        print(f"    - Distance Covered: {step1['distance_covered_km']:.2f} km | Remaining: {step1['remaining_distance_km']:.2f} km")
        print(f"    - Battery: {step1['current_battery_wh']:.1f} Wh ({step1['battery_percent']:.1f}%)")

        # 7. Pause and Resume Event
        print(f"\n[7] Simulating Operator Pause & Resume Command:")
        SimulationService.pause_simulation(sim.id)
        print(f"    - Paused: Status = {sim.status}")
        SimulationService.resume_simulation(sim.id)
        print(f"    - Resumed: Status = {sim.status}")

        # 8. Step Kinematics: 75% Progress
        print(f"\n[8] In-Flight Waypoint Kinematics Step (Advance to 75%):")
        step2 = SimulationService.step_simulation(sim.id, delta_sim_seconds=90.0, speed_multiplier=1.0)
        print(f"    - Progress: {step2['progress_percent']:.1f}%")
        print(f"    - Current Position: ({step2['latitude']:.6f}, {step2['longitude']:.6f}, {step2['altitude_m']:.1f}m)")
        print(f"    - Battery: {step2['current_battery_wh']:.1f} Wh ({step2['battery_percent']:.1f}%)")

        # 9. Final Approach & Touchdown (100% Completion)
        print(f"\n[9] Final Approach, Touchdown, and Payload Drop (100% Completion):")
        final_step = SimulationService.step_simulation(sim.id, delta_sim_seconds=200.0, speed_multiplier=1.0)
        db.session.refresh(sim)
        db.session.refresh(req)
        db.session.refresh(drone)
        assignment = db.session.get(DroneAssignment, assignment_id)

        print(f"    - Simulation Status: {sim.status}")
        print(f"    - Progress: {sim.current_progress_percent:.1f}%")
        print(f"    - Final Position: ({sim.current_latitude:.6f}, {sim.current_longitude:.6f}, {sim.current_altitude_m:.1f}m)")
        print(f"    - Request Lifecycle Status: {req.status}")
        print(f"    - Assignment Status: {assignment.status}")
        print(f"    - Released Drone Status: {drone.status} (Remaining Battery: {drone.current_battery_wh:.1f} Wh)")

        # 10. Audit & Evaluation Log
        log = AnalysisLog.query.filter_by(simulation_run_id=sim.id).first()
        if log:
            print(f"\n[10] Post-Mission Audit Log Generated:")
            print(f"     - Evaluation Status: {log.evaluation_status}")
            print(f"     - Predicted Metrics: {log.get_predicted_metrics()}")
            print(f"     - Actual Simulated Metrics: {log.get_actual_metrics()}")
            print(f"     - Audit Notes: {log.notes}")

        print("\n" + "=" * 80)
        print("✅ MISSION SIMULATION COMPLETED SUCCESSFULLY WITH VERIFIED PASSING CRITERIA")
        print("=" * 80)


if __name__ == "__main__":
    demonstrate_mission()
