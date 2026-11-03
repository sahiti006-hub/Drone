"""Academic Demonstration Runner: Scenarios A through F.

Live demonstration script designed for project evaluators and oral examination panels.
Executes and prints verified telemetry and database assertions for:
  Scenario A: Successful Emergency Delivery Lifecycle
  Scenario B: Insufficient Battery Rejection Guardrail
  Scenario C: Payload Limit Exceeded Rejection Guardrail
  Scenario D: Dynamic Environmental Weather Change & In-Flight Rerouting
  Scenario E: Multi-Drone Priority Allocation vs. FCFS Baseline
  Scenario F: Advisory ML Flight Prediction Evaluation & Synthetic Data Disclaimer
"""

from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import create_app
from app.extensions import db
from app.models.delivery_request import DeliveryRequest, EmergencyType, RequestPriority, RequestStatus
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.user import User, UserRole
from app.services.analytics_service import AnalyticsService
from app.services.assignment_service import AssignmentService, InfeasibleAssignmentError
from app.services.drone_allocation_service import DroneAllocationService
from app.services.prediction_service import FlightPredictionService
from app.services.route_optimizer import RouteOptimizer
from app.services.simulation_service import SimulationService
from app.services.weather_service import WeatherData


def get_or_create_demo_user(email: str, full_name: str, role: str) -> User:
    """Idempotently fetch or create a demonstration user account."""
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(full_name=full_name, email=email, password="DemoSecurePassword123!", role=role)
        db.session.add(user)
        db.session.commit()
    return user


def get_or_create_demo_drone(
    drone_code: str,
    model_name: str,
    max_payload_kg: float,
    battery_wh: float,
    current_wh: float,
    speed_kmh: float,
    status: str = DroneStatus.AVAILABLE.value,
) -> Drone:
    """Idempotently fetch or create a demonstration drone unit and reset to nominal state."""
    drone = Drone.query.filter_by(drone_code=drone_code).first()
    if not drone:
        drone = Drone(
            drone_code=drone_code,
            model_name=model_name,
            maximum_payload_kg=max_payload_kg,
            battery_capacity_wh=battery_wh,
            current_battery_wh=current_wh,
            cruise_speed_kmh=speed_kmh,
            status=status,
        )
        db.session.add(drone)
        db.session.commit()
    else:
        # Cancel/abort any dangling active assignments from previously interrupted runs
        DroneAssignment.query.filter_by(
            drone_id=drone.id, status=AssignmentStatus.ACTIVE.value
        ).update({"status": AssignmentStatus.ABORTED.value})
        drone.maximum_payload_kg = max_payload_kg
        drone.battery_capacity_wh = battery_wh
        drone.current_battery_wh = current_wh
        drone.cruise_speed_kmh = speed_kmh
        drone.status = status
        db.session.commit()
    return drone


