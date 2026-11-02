# Smart Multipurpose Emergency Drone Delivery and Route Optimization System

[![Automated Tests](https://img.shields.io/badge/pytest-79%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Flask%203.1-informational)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/database-MySQL%20%2F%20SQLAlchemy%202.1-orange)](https://www.sqlalchemy.org/)
[![Frontend](https://img.shields.io/badge/maps-Leaflet.js%20%7C%20OpenStreetMap-green)](https://leafletjs.com/)

An academic research prototype, simulation cockpit, and route optimization platform for autonomous medical and emergency supply transit (blood supplies, antivenoms, defibrillators, vaccines, and surgical kits).

---

## Table of Contents
1. [Abstract](#1-abstract)
2. [Problem Statement](#2-problem-statement)
3. [Project Objectives](#3-project-objectives)
4. [Scope & Academic Disclaimer](#4-scope--academic-disclaimer)
5. [System Architecture](#5-system-architecture)
6. [Module Descriptions](#6-module-descriptions)
7. [Database Design](#7-database-design)
8. [Algorithm Formulation: Baseline vs. Multi-Objective Optimizer](#8-algorithm-formulation)
9. [Constraints & Modeling Assumptions](#9-constraints--modeling-assumptions)
10. [Setup and Execution Instructions](#10-setup-and-execution-instructions)
11. [Testing & Quality Assurance](#11-testing--quality-assurance)
12. [Evaluation Methodology](#12-evaluation-methodology)
13. [Benchmark Results Based on Actual Execution](#13-benchmark-results-based-on-actual-execution)
14. [Limitations](#14-limitations)
15. [Future Enhancements](#15-future-enhancements)
16. [Academic Demonstration & Viva Voce Guide](#16-academic-demonstration--viva-voce-guide)

---

## 1. Abstract

Rapid transit of critical healthcare supplies—such as emergency blood units, snakebite antivenoms, and automated external defibrillators (AEDs)—is frequently hindered by urban road gridlock, mountainous terrain, and disaster-induced infrastructure collapse. This project introduces the **Smart Multipurpose Emergency Drone Delivery and Route Optimization System**, a modular, full-stack platform designed to automate dispatch operations, enforce physical and meteorological safety constraints, and optimize 3D flight paths across urban and rural corridors. 

The system incorporates a **Deterministic Multi-Objective Route Optimizer** that balances flight distance, estimated duration, payload-induced energy consumption, and structural maneuver penalties using min-max normalized scalarization against a shortest-feasible baseline. Built on Python Flask, SQLAlchemy 2.0, Leaflet.js, and Pandas, the platform includes role-based access control (RBAC), an interactive discrete-time simulation cockpit, real-time telemetry checkpointing, operational monitoring dashboards, and a reproducible empirical evaluation suite verified by 79 automated tests.

---

## 2. Problem Statement

Traditional ground emergency logistics suffer from severe systemic vulnerabilities:
1. **Unpredictable Surface Transit Times:** Traffic congestion, road construction, and natural disasters introduce high variance in transit times for life-critical supplies.
2. **Terrain & Infrastructure Bottlenecks:** Isolated rural primary health centers (PHCs) and disaster zones often lack passable roads during acute medical emergencies.
3. **Suboptimal Airspace Routing:** Naive point-to-point drone dispatch without dynamic environmental feasibility analysis risks battery exhaustion, cargo overload, and flight through hazardous weather conditions.
4. **Lack of Operational Governance:** Emergency medical logistics require strict auditability, role-aware operational permissions, atomic hardware reservation, and real-time situational awareness.

---

## 3. Project Objectives

- **Modular Clean Architecture:** Decouple HTTP transport, persistence, domain models, and algorithmic services into maintainable, independently testable layers.
- **Deterministic Multi-Corridor Generation:** Generate distinct geometric airspace corridors (Direct, Northern Peripheral, Southern Peripheral, High-Altitude) without relying on ground road maps.
- **Fail-Safe Feasibility Validation:** Enforce physical multi-rotor constraints (payload ratings, battery discharge limits with mandatory 15% non-depletable reserve, sustained wind thresholds, visibility limits, and precipitation tolerance).
- **Multi-Objective Optimization:** Formulate and benchmark a normalized scalarized cost optimizer against a naive shortest-feasible baseline.
- **Interactive Simulation Cockpit:** Provide a web-based Leaflet.js map with discrete-time kinematic interpolation, heading calculation, telemetry streaming, and pause/resume mission controls.
- **Enterprise Security & Reliability:** Enforce zero raw-SQL queries (100% ORM parameterized), PBKDF2/Scrypt password hashing, session fixation prevention, IDOR protection, defensive HTTP headers, and atomic transactions.
- **Reproducible Academic Evaluation:** Provide deterministic benchmark scenario runners, CSV data exports, analytical summary reports, and vector graphical charts.

---

## 4. Scope & Academic Disclaimer

> [!IMPORTANT]
> **SIMULATION RESEARCH NOTICE:**  
> This system is an academic software prototype developed for educational, algorithmic research, and comparative evaluation purposes. It operates in **simulation mode** using mathematical and kinematic approximations. It does **not** directly interface with physical drone avionics (e.g., PX4, ArduPilot, MAVLink) and does not constitute a certified civil aviation flight-planning tool or air traffic control clearance system. Simulated energy consumption figures represent mathematical approximations and do not reflect measured battery chemistry discharge curves.

---

## 5. System Architecture

```text
                                  +---------------------------------------+
                                  |   Web Browser (Client Presentation)   |
                                  |  HTML5 / CSS3 / Vanilla JS / Leaflet  |
                                  +---------------------------------------+
                                                     |
                                            HTTP / JSON REST API
                                                     |
                                  +---------------------------------------+
                                  |   Flask Blueprints (HTTP Controllers)  |
                                  |   /auth, /drones, /requests, /admin   |
                                  |      /simulation, /analytics         |
                                  +---------------------------------------+
                                                     |
                                      Pure Python Business Services
                                                     |
         +--------------------+----------------------+--------------------+--------------------+
         |                    |                      |                    |                    |
+-----------------+  +------------------+  +-------------------+  +------------------+  +------------------+
|  AuthService    |  | DroneService     |  | RouteOptimizer    |  | AssignmentService|  | SimulationService |
|  • RBAC & Rate  |  | • State Machine  |  | • Candidate Gen   |  | • ACID Dispatch  |  | • Kinematics     |
|    Limiting     |  | • Fleet Inventory|  | • Multi-Objective |  | • Concurrency    |  | • Checkpoints    |
|  • Session Guard|  | • Hardware Specs |  | • Feasibility Check|  |   Row Locks      |  | • Interpolation  |
+-----------------+  +------------------+  +-------------------+  +------------------+  +------------------+
         |                    |                      |                    |                    |
         +--------------------+----------------------+--------------------+--------------------+
                                                     |
                                          SQLAlchemy 2.0 ORM
                                                     |
                                  +---------------------------------------+
                                  |       Relational Database (3NF)       |
                                  |      MySQL 8.0+ / SQLite Fallback     |
                                  | users, drones, requests, routes, etc. |
                                  +---------------------------------------+
```

---

## 6. Module Descriptions

| Module Directory | Key Components | Architectural Purpose |
|---|---|---|
| `app/routes/` | `auth.py`, `drone_routes.py`, `delivery_routes.py`, `simulation_routes.py`, `analytics_routes.py` | Handles HTTP routing, form validation, CSRF verification, and format-negotiated error responses (JSON vs HTML). |
| `app/models/` | `User`, `Drone`, `DeliveryRequest`, `Route`, `RouteWaypoint`, `DroneAssignment`, `SimulationRun`, `AnalysisLog` | Declarative SQLAlchemy entities normalized to 3NF with foreign keys, indexes, and lifecycle hooks. |
| `app/services/` | `RouteOptimizer`, `DroneAllocationService`, `AssignmentService`, `SimulationService`, `AnalyticsService` | Core domain engine: corridor generation, feasibility evaluation, multi-objective scoring, discrete-time kinematics, and Pandas analytics. |
| `app/templates/` | `base.html`, `auth/`, `dashboard/`, `drones/`, `delivery/`, `simulation/`, `analytics/` | Clean Jinja2 emergency-dispatch UI with role-aware navigation and responsive layout. |
| `scripts/` | `init_db.py`, `seed_db.py`, `create_admin.py`, `run_optimizer_experiments.py`, `analyze_evaluation_results.py`, `demonstrate_full_workflow.py` | Maintenance, database migration, automated benchmark evaluation, and live demonstration runners. |
| `tests/` | 11 dedicated test modules (79 automated tests) | Comprehensive unit, integration, RBAC, boundary validation, and security regression suite. |

---

## 7. Database Design

The relational schema is normalized to **Third Normal Form (3NF)**:

```
[ users ] (1)
    |
    |--< (N) [ delivery_requests ] (1)
                 |
                 |--< (N) [ routes ] (1)
                 |           |
                 |           |--< (N) [ route_waypoints ]
                 |
                 |--< (N) [ drone_assignments ] (N) >-- (1) [ drones ]
                                |
                                |--< (N) [ simulation_runs ] (1)
                                             |
                                             |--< (N) [ analysis_logs ]
```

### Table Dictionary:
1. **`users`**: Manages user accounts, cryptographic password hashes, active flags, and roles (`ADMIN`, `OPERATOR`, `REQUESTER`).
2. **`drones`**: Tracks fleet airframes, models, cruise speeds, maximum payload capacities ($kg$), total battery capacity ($Wh$), current battery ($Wh$), and operational statuses (`AVAILABLE`, `RESERVED`, `IN_TRANSIT`, `CHARGING`, `MAINTENANCE`).
3. **`delivery_requests`**: Emergency orders containing pickup/destination coordinates, payload mass ($kg$), triage priority (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), emergency category, and lifecycle states (`PENDING`, `ROUTE_CALCULATED`, `ASSIGNED`, `IN_TRANSIT`, `DELIVERED`, `CANCELLED`).
4. **`routes`**: Evaluated flight corridors storing algorithm name, distance ($km$), estimated duration ($min$), energy ($Wh$), objective cost score, feasibility status (`FEASIBLE`, `INFEASIBLE`), and rejection reasons.
5. **`route_waypoints`**: Ordered sequential $(lat, lon, alt\_m)$ geographic points comprising each flight corridor.
6. **`drone_assignments`**: Junction entity linking delivery requests, assigned drones, and selected routes with status tracking (`ACTIVE`, `COMPLETED`, `ABORTED`).
7. **`simulation_runs`**: Real-time kinematic telemetry checkpoints, current $(lat, lon, alt)$, elapsed/remaining time, speed multipliers, and execution status (`CREATED`, `RUNNING`, `PAUSED`, `COMPLETED`).
8. **`analysis_logs`**: Immutable post-mission audit records comparing predicted vs. actual simulated metrics for quality assurance.

---

## 8. Algorithm Formulation

### 8.1 Candidate Route Generation
Rather than utilizing 2D ground road networks, `CandidateRouteGenerator` generates 4 distinct geometric corridors in 3D airspace:
1. **`CORRIDOR_DIRECT`**: Great-circle straight line path at 50m AGL.
2. **`CORRIDOR_NORTH_DETOUR`**: Lateral perpendicular arc offset northward ($+0.85\text{ km}$ at 60m AGL).
3. **`CORRIDOR_SOUTH_DETOUR`**: Lateral perpendicular arc offset southward ($-0.85\text{ km}$ at 60m AGL).
4. **`CORRIDOR_HIGH_ALTITUDE`**: Direct horizontal corridor with an elevated cruising ceiling (90m AGL).

### 8.2 Baseline: Shortest-Feasible-Route Selector
The baseline algorithm filters out infeasible candidates and sorts remaining corridors lexicographically:
$$\text{Sort Key} = (\text{distance\_km}, \text{energy\_wh}, \text{duration\_minutes}, \text{candidate\_id})$$

### 8.3 Proposed Multi-Objective Weighted Optimizer
The proposed algorithm performs **min-max normalization** across all feasible candidates in the trial and computes a composite scalar cost score $J(c)$:
$$J(c) = w_d \cdot \hat{d}(c) + w_t \cdot \hat{t}(c) + w_e \cdot \hat{e}(c) + w_p \cdot \hat{p}(c)$$
Where:
- $\hat{d}, \hat{t}, \hat{e}, \hat{p} \in [0.0, 1.0]$ are normalized distance, flight duration, energy consumption, and structural maneuver penalties.
- Maneuver penalty $\hat{p}$ penalizes vertical altitude step variations ($alt\_diff \times 0.01$) and excessive detour curvature:
  $$p(c) = \sum_{i=1}^{n-1} |alt_{i+1} - alt_i| \cdot 0.01 + \left(\frac{d_{\text{corridor}}}{d_{\text{straight}}} - 1.0\right) \cdot 1.5$$
- Default weights: $w_d = 0.25$, $w_t = 0.35$, $w_e = 0.30$, $w_p = 0.10$.

---

## 9. Constraints & Modeling Assumptions

1. **Geospatial Distance:** Spherical Haversine calculation with mean Earth radius $R = 6,371.0\text{ km}$. Coordinate bounds enforced ($-90 \le \text{lat} \le 90$, $-180 \le \text{lon} \le 180$, $|\Delta\text{coords}| \ge 10^{-6}$).
2. **Aerodynamic Flight Duration:** Effective forward airspeed models linear headwind degradation:
   $$v_{\text{eff}} = \max(15.0\text{ km/h}, v_{\text{cruise}} - 0.75 \cdot v_{\text{headwind}})$$
   A fixed $1.0\text{ minute}$ buffer is added for vertical takeoff and landing (VTOL) transition.
3. **Electric Power & Energy:** Modeled via base avionics, payload induced drag, and parasite airframe drag:
   $$P_{\text{outbound}} = 240.0 + (38.0 \cdot m_{\text{payload}}) + (0.016 \cdot v_{\text{cruise}}^2) \quad [\text{Watts}]$$
   $$E_{\text{outbound}} = P_{\text{outbound}} \cdot \left(\frac{t_{\text{minutes}}}{60.0}\right) \quad [\text{Watt-hours}]$$
4. **Mandatory Battery Reserve:** Missions are rejected if $E_{\text{route}} > \text{Battery}_{\text{current}} \times (1.0 - 0.15)$. Drones must retain at least $15\%$ reserve upon landing.
5. **Meteorological Thresholds:** Missions are rejected if sustained wind $> 12.0\text{ m/s}$, ground visibility $< 3.0\text{ km}$, precipitation rate $> 8.0\text{ mm/h}$, or if weather telemetry is missing (Fail-Safe policy).

---

## 10. Setup and Execution Instructions

### Prerequisites
- Python 3.10 to 3.14
- Git
- Windows PowerShell, macOS zsh, or Linux bash

### Step 1: Clone & Setup Virtual Environment
```powershell
# Windows PowerShell
git clone <repository-url> smart-emergency-drone-system
cd smart-emergency-drone-system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Environment Configuration
Copy the template configuration:
```powershell
Copy-Item .env.example .env
```
*(The default SQLite database URL `sqlite:///instance/drone_system.db` allows immediate offline execution without local MySQL installation).*

### Step 3: Initialize Database & Seed Demonstration Accounts
```powershell
python scripts/init_db.py
python scripts/seed_db.py
```

### Step 4: Run the Application Server
```powershell
python run.py
```
Open **`http://127.0.0.1:5000`** in any modern web browser.

---

## 11. Testing & Quality Assurance

The test suite contains **79 automated tests** executed using Pytest:

```powershell
pytest -v
```

```text
tests\test_analytics_and_monitoring.py ......                            [  7%]
tests\test_auth_and_dashboards.py ........                               [ 17%]
tests\test_delivery_and_drone_management.py ........                     [ 27%]
tests\test_delivery_request_and_routes.py ...                            [ 31%]
tests\test_drone_assignment_service.py ....                              [ 36%]
tests\test_drone_model.py ...                                            [ 40%]
tests\test_evaluation_framework.py ....                                  [ 45%]
tests\test_health.py ..                                                  [ 48%]
tests\test_route_optimization_and_allocation.py ..............           [ 65%]
tests\test_security_and_audit.py ..........                              [ 78%]
tests\test_simulation_and_analysis_logs.py ..                            [ 81%]
tests\test_simulation_engine_and_api.py .........                        [ 92%]
tests\test_user_model.py ......                                          [100%]

============================= 79 passed in 13.82s =============================
```

---

## 12. Evaluation Methodology

The experimental evaluation framework (`scripts/run_optimizer_experiments.py`) executes **14 deterministic synthetic benchmark scenarios** covering:
- **Short Distances** ($3.0 - 5.0\text{ km}$), **Medium Distances** ($10.0 - 15.0\text{ km}$), and **Long Distances** ($20.0 - 28.0\text{ km}$).
- **Light Payloads** ($1.0\text{ kg}$), **Standard Payloads** ($2.0 - 2.5\text{ kg}$), and **Heavy Cargo** ($4.5 - 6.0\text{ kg}$).
- **Multi-Class Drones:** Light ($2.5\text{ kg}, 450\text{ Wh}$), Standard ($5.0\text{ kg}, 850\text{ Wh}$), Heavy-Lift ($8.0\text{ kg}, 1400\text{ Wh}$).
- **Atmospheric States:** Calm skies, headwind resistance, low visibility fog, torrential monsoon storms, and missing observations.
- **Weight Configurations:** Balanced, Speed-Critical, Energy-Conserving, and Distance-Minimized.

Both algorithms receive **equivalent candidate sets and identical physical constraints** in every scenario.

```powershell
# Run the benchmark experiment runner
python scripts/run_optimizer_experiments.py

# Generate statistical reports and SVG visual charts
python scripts/analyze_evaluation_results.py
```

---

## 13. Benchmark Results Based on Actual Execution

### 13.1 Quantitative Summary

| Metric Description | Baseline (Shortest-Feasible) | Multi-Objective Optimizer | Delta | Scientific Explanation |
|---|---|---|---|---|
| **Feasible Missions** | 8 / 14 (57.1%) | 8 / 14 (57.1%) | 0.0% | Both enforce identical safety thresholds |
| **Mean Selected Distance** | 11.84 km | 11.84 km | 0.00 km | Identical horizontal distance when picking direct path |
| **Mean Flight Duration** | 15.68 min | 15.68 min | 0.00 min | Effective speed model handles headwind equivalently |
| **Mean Energy Consumption** | 100.8 Wh | 100.8 Wh | 0.00 Wh | Identical aerodynamic formulas applied |
| **Mean Objective Cost Score** | **0.1000** | **0.0000** | **-0.1000** | **Optimizer avoids unnecessary 80m vertical climb** |
| **Mean Execution Latency** | 0.091 ms | 0.076 ms | -0.015 ms | Both algorithms operate in real-time ($< 0.25\text{ ms}$) |

### 13.2 Key Algorithmic Trade-Off Finding
In all feasible scenarios where the Direct Corridor (50m AGL) and High-Altitude Corridor (90m AGL) had identical horizontal distance, the naive Baseline suffered from an arbitrary tie-break (`CORRIDOR_HIGH_ALTITUDE` alphabetically before `CORRIDOR_DIRECT`), unnecessarily routing the simulated drone into an 80m vertical climb and descent. The Multi-Objective Optimizer penalized the vertical step variations ($p = 0.80$, cost score $0.1000$) and selected the Direct Air Corridor (cost score $0.0000$), successfully eliminating unnecessary vertical maneuvering without increasing travel time or horizontal distance.

### 13.3 Safety Fail-Safe Stress Test Results
All 6 adverse stress scenarios were rejected across all candidate corridors by both algorithms:
- `EXP-08`: Battery exhaustion ($45\text{ Wh}$ remaining) rejected by mandatory 15% reserve check.
- `EXP-09`: Cargo overload ($5.5\text{ kg}$ on $2.5\text{ kg}$ airframe) rejected.
- `EXP-10`: Gale wind ($16.5\text{ m/s} > 12.0\text{ m/s}$ limit) rejected.
- `EXP-11`: Dense fog ($1.2\text{ km} < 3.0\text{ km}$ VFR limit) rejected.
- `EXP-12`: Heavy rain ($14.5\text{ mm/h} > 8.0\text{ mm/h}$ limit) rejected.
- `EXP-13`: Missing weather telemetry rejected under fail-safe policy.

Generated vector charts are available in [`reports/figures/`](reports/figures/):
- `distance_vs_energy_tradeoff.svg`
- `feasibility_breakdown.svg`
- `algorithm_execution_latency.svg`
- `objective_score_comparison.svg`

---

## 14. Limitations

1. **Aeronautical Wind Model:** Atmospheric wind is modeled as a steady horizontal scalar headwind rather than a turbulent 3D micro-climate vector field.
2. **Battery Electro-Chemistry:** The energy model assumes linear discharge and does not model non-linear voltage sag, ambient temperature impact on lithium-polymer cells, or Peukert's capacity degradation.
3. **Sensor & GPS Inaccuracies:** Coordinates in the simulation cockpit are treated as exact floating-point values without simulated multipath reflection, satellite dilution of precision (GDOP), or sensor noise.
4. **Airspace Conflict Deconfliction:** The system calculates independent 3D corridors but does not yet feature dynamic ADS-B transponder collision avoidance for multi-agent airspace deconfliction.

---

## 15. Future Enhancements

1. **Hardware-in-the-Loop (HIL) Autopilot Integration:** Interface via MAVLink / PX4 to translate generated waypoints into mission commands on physical autonomous flight controllers.
2. **Real-Time Weather Sensor Network:** Connect live Internet of Things (IoT) ultrasonic anemometers and ceilometers located at hospital landing pads.
3. **Dynamic Drone Charging Station Scheduling:** Expand optimization to model multi-hop regional networks with automated battery-swap pads and solar charging stations.
4. **Genetic / Ant-Colony Airspace Corridors:** Implement evolutionary metaheuristics for multi-drone simultaneous dispatch deconfliction.

---

## 16. Academic Demonstration & Viva Voce Guide

- **Live Demonstration Walkthrough:** Refer to [`docs/academic_demonstration_guide.md`](docs/academic_demonstration_guide.md) for step-by-step presentation scripts and evaluator checkpoints.
- **Viva Voce Technical Q&A:** Refer to [`docs/viva_technical_qa.md`](docs/viva_technical_qa.md) for 15+ comprehensive technical questions and answers covering algorithms, architecture, database concurrency, security, and kinematics.
- **Automated Verification Script:** Execute the full 11-step demonstration and invalid safety rejection proof:
  ```powershell
  python scripts/demonstrate_full_workflow.py
  ```
