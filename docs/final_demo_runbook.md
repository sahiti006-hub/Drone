# Academic Demonstration Runbook & Oral Examination Guide
**Smart Multipurpose Emergency Drone Delivery and Route Optimization System**
*Controlled Academic Evaluation, Defense Protocol, and Live Scenario Runbook*

---

## 1. Executive Demonstration Overview

This document provides a strict, reproducible protocol for conducting a live academic defense and technical demonstration of the **Smart Emergency Drone Delivery System**. 

The system operates in **strict simulation mode**: all aerodynamic calculations, kinematic waypoint interpolations, weather disruptions, and battery drain models are computed numerically in software. No physical unmanned aerial vehicles (UAVs) are controlled.

### Demonstration Architecture Summary
- **Backend Architecture**: Flask 3.1 application with SQLAlchemy 2.0 ORM, Flask-Login authentication, Flask-WTF CSRF protection, and SQLite/MySQL database support.
- **Route Optimization Engine**: Multi-objective A* / Dijkstra-based candidate generation evaluated against physical feasibility constraints (payload, wind, precipitation, battery reserve margin).
- **Multi-Drone Allocation Service**: Concurrency-safe batch matching engine supporting both `PRIORITY_BEST_FIT` (triage-driven) and `FCFS_GREEDY_BASELINE` (arrival-order) allocation strategies.
- **Dynamic Simulation Engine**: Discrete-time kinematic simulation with mid-flight waypoint interpolation, manual operator pause/resume, and in-flight dynamic rerouting.
- **Advisory Machine Learning Module**: L2-regularized Ridge Regression (`Ridge-OLS-Poly-v1.0`, $\alpha=1.0$) providing advisory flight duration and energy predictions benchmarked against analytical physics equations.

---

## 2. Pre-Demonstration Checklist & Environment Preparation

Before welcoming evaluators or starting the live demonstration, complete the following verification steps.

### Pre-Demo Verification Checklist
| Check Item | Requirement | Verification Command | Expected Status |
| :--- | :--- | :--- | :--- |
| **Python Runtime** | Python 3.10+ (Tested on 3.14.6) | `python --version` | `Python 3.14.x` |
| **Virtual Environment** | Active isolated `.venv` | `Get-Command python` (PowerShell) | Points to `.\.venv\Scripts\python.exe` |
| **Dependencies** | All packages in `requirements.txt` | `pip check` | `No broken requirements found.` |
| **Port Availability** | TCP Port 5000 free | `netstat -ano \| findstr 5000` | No active listeners |
| **Database State** | Tables created & stamped | `python scripts/init_db.py` | `[+] Database initialized and stamped at head.` |
| **Automated Tests** | 125 tests passing | `pytest -q` | `125 passed in ~20s` |
| **Health API** | HTTP 200 OK | `curl -s http://127.0.0.1:5000/api/health` | `{"status":"healthy","database":"connected"}` |

---

## 3. Clean Demonstration Environment Setup

To ensure total isolation without deleting or corrupting existing development databases, historical logs, or Docker volumes:

### 3.1 Idempotent Database Initialization
Run the initialization script. It creates missing schema tables without dropping existing tables or truncating historical data:
```powershell
# From project root: C:\Users\Sahiti\.gemini\antigravity\scratch\smart-emergency-drone-system
.\.venv\Scripts\Activate.ps1
python scripts/init_db.py
```

### 3.2 Idempotent Demonstration Dataset Seeding
Seed the baseline demonstration users and fleet. The seeding script verifies existence by unique keys (`email`, `drone_code`) before inserting, guaranteeing zero duplicate record collisions on repeated runs:
```powershell
python scripts/seed_db.py
```

### 3.3 Default Demonstration Credentials
| Account Role | Full Name | Email Address | Password | Intended Use in Demonstration |
| :--- | :--- | :--- | :--- | :--- |
| **Administrator** | Dr. Elena Rostova | `admin@emergencydrone.org` | `AdminSecurePassword123!` | Full system administration, fleet registry, audit logs |
| **Fleet Operator** | Marcus Vance | `operator@emergencydrone.org` | `OperatorSecurePassword123!` | Batch drone allocation, mission dispatch, in-flight rerouting |
| **Hospital Requester**| Dr. Sarah Lin | `requester@hospital.org` | `RequesterSecurePassword123!` | Emergency request creation, mission tracking |

---

## 4. Live Demonstration Scenarios (A through F)

All six scenarios can be demonstrated interactively through the Web UI (browser) or executed via the automated academic scenario suite:
```powershell
# Run all six academic scenarios with live assertions:
python scripts/demonstrate_academic_scenarios.py --scenario all

# Or run any individual scenario:
python scripts/demonstrate_academic_scenarios.py --scenario A
```