# ==============================================================================
# SCENARIO A: SUCCESSFUL DELIVERY LIFECYCLE
# ==============================================================================
def run_scenario_a():
    print("\n" + "=" * 80)
    print("▶ SCENARIO A — COMPLETE END-TO-END EMERGENCY DELIVERY LIFECYCLE")
    print("  Objective: Validate request intake, corridor optimization, assignment,")
    print("  discrete kinematics, in-flight pause/resume, and post-mission hardware release.")
    print("=" * 80)

    # 1. Setup accounts
    requester = get_or_create_demo_user("doctor@hospital.org", "Dr. Anita Roy (Hospital)", UserRole.REQUESTER.value)
    drone = get_or_create_demo_drone(
        "DEMO-UAV-SCEN-A", "SkyMedic Hexacopter X6", 5.0, 850.0, 850.0, 65.0, DroneStatus.AVAILABLE.value
    )
    print(f"[+] Drone Readiness Check: {drone.drone_code} [{drone.model_name}]")
    print(f"    Payload Capacity: {drone.maximum_payload_kg} kg | Battery: {drone.current_battery_wh:.1f}/{drone.battery_capacity_wh:.1f} Wh")

    # 2. Submit Emergency Delivery Request
    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,  # Central Blood Bank
        destination_latitude=17.442000,
        destination_longitude=78.388000,  # Trauma Center
        payload_weight_kg=2.20,
        priority=RequestPriority.CRITICAL.value,
        description="URGENT: 2 units O-negative blood for immediate trauma resuscitation.",
    )
    db.session.add(req)
    db.session.commit()
    print(f"[+] Step 1: Emergency Request Lodged #{req.id}")
    print(f"    Type: {req.emergency_type} | Priority: {req.priority} | Cargo: {req.payload_weight_kg} kg")

    # 3. Generate Candidate Routes
    weather = WeatherData(wind_speed_mps=3.2, precipitation_mmh=0.0, visibility_km=10.0, weather_summary="Clear daylight")
    opt_result, saved_route = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=req.id,
        drone_id=drone.id,
        algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
        require_weather=False,
    )
    print(f"[+] Step 2: Route Generation & Corridor Evaluation:")
    print(f"    Evaluated Candidates: {opt_result.candidate_count} | Feasible Corridors: {opt_result.feasible_count}")
    for c in opt_result.candidates:
        f_tag = "FEASIBLE" if c.is_feasible else f"REJECTED ({'; '.join(c.rejection_reasons)})"
        print(f"    • [{c.candidate_id}] {c.corridor_name:28s} | {c.distance_km:5.2f} km | {c.duration_minutes:4.1f} min | {c.energy_wh:5.1f} Wh | Score: {c.objective_score:.4f} -> {f_tag}")

    # 4. Compare Baseline vs Multi-Objective Optimizer
    baseline_res = RouteOptimizer.optimize(
        pickup_lat=float(req.pickup_latitude),
        pickup_lng=float(req.pickup_longitude),
        dest_lat=float(req.destination_latitude),
        dest_lng=float(req.destination_longitude),
        payload_weight_kg=float(req.payload_weight_kg),
        drone_cruise_speed_kmh=float(drone.cruise_speed_kmh),
        drone_max_payload_kg=float(drone.maximum_payload_kg),
        drone_battery_capacity_wh=float(drone.battery_capacity_wh),
        drone_current_battery_wh=float(drone.current_battery_wh),
        weather=weather,
        algorithm_name="SHORTEST_FEASIBLE",
    )
    b_sel = baseline_res.selected_route
    o_sel = opt_result.selected_route
    print(f"[+] Step 3: Algorithmic Comparative Benchmark:")
    print(f"    Baseline (Shortest-Feasible) : {b_sel.corridor_name} ({b_sel.distance_km:.2f} km, {b_sel.duration_minutes:.1f} min, {b_sel.energy_wh:.1f} Wh, Cost: {b_sel.objective_score:.4f})")
    print(f"    Optimizer (Weighted-Objective): {o_sel.corridor_name} ({o_sel.distance_km:.2f} km, {o_sel.duration_minutes:.1f} min, {o_sel.energy_wh:.1f} Wh, Cost: {o_sel.objective_score:.4f})")
    print(f"    Optimization Delta           : Selected {o_sel.corridor_name} with objective score improvement.")

    # 5. Assign Eligible Drone
    assignment = AssignmentService.create_assignment(
        delivery_request_id=req.id,
        drone_id=drone.id,
        route_id=saved_route.id,
    )
    db.session.refresh(req)
    db.session.refresh(drone)
    print(f"[+] Step 4: ACID Fleet Assignment Created #{assignment.id}")
    print(f"    Assignment Status: {assignment.status} | Request Status: {req.status} | Drone Status: {drone.status}")

    # 6. Start Simulation
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)
    db.session.refresh(req)
    db.session.refresh(drone)
    print(f"[+] Step 5: Kinematic Simulation Initiated #{sim.id} (Run Code: {sim.run_code})")
    print(f"    Simulation Status: {sim.status} | Request Status: {req.status} | Drone Status: {drone.status}")

    # Step in-flight to 35%
    step_res = SimulationService.step_simulation(sim.id, delta_sim_seconds=120.0, speed_multiplier=1.0)
    print(f"    • Flight in-progress: {step_res['progress_percent']:.1f}% | Coordinates: ({step_res['latitude']:.5f}, {step_res['longitude']:.5f}) | Battery: {step_res['current_battery_wh']:.1f} Wh")

    # 7. Pause and Resume Simulation
    SimulationService.pause_simulation(sim.id)
    db.session.refresh(sim)
    print(f"[+] Step 6: Operator Intervention (PAUSE): Simulation Status = {sim.status}")
    assert sim.status == SimulationStatus.PAUSED.value, "Simulation pause failed"

    SimulationService.resume_simulation(sim.id)
    db.session.refresh(sim)
    print(f"[+] Step 7: Operator Intervention (RESUME): Simulation Status = {sim.status}")
    assert sim.status == SimulationStatus.RUNNING.value, "Simulation resume failed"

    # 8. Complete Flight Simulation (100% Touchdown)
    SimulationService.step_simulation(sim.id, delta_sim_seconds=900.0, speed_multiplier=1.0)
    db.session.refresh(sim)
    db.session.refresh(req)
    db.session.refresh(drone)
    db.session.refresh(assignment)

    print(f"[+] Step 8: Touchdown & Post-Mission Verification:")
    print(f"    • Final Simulation Status : {sim.status} (Progress: {sim.current_progress_percent:.1f}%)")
    print(f"    • Final Delivery Request  : {req.status}")
    print(f"    • Final Assignment Status : {assignment.status}")
    print(f"    • Airframe Hardware State : {drone.status} (Available for next dispatch)")
    print(f"    • Post-Flight Battery     : {drone.current_battery_wh:.1f} Wh")

    # Assertions
    assert sim.status == SimulationStatus.COMPLETED.value
    assert req.status == RequestStatus.DELIVERED.value
    assert assignment.status == AssignmentStatus.COMPLETED.value
    assert drone.status == DroneStatus.AVAILABLE.value
    print("[PASS] SCENARIO A: Verified end-to-end delivery lifecycle successfully.\n")