---

### Scenario A — Complete End-to-End Emergency Delivery Lifecycle
*Objective: Prove request intake, corridor generation, comparative optimization, safe assignment, kinematic stepping, operator pause/resume, and hardware release upon touchdown.*

#### Step-by-Step Web UI Procedure:
1. **Login**: Navigate to `http://127.0.0.1:5000/login` and log in as `requester@hospital.org`.
2. **Submit Emergency Request**:
   - Go to **New Delivery Request** (`/delivery/new`).
   - Select Emergency Type: `Blood Supply (Type O-Negative)`.
   - Set Priority: `CRITICAL`.
   - Set Cargo Mass: `2.20 kg`.
   - Pickup Coordinates: `17.385044, 78.486671` (Central Blood Bank).
   - Destination Coordinates: `17.442000, 78.388000` (Trauma Center).
   - Click **Submit Emergency Request**.
3. **Route Generation & Feasibility Inspection**:
   - Log out and log in as `operator@emergencydrone.org`.
   - Open the pending request.
   - Click **Calculate Candidate Corridors**.
   - Observe the 4 generated flight corridors:
     - `CORRIDOR_DIRECT` (Direct Air Corridor): ~12.24 km, ~13.9 min, ~90.6 Wh.
     - `CORRIDOR_NORTH_DETOUR` (Northern Peripheral): ~12.35 km.
     - `CORRIDOR_SOUTH_DETOUR` (Southern Peripheral): ~12.35 km.
     - `CORRIDOR_HIGH_ALTITUDE` (High Altitude Corridor): ~12.24 km (with climb penalty).
4. **Algorithmic Comparison**:
   - Contrast the **Baseline (Shortest-Feasible)** method with the **Weighted Multi-Objective Optimizer**.
   - Note that the optimizer evaluates composite cost (distance, aerodynamic drag, altitude changes, and risk penalties) rather than naive 2D Euclidean distance.
5. **Assign Eligible Drone**:
   - Select drone unit `DEMO-UAV-SCEN-A` (SkyMedic Hexacopter X6).
   - Click **Confirm Assignment & Lock Dispatch**.
   - Confirm status transitions: Request becomes `ASSIGNED`, Drone becomes `IN_TRANSIT`.
6. **Kinematic Mission Simulation**:
   - Open **Mission Control & Simulation View** (`/simulation/<sim_id>`).
   - Click **Start Mission Flight**.
   - Observe live Leaflet map: drone marker moves along waypoints; altitude and remaining battery decrease in real time.
7. **Pause and Resume Simulation**:
   - Click **Pause Simulation**. Status transitions to `PAUSED`. Drone halts mid-flight.
   - Click **Resume Flight**. Status returns to `RUNNING`. Drone resumes flight progression.
8. **Touchdown & Post-Mission Verification**:
   - Allow simulation to reach 100.0% progress (or click Fast Forward).
   - Verify final database state:
     - `DeliveryRequest.status == DELIVERED`
     - `DroneAssignment.status == COMPLETED`
     - `SimulationRun.status == COMPLETED`
     - `Drone.status == AVAILABLE` (hardware released for next dispatch).

---

### Scenario B — Insufficient Battery Rejection Guardrail
*Objective: Prove that dispatch is strictly blocked when remaining battery fails the mandatory 15% reserve margin plus flight energy requirement.*

#### Demonstration Steps:
1. Select low-battery drone unit `DEMO-UAV-SCEN-B-DEPLETED` (Current battery: `35.0 Wh` out of `850.0 Wh`).
2. Target delivery request requires `88.87 Wh` for transit.
3. System calculates usable battery:
   $$\text{Usable Battery} = 35.0\text{ Wh} \times (1.0 - 0.15) = 29.75\text{ Wh}$$
4. Feasibility checker marks all candidate routes as `INFEASIBLE`.
5. **Explicit Rejection Reason**:
   > `"Insufficient battery: route requires 88.87 Wh, usable battery is 29.75 Wh (current: 35.0 Wh with 15% mandatory reserve)."`
6. Attempting forced dispatch raises `InfeasibleAssignmentError`. No assignment record is written to the database.

---

### Scenario C — Payload Limit Exceeded Rejection Guardrail
*Objective: Prove that attempting to dispatch cargo exceeding a drone's airframe capacity is strictly rejected.*

#### Demonstration Steps:
1. Target lightweight scout drone `DEMO-UAV-SCEN-C-LIGHT` (RapidDart Courier V2, max payload: `2.50 kg`).
2. Create emergency request with heavy cargo: `7.50 kg` (Emergency Surgical Kit).
3. Evaluate route feasibility.
4. **Explicit Rejection Reason**:
   > `"Payload exceeds capacity: cargo is 7.5 kg, drone maximum is 2.5 kg."`