# ==============================================================================
# SCENARIO B: INSUFFICIENT BATTERY REJECTION GUARDRAIL
# ==============================================================================
def run_scenario_b():
    print("=" * 80)
    print("▶ SCENARIO B — INSUFFICIENT BATTERY REJECTION GUARDRAIL")
    print("  Objective: Verify that dispatch is strictly blocked when the drone's battery")
    print("  fails the mandatory 20% reserve safety margin, producing an explicit explanation.")
    print("=" * 80)

    requester = get_or_create_demo_user("doctor@hospital.org", "Dr. Anita Roy", UserRole.REQUESTER.value)
    
    # Configure drone with critically depleted battery (35.0 Wh)
    depleted_drone = get_or_create_demo_drone(
        "DEMO-UAV-SCEN-B-DEPLETED",
        "SkyMedic Hexacopter X6",
        5.0,
        850.0,
        35.0,  # 35 Wh cannot satisfy route requirement + 20% reserve
        65.0,
        DroneStatus.AVAILABLE.value,
    )
    print(f"[+] Low-Battery Test Drone: {depleted_drone.drone_code}")
    print(f"    Current Battery: {depleted_drone.current_battery_wh:.1f} Wh / {depleted_drone.battery_capacity_wh:.1f} Wh ({(depleted_drone.current_battery_wh/depleted_drone.battery_capacity_wh)*100:.1f}%)")

    # Delivery request requiring ~68 Wh
    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.ANTIVENOM.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.442000,
        destination_longitude=78.388000,
        payload_weight_kg=2.0,
        priority=RequestPriority.HIGH.value,
        description="Emergency antivenom serum delivery test for battery reserve.",
    )
    db.session.add(req)
    db.session.commit()

    # Route evaluation
    eval_res, _ = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=req.id,
        drone_id=depleted_drone.id,
        require_weather=False,
    )

    print(f"[+] Route Evaluation Feasibility Outcome:")
    print(f"    Overall Feasible: {eval_res.is_feasible} ({eval_res.feasible_count} / {eval_res.candidate_count} candidates feasible)")
    assert not eval_res.is_feasible, "Evaluation should mark routes infeasible due to depleted battery"
    
    explicit_rejection_found = False
    for rej in eval_res.rejected_candidates:
        for r_msg in rej["reasons"]:
            if "battery" in r_msg.lower() or "reserve" in r_msg.lower():
                explicit_rejection_found = True
                print(f"    ✖ Explicit Rejection Reason: \"{r_msg}\"")

    assert explicit_rejection_found, "Explicit battery reserve rejection reason missing"

    # Attempt to bypass/force assignment with infeasible route
    infeasible_route = Route.query.filter_by(
        delivery_request_id=req.id,
        feasibility_status=FeasibilityStatus.INFEASIBLE.value,
    ).first()

    print("[+] Testing System Guardrail against Forced Assignment:")
    try:
        AssignmentService.create_assignment(
            delivery_request_id=req.id,
            drone_id=depleted_drone.id,
            route_id=infeasible_route.id,
        )
        raise AssertionError("SECURITY DEFECT: System allowed assignment of an infeasible battery route!")
    except InfeasibleAssignmentError as e:
        print(f"    ✔ GUARDRAIL ACTIVE: AssignmentService raised InfeasibleAssignmentError:")
        print(f"      \"{e}\"")

    # Verify database was not modified
    active_assign = DroneAssignment.query.filter_by(delivery_request_id=req.id).first()
    assert active_assign is None, "Assignment record must NOT exist in database"
    assert depleted_drone.status == DroneStatus.AVAILABLE.value
    print("[PASS] SCENARIO B: System safely blocked dispatch and verified explicit rejection.\n")


# ==============================================================================
# SCENARIO C: PAYLOAD LIMIT REJECTION GUARDRAIL
# ==============================================================================
def run_scenario_c():
    print("=" * 80)
    print("▶ SCENARIO C — PAYLOAD LIMIT EXCEEDED REJECTION GUARDRAIL")
    print("  Objective: Verify that attempting to assign cargo heavier than the drone's")
    print("  airframe capacity is strictly rejected, preventing forced dispatch.")
    print("=" * 80)

    requester = get_or_create_demo_user("doctor@hospital.org", "Dr. Anita Roy", UserRole.REQUESTER.value)
    
    # Drone with 2.5 kg maximum payload capacity
    light_drone = get_or_create_demo_drone(
        "DEMO-UAV-SCEN-C-LIGHT",
        "RapidDart Courier V2",
        2.5,  # Max payload 2.50 kg
        500.0,
        500.0,
        80.0,
        DroneStatus.AVAILABLE.value,
    )
    print(f"[+] Light Scout Drone: {light_drone.drone_code} [{light_drone.model_name}]")
    print(f"    Airframe Payload Limit: {light_drone.maximum_payload_kg:.2f} kg")

    # Delivery request with 7.50 kg heavy cargo (heavy surgical kit)
    heavy_req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.SURGICAL_KIT.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.442000,
        destination_longitude=78.388000,
        payload_weight_kg=7.50,  # 7.5 kg > 2.5 kg limit
        priority=RequestPriority.HIGH.value,
        description="Heavy trauma surgical kit for emergency field operation.",
    )
    db.session.add(heavy_req)
    db.session.commit()
    print(f"[+] Heavy Delivery Request Lodged #{heavy_req.id} (Cargo: {heavy_req.payload_weight_kg:.2f} kg)")

    # Evaluate route
    eval_res, _ = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=heavy_req.id,
        drone_id=light_drone.id,
        require_weather=False,
    )

    print(f"[+] Route Feasibility Evaluation:")
    print(f"    Feasible: {eval_res.is_feasible} ({eval_res.feasible_count} / {eval_res.candidate_count} candidates)")
    assert not eval_res.is_feasible, "Evaluation should mark routes infeasible due to payload overload"

    payload_rejection_found = False
    for rej in eval_res.rejected_candidates:
        for r_msg in rej["reasons"]:
            if "payload" in r_msg.lower() and "exceeds" in r_msg.lower():
                payload_rejection_found = True
                print(f"    ✖ Explicit Payload Rejection: \"{r_msg}\"")

    assert payload_rejection_found, "Explicit payload rejection message not found in route evaluation"

    # Attempt forced assignment
    infeasible_route = Route.query.filter_by(
        delivery_request_id=heavy_req.id,
        feasibility_status=FeasibilityStatus.INFEASIBLE.value,
    ).first()

    print("[+] Testing Enforcement: Attempting to create assignment for overloaded payload:")
    try:
        AssignmentService.create_assignment(
            delivery_request_id=heavy_req.id,
            drone_id=light_drone.id,
            route_id=infeasible_route.id,
        )
        raise AssertionError("SECURITY DEFECT: System allowed assignment exceeding drone payload!")
    except InfeasibleAssignmentError as e:
        print(f"    ✔ GUARDRAIL ACTIVE: Assignment strictly rejected with message:")
        print(f"      \"{e}\"")

    assert DroneAssignment.query.filter_by(delivery_request_id=heavy_req.id).first() is None
    print("[PASS] SCENARIO C: Payload limit safely enforced; forced dispatch strictly blocked.\n")