5. Attempting to force assignment triggers `InfeasibleAssignmentError` and is rejected with HTTP 400.

---

### Scenario D — Dynamic Weather Change and In-Flight Rerouting
*Objective: Prove in-flight weather hazard detection, candidate replacement evaluation, safe switching under `SAFETY_MANDATED` policy, and immutable preservation of the original route.*

#### Demonstration Steps:
1. Start an active simulation flight under nominal conditions (Route #1, `CORRIDOR_DIRECT`).
2. Step flight to ~35% progress (drone is in mid-air).
3. Inject environmental disturbance: wind increases to `7.8 m/s` with `4.0 mm/h` precipitation.
4. Call `SimulationService.evaluate_and_reroute(sim.id, updated_weather, policy_name="SAFETY_MANDATED")`.
5. **Expected Observations**:
   - Replacement candidates are computed from current coordinates `(lat, lon)` to destination.
   - Switch accepted: New Route (e.g. `Route #2`, `REROUTE:CORRIDOR_DIRECT`) is created.
   - **Database Preservation**: Original `Route #1` remains intact in the `routes` table (never overwritten or deleted).
   - **Audit Trail**: `sim.parameters_json["reroute_history"]` logs an immutable audit entry with timestamp, old route ID, new route ID, incident coordinates, and operational rationale.
   - Simulation completes flight on the revised corridor.

---

### Scenario E — Multi-Drone Allocation: Priority Best-Fit vs. FCFS Baseline
*Objective: Demonstrate that priority-aware triage outperforms First-Come-First-Served (FCFS) when fleet capacity is constrained.*

#### Demonstration Setup:
- **Available Fleet**: 2 Drones (`UAV-E1` [5.0 kg], `UAV-E2` [8.5 kg]).
- **Pending Requests** (in order of arrival):
  1. `Req #1`: LOW Priority (Routine supplies, 1.5 kg)
  2. `Req #2`: MEDIUM Priority (Antibiotics, 4.2 kg)
  3. `Req #3`: HIGH Priority (Antivenom, 2.0 kg)
  4. `Req #4`: CRITICAL Priority (Emergency Blood, 2.2 kg)

#### Comparative Allocation Results:
| Allocation Policy | Matched Requests | Unmatched Requests | High-Priority Fulfillment Rate | Total Priority Score Served |
| :--- | :--- | :--- | :--- | :--- |
| **FCFS Greedy Baseline** | `Req #1` (LOW), `Req #2` (MEDIUM) | `Req #3` (HIGH), `Req #4` (CRITICAL) | **0.0%** (0/2) | **3** (1 + 2) |
| **PRIORITY_BEST_FIT** | `Req #4` (CRITICAL), `Req #3` (HIGH) | `Req #2` (MEDIUM), `Req #1` (LOW) | **100.0%** (2/2) | **7** (4 + 3) |

#### Key Takeaway for Evaluators:
Under FCFS, low-priority routine cargo claims available airframes simply because it was submitted first, leaving life-threatening CRITICAL blood requests grounded. The `PRIORITY_BEST_FIT` algorithm prioritizes by clinical triage urgency while minimizing payload headroom waste.

---

### Scenario F — Advisory ML Flight Prediction Module & Methodology Review
*Objective: Present independent experimental validation metrics, train/test split, comparison with physics baseline, and the mandatory synthetic dataset disclaimer.*

#### Model Architecture:
- Algorithm: L2-Regularized Ridge Regression (`Ridge-OLS-Poly-v1.0`, $\alpha=1.0$)
- Predictor Features ($D=6$): Distance, Payload Weight, Wind Speed, Cruise Speed, Interaction Term, Aerodynamic Drag Term ($\text{wind}^2$).
- Partitioning: 80% Training ($N=320$) / 20% Held-Out Testing ($N=80$), deterministic seed=42.

#### Benchmark Performance vs. Analytical Physics Baseline:
| Target Variable | Metric | Analytical Physics Baseline | Trained Ridge ML Model | Improvement |
| :--- | :--- | :--- | :--- | :--- |
| **Flight Duration (min)** | MAE | 2.5495 min | **1.0397 min** | **+59.2%** |
| | RMSE | 2.7817 min | **1.3334 min** | - |
| | $R^2$ Score | 0.8930 | **0.9754** | Fits synthetic dynamics |
| **Energy Consumption (Wh)** | MAE | 21.2845 Wh | **7.8514 Wh** | **+63.1%** |
| | RMSE | 30.1282 Wh | **10.9067 Wh** | - |
| | $R^2$ Score | 0.5181 | **0.9368** | Fits synthetic dynamics |

#### Mandatory Academic Methodology Disclaimer:
1. **Synthetic Training Data**: The model is trained exclusively on simulated data generated by mathematical flight equations with Gaussian perturbation noise ($\sigma=0.05$). No physical drone flight sensor telemetry is present.
2. **High $R^2$ Score Interpretation**: The high coefficient of determination reflects successful function approximation of the underlying closed-form simulator, NOT empirical real-world UAV flight.
3. **Safety Boundary**: ML predictions are strictly advisory. Deterministic physics constraints and reserve battery margins ($\ge 15\%$) take absolute precedence.

---

## 5. Live Troubleshooting & Recovery Procedures

If an unexpected condition occurs during a live demonstration, follow these recovery procedures:

### Problem 1: Port 5000 is Already in Use
```powershell
# Identify process listening on port 5000:
Get-NetTCPConnection -LocalPort 5000 | Select-Object OwningProcess

# Terminate the rogue process:
Stop-Process -Id <OwningProcessId> -Force
```

### Problem 2: Drone Left in `IN_TRANSIT` from an Aborted Demo Run
If a demo drone is locked because a previous manual test was interrupted:
```powershell
# Re-run academic scenarios runner (auto-cleans and resets demo drones):
python scripts/demonstrate_academic_scenarios.py --scenario A
```
Or reset directly via Python shell:
```python
from app import create_app
from app.extensions import db
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import DroneAssignment, AssignmentStatus

app = create_app()
with app.app_context():
    DroneAssignment.query.filter_by(status=AssignmentStatus.ACTIVE.value).update({"status": AssignmentStatus.ABORTED.value})
    Drone.query.update({"status": DroneStatus.AVAILABLE.value})
    db.session.commit()
    print("Fleet reset to AVAILABLE.")
```

### Problem 3: SQLite Database Busy / Locked
```powershell
# Ensure no background Python instances hold open file locks:
Get-Process python* | Stop-Process -Force
```

---

## 6. Features Requiring Manual Browser Verification

The following visual and interactive UX capabilities cannot be fully verified via CLI and should be viewed in the browser (`http://127.0.0.1:5000`):

| UI Feature | URL / Location | Visual Observation to Confirm |
| :--- | :--- | :--- |
| **Interactive Leaflet Map** | `/simulation/<sim_id>` | OpenStreetMap base tiles load; pickup and delivery pin markers render with popup details. |
| **Flight Trajectory Polyline** | `/simulation/<sim_id>` | Blue corridor polyline connects waypoints with accurate geodesic curvatures. |
| **Drone Kinematic Marker** | `/simulation/<sim_id>` | Quadcopter icon moves along polyline smoothly as simulation steps advance. |
| **Live Telemetry HUD** | `/simulation/<sim_id>` | Top-right HUD updates airspeed, altitude, battery percentage gauge, and estimated time of arrival. |
| **Operator Pause/Resume Toggle** | `/simulation/<sim_id>` | Button toggles between `Pause Flight` (yellow) and `Resume Flight` (green) with immediate HUD feedback. |
| **Comparative Analytics Table** | `/analytics` | Algorithmic comparison table renders green/red delta badges and root cause rejection histograms. |
| **Advisory ML Validation Card** | `/analytics#ml-evaluation-card` | Displays Ridge model error metrics, baseline comparisons, and the yellow academic disclaimer banner. |
| **Responsive Mobile Layout** | Any page | Navigation collapse menu and responsive CSS grid adjust cleanly to narrower viewport widths. |

---

## 7. Oral Examination Summary Points for Evaluators

1. **Why multi-objective optimization instead of shortest path?**
   Shortest Euclidean distance frequently traverses high-altitude mountain obstacles, turbulent urban corridors, or severe crosswinds. The multi-objective formulation optimizes energy consumption, aerodynamic drag, climb penalties, and risk scores.
2. **How is flight safety guaranteed in software?**
   Through strict pre-flight constraint validation: maximum payload checks, minimum battery reserve margins ($15\%$), and weather ceiling thresholds ($12.0\text{ m/s}$ wind, $8.0\text{ mm/h}$ rain).
3. **What happens during mid-flight weather events?**
   The dynamic simulation engine re-evaluates remaining flight segments from the drone's instantaneous coordinate. Under `SAFETY_MANDATED` policy, it adopts safer lateral corridors while immutably preserving the original route in the database for post-flight audit.
4. **What is the true role of the Machine Learning module?**
   The Ridge Regression model serves strictly as an advisory fast estimator for flight duration and energy drain. It is validated against analytical physics formulas with an explicit disclaimer acknowledging its synthetic training foundation.