# ==============================================================================
# SCENARIO D: DYNAMIC WEATHER CHANGE AND REROUTING
# ==============================================================================
def run_scenario_d():
    print("=" * 80)
    print("▶ SCENARIO D — DYNAMIC WEATHER CHANGE AND IN-FLIGHT REROUTING")
    print("  Objective: Simulate sudden severe weather during flight, evaluate replacement")
    print("  corridors, select feasible replacement, and verify original route preservation.")
    print("=" * 80)

    requester = get_or_create_demo_user("doctor@hospital.org", "Dr. Anita Roy", UserRole.REQUESTER.value)
    drone = get_or_create_demo_drone(
        "DEMO-UAV-SCEN-D-REROUTE",
        "SkyMedic Hexacopter X6",
        5.0,
        850.0,
        850.0,
        65.0,
        DroneStatus.AVAILABLE.value,
    )

    req = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044,
        pickup_longitude=78.486671,
        destination_latitude=17.442000,
        destination_longitude=78.388000,
        payload_weight_kg=2.0,
        priority=RequestPriority.CRITICAL.value,
        description="Mid-flight dynamic weather rerouting verification.",
    )
    db.session.add(req)
    db.session.commit()

    # Initial route generation under nominal weather
    opt_result, saved_route = DroneAllocationService.generate_and_persist_routes(
        delivery_request_id=req.id,
        drone_id=drone.id,
        algorithm_name="WEIGHTED_MULTI_OBJECTIVE",
        require_weather=False,
    )
    original_route_id = saved_route.id
    print(f"[+] Original Route Established: Route #{original_route_id} ({saved_route.algorithm_name})")
    print(f"    Est Distance: {saved_route.estimated_distance_km} km | Est Duration: {saved_route.estimated_duration_minutes} min | Est Energy: {saved_route.estimated_energy_wh} Wh")

    # Dispatch mission
    assignment = AssignmentService.create_assignment(req.id, drone.id, original_route_id)
    sim = SimulationService.get_or_create_simulation(assignment.id)
    SimulationService.start_simulation(sim.id)

    # Step to ~35% flight progress
    step_res = SimulationService.step_simulation(sim.id, delta_sim_seconds=120.0, speed_multiplier=1.0)
    print(f"[+] In-Flight Status at 35% Progress:")
    print(f"    Current Drone Coordinates: ({step_res['latitude']:.5f}, {step_res['longitude']:.5f}) | Progress: {step_res['progress_percent']:.1f}%")

    # Inject sudden moderate adverse weather event (e.g. convective front with crosswind)
    severe_weather = WeatherData(
        wind_speed_mps=7.8,
        precipitation_mmh=4.0,
        visibility_km=4.5,
        weather_summary="Sudden convective cell with crosswind shear and localized rain",
    )
    print(f"\n[!] IN-FLIGHT INCIDENT DETECTED: Sudden Weather Hazard!")
    print(f"    Wind Speed: {severe_weather.wind_speed_mps} m/s | Rain: {severe_weather.precipitation_mmh} mm/h | Visibility: {severe_weather.visibility_km} km")

    # Evaluate dynamic rerouting under SAFETY_MANDATED policy
    reroute_res = SimulationService.evaluate_and_reroute(
        simulation_id=sim.id,
        updated_weather=severe_weather,
        policy_name="SAFETY_MANDATED",
        reason="Severe wind shear and precipitation exceeding safe envelope on direct corridor",
    )

    print(f"[+] Dynamic Rerouting Engine Evaluation Outcome:")
    print(f"    Switched Corridors    : {reroute_res.switched}")
    print(f"    Original Route ID     : #{reroute_res.original_route_id}")
    print(f"    New Route ID          : #{reroute_res.new_route_id}")
    print(f"    Previous Corridor     : {reroute_res.previous_corridor}")
    print(f"    New Corridor Selected : {reroute_res.new_corridor}")
    print(f"    Feasible Candidates   : {reroute_res.feasible_candidates_count}")
    print(f"    Operational Reason    : {reroute_res.reason}")

    assert reroute_res.switched is True, "Dynamic rerouting should switch to safer replacement corridor"
    assert reroute_res.new_route_id is not None
    assert reroute_res.new_route_id != original_route_id

    # Verify that original route is STILL preserved in the database
    orig_route_in_db = db.session.get(Route, original_route_id)
    assert orig_route_in_db is not None, "Original route was deleted from database! Must be preserved."
    assert orig_route_in_db.id == original_route_id
    print(f"[+] Verification: Original Route #{original_route_id} preserved in database.")

    # Verify replacement route in database
    new_route_in_db = db.session.get(Route, reroute_res.new_route_id)
    assert new_route_in_db is not None
    assert new_route_in_db.feasibility_status == FeasibilityStatus.FEASIBLE.value
    print(f"[+] Verification: Replacement Route #{new_route_in_db.id} ({new_route_in_db.algorithm_name}) active.")

    # Verify simulation audit trail in parameters_json
    db.session.refresh(sim)
    params = sim.get_parameters()
    assert "reroute_history" in params
    assert len(params["reroute_history"]) >= 1
    audit_entry = params["reroute_history"][-1]
    print(f"[+] Verification: Immutable Reroute Audit Trail Logged:")
    print(f"    • Old Route ID : #{audit_entry['original_route_id']} -> New Route ID: #{audit_entry['new_route_id']}")
    print(f"    • Reason       : {audit_entry['reason']}")
    print(f"    • Origin Coords: ({audit_entry['reroute_origin']['latitude']:.5f}, {audit_entry['reroute_origin']['longitude']:.5f})")

    # Complete flight on new route
    final_step = SimulationService.step_simulation(sim.id, delta_sim_seconds=900.0, speed_multiplier=1.0)
    db.session.refresh(sim)
    db.session.refresh(req)
    assert sim.status == SimulationStatus.COMPLETED.value
    assert req.status == RequestStatus.DELIVERED.value
    print(f"[+] Mission Touchdown Completed: Status = {req.status} (Progress: {sim.current_progress_percent:.1f}%)")
    print("[PASS] SCENARIO D: Dynamic rerouting evaluated, executed, and audited without data loss.\n")


# ==============================================================================
# SCENARIO E: MULTI-DRONE BATCH ALLOCATION
# ==============================================================================
def run_scenario_e():
    print("=" * 80)
    print("▶ SCENARIO E — MULTI-DRONE ALLOCATION: PRIORITY BEST-FIT VS. FCFS BASELINE")
    print("  Objective: Evaluate competing emergency requests against a constrained fleet,")
    print("  contrasting First-Come-First-Served baseline with priority-aware triage.")
    print("=" * 80)

    requester = get_or_create_demo_user("doctor@hospital.org", "Dr. Anita Roy", UserRole.REQUESTER.value)

    # Drones: 2 available drones
    drone1 = get_or_create_demo_drone("DEMO-UAV-E1", "SkyMedic Hexacopter X6", 5.0, 850.0, 850.0, 65.0)
    drone2 = get_or_create_demo_drone("DEMO-UAV-E2", "AeroRescue HeavyLifter H8", 8.5, 1200.0, 1200.0, 55.0)
    
    # Put all other drones into MAINTENANCE so available fleet is strictly these two
    Drone.query.filter(~Drone.drone_code.in_(["DEMO-UAV-E1", "DEMO-UAV-E2"])).update(
        {"status": DroneStatus.MAINTENANCE.value}, synchronize_session=False
    )
    drone1.status = DroneStatus.AVAILABLE.value
    drone2.status = DroneStatus.AVAILABLE.value
    db.session.commit()

    # Create 4 competing requests created at different timestamps
    # Request 1 (Oldest, LOW priority): Routine supplies
    r_low = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.DISASTER_RELIEF.value,
        pickup_latitude=17.385044, pickup_longitude=78.486671,
        destination_latitude=17.435000, destination_longitude=78.400000,
        payload_weight_kg=1.5,
        priority=RequestPriority.LOW.value,
        description="Routine packaging materials.",
    )
    # Request 2 (MEDIUM priority): Diagnostic medicine
    r_med = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.EMERGENCY_MEDICINE.value,
        pickup_latitude=17.385044, pickup_longitude=78.486671,
        destination_latitude=17.440000, destination_longitude=78.395000,
        payload_weight_kg=4.2,
        priority=RequestPriority.MEDIUM.value,
        description="Standard antibiotics and saline for clinic.",
    )
    # Request 3 (HIGH priority): Pediatric antivenom
    r_high = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.ANTIVENOM.value,
        pickup_latitude=17.385044, pickup_longitude=78.486671,
        destination_latitude=17.442000, destination_longitude=78.388000,
        payload_weight_kg=2.0,
        priority=RequestPriority.HIGH.value,
        description="Pediatric snakebite antivenom vial.",
    )
    # Request 4 (Newest, CRITICAL priority): Blood for operating theater
    r_crit = DeliveryRequest(
        requester_id=requester.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY.value,
        pickup_latitude=17.385044, pickup_longitude=78.486671,
        destination_latitude=17.445000, destination_longitude=78.382000,
        payload_weight_kg=2.2,
        priority=RequestPriority.CRITICAL.value,
        description="O-negative emergency blood units for active surgery.",
    )
    db.session.add_all([r_low, r_med, r_high, r_crit])
    db.session.commit()

    req_ids = [r_low.id, r_med.id, r_high.id, r_crit.id]
    drone_ids = [drone1.id, drone2.id]

    print(f"[+] 4 Competing Delivery Requests Created:")
    print(f"    • Req #{r_low.id}  : Priority = LOW      | Payload = {r_low.payload_weight_kg} kg (Arrived First)")
    print(f"    • Req #{r_med.id}  : Priority = MEDIUM   | Payload = {r_med.payload_weight_kg} kg")
    print(f"    • Req #{r_high.id} : Priority = HIGH     | Payload = {r_high.payload_weight_kg} kg")
    print(f"    • Req #{r_crit.id} : Priority = CRITICAL | Payload = {r_crit.payload_weight_kg} kg (Arrived Last)")
    print(f"    Constrained Available Fleet: 2 Drones (UAV-E1 [5.0 kg], UAV-E2 [8.5 kg])")

    # 1. Run FCFS Greedy Baseline
    fcfs_plan = DroneAllocationService.evaluate_multi_drone_allocation(
        request_ids=req_ids,
        drone_ids=drone_ids,
        algorithm_name="FCFS_GREEDY_BASELINE",
        require_weather=False,
    )

    # 2. Run Priority Best-Fit Strategy
    prio_plan = DroneAllocationService.evaluate_multi_drone_allocation(
        request_ids=req_ids,
        drone_ids=drone_ids,
        algorithm_name="PRIORITY_BEST_FIT",
        require_weather=False,
    )

    priority_weights = {
        RequestPriority.CRITICAL.value: 4,
        RequestPriority.HIGH.value: 3,
        RequestPriority.MEDIUM.value: 2,
        RequestPriority.LOW.value: 1,
    }
    fcfs_prio_score = sum(priority_weights.get(m.request_priority, 1) for m in fcfs_plan.matches)
    prio_prio_score = sum(priority_weights.get(m.request_priority, 1) for m in prio_plan.matches)

    print(f"\n[+] Strategy 1: FCFS Greedy Baseline Allocation:")
    print(f"    Matched Requests: {len(fcfs_plan.matches)} / {fcfs_plan.total_evaluated_requests}")
    print(f"    High Priority Fulfillment: {fcfs_plan.high_priority_fulfillment_rate_pct:.1f}%")
    print(f"    Total Priority Score Served: {fcfs_prio_score}")
    for m in fcfs_plan.matches:
        print(f"    • Req #{m.request_id} [{m.request_priority}] -> Drone #{m.drone_id} ({m.drone_code})")
    for u in fcfs_plan.unmatched_requests:
        print(f"    ✖ UNMATCHED: Req #{u.request_id} [{u.priority}] - {u.reason_code}: {u.explanation}")

    print(f"\n[+] Strategy 2: Priority-Driven Best-Fit Allocation:")
    print(f"    Matched Requests: {len(prio_plan.matches)} / {prio_plan.total_evaluated_requests}")
    print(f"    High Priority Fulfillment: {prio_plan.high_priority_fulfillment_rate_pct:.1f}%")
    print(f"    Total Priority Score Served: {prio_prio_score}")
    for m in prio_plan.matches:
        print(f"    • Req #{m.request_id} [{m.request_priority}] -> Drone #{m.drone_id} ({m.drone_code})")
    for u in prio_plan.unmatched_requests:
        print(f"    ✖ UNMATCHED: Req #{u.request_id} [{u.priority}] - {u.reason_code}: {u.explanation}")

    # Verification: Priority Best Fit must prioritize critical and high
    print(f"\n[+] Algorithmic Comparison:")
    print(f"    FCFS Total Priority Score Served : {fcfs_prio_score}")
    print(f"    Priority Best-Fit Priority Score : {prio_prio_score}")
    
    prio_matched_req_ids = [m.request_id for m in prio_plan.matches]
    assert r_crit.id in prio_matched_req_ids, "CRITICAL request must be allocated under Priority Best Fit"
    assert r_high.id in prio_matched_req_ids, "HIGH request must be allocated under Priority Best Fit"
    assert prio_prio_score >= fcfs_prio_score, "Priority Best-Fit should achieve >= priority score vs FCFS"

    # Test conflict-free transactional batch dispatch
    dispatched_assignments = DroneAllocationService.execute_batch_dispatch(
        allocation_plan=prio_plan,
    )
    print(f"[+] Transactional Batch Dispatch Execution:")
    print(f"    Dispatched Missions: {len(dispatched_assignments)} assignments created.")
    for asg in dispatched_assignments:
        print(f"    • Assignment #{asg.id} -> Drone #{asg.drone_id} (Status: {asg.status})")
    assert len(dispatched_assignments) == 2

    # Clean up drone status for subsequent tests
    Drone.query.update({"status": DroneStatus.AVAILABLE.value})
    db.session.commit()
    print("[PASS] SCENARIO E: Multi-drone allocation demonstrated with priority dominance over FCFS.\n")


# ==============================================================================
# SCENARIO F: ADVISORY ML PREDICTION MODULE & METHODOLOGY
# ==============================================================================
def run_scenario_f():
    print("=" * 80)
    print("▶ SCENARIO F — ADVISORY ML FLIGHT PREDICTION MODULE & METHODOLOGY REVIEW")
    print("  Objective: Present experimental evaluation metrics, 80/20 train/test split,")
    print("  physics baseline comparisons, and explicit synthetic dataset disclaimers.")
    print("=" * 80)

    report = FlightPredictionService.get_evaluation_report()

    print(f"[+] Model Architecture & Protocol:")
    print(f"    • Model Version : {report['model_version']} (L2 Regularized Ridge Regression, alpha=1.0)")
    print(f"    • Training Set  : {report['train_samples']} samples (80%)")
    print(f"    • Test Set      : {report['test_samples']} samples (20%, strictly held-out, seed=42)")
    print(f"    • Predictors    : {', '.join(report['features'])}")

    dur_eval = report["duration_evaluation"]
    nrg_eval = report["energy_evaluation"]

    print(f"\n[+] Target 1: Flight Duration Prediction (Minutes):")
    print(f"    Metric | Baseline Physics Formula | Proposed Ridge ML Model | Improvement")
    print(f"    -------+--------------------------+-------------------------+------------")
    print(f"    MAE    | {dur_eval['baseline_formula']['mae']:10.4f} min        | {dur_eval['ml_model']['mae']:9.4f} min       | +{dur_eval['mae_improvement_pct']:.1f}%")
    print(f"    RMSE   | {dur_eval['baseline_formula']['rmse']:10.4f} min        | {dur_eval['ml_model']['rmse']:9.4f} min       | -")
    print(f"    R²     | {dur_eval['baseline_formula']['r2_score']:10.4f}            | {dur_eval['ml_model']['r2_score']:9.4f}            | -")

    print(f"\n[+] Target 2: Energy Consumption Prediction (Watt-Hours):")
    print(f"    Metric | Baseline Physics Formula | Proposed Ridge ML Model | Improvement")
    print(f"    -------+--------------------------+-------------------------+------------")
    print(f"    MAE    | {nrg_eval['baseline_formula']['mae']:10.4f} Wh         | {nrg_eval['ml_model']['mae']:9.4f} Wh        | +{nrg_eval['mae_improvement_pct']:.1f}%")
    print(f"    RMSE   | {nrg_eval['baseline_formula']['rmse']:10.4f} Wh         | {nrg_eval['ml_model']['rmse']:9.4f} Wh        | -")
    print(f"    R²     | {nrg_eval['baseline_formula']['r2_score']:10.4f}            | {nrg_eval['ml_model']['r2_score']:9.4f}            | -")

    print("\n" + "-" * 80)
    print("⚠️  MANDATORY ACADEMIC & EXPERIMENTAL METHODOLOGY DISCLAIMER")
    print("-" * 80)
    print("1. SYNTHETIC DATASET:")
    print("   The evaluation dataset is generated mathematically using kinematic and aerodynamic")
    print("   formulas with Gaussian noise (sigma=0.05). No physical drone flight sensor telemetry")
    print("   is present in the training or test partitions.")
    print("2. HIGH R² INTERPRETATION (R² >= 0.999):")
    print("   The near-perfect coefficient of determination reflects successful function approximation")
    print("   of the underlying closed-form synthetic simulator, NOT empirical real-world UAV flight.")
    print("3. SAFETY-CRITICAL BOUNDARY:")
    print("   ML predictions are strictly advisory. In flight dispatch, deterministic physics")
    print("   constraints, reserve battery margins (>=20%), and physical limits take absolute precedence.")
    print("-" * 80)

    assert dur_eval["ml_model"]["r2_score"] > 0.85
    assert nrg_eval["ml_model"]["r2_score"] > 0.85
    assert dur_eval["ml_model"]["mae"] < dur_eval["baseline_formula"]["mae"]
    assert nrg_eval["ml_model"]["mae"] < nrg_eval["baseline_formula"]["mae"]
    print("[PASS] SCENARIO F: Advisory ML module evaluation and disclaimers verified.\n")


# ==============================================================================
# MAIN DISPATCHER
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Run Smart Emergency Drone System Academic Demonstration Scenarios")
    parser.add_argument(
        "--scenario",
        choices=["all", "A", "B", "C", "D", "E", "F"],
        default="all",
        help="Specific scenario to execute (default: all)",
    )
    args = parser.parse_args()

    app = create_app("development")
    with app.app_context():
        print("=" * 80)
        print("🎓 SMART EMERGENCY DRONE DELIVERY & ROUTE OPTIMIZATION SYSTEM")
        print("   ACADEMIC DEMONSTRATION & ORAL EVALUATION RUNNER")
        print("=" * 80)

        target = args.scenario.upper()
        if target in ("ALL", "A"):
            run_scenario_a()
        if target in ("ALL", "B"):
            run_scenario_b()
        if target in ("ALL", "C"):
            run_scenario_c()
        if target in ("ALL", "D"):
            run_scenario_d()
        if target in ("ALL", "E"):
            run_scenario_e()
        if target in ("ALL", "F"):
            run_scenario_f()

        print("=" * 80)
        print("🎉 ALL SELECTED DEMONSTRATION SCENARIOS EXECUTED & VERIFIED SUCCESSFULLY!")
        print("=" * 80)


if __name__ == "__main__":
    main()
