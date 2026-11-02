# Academic Demonstration Guide & Presentation Script
**Project Title:** Smart Multipurpose Emergency Drone Delivery and Route Optimization System  
**Audience:** External Project Evaluators, University Examination Committee, viva examiners  
**Simulation Notice:** All drone paths, kinematics, and telemetry are deterministic academic software simulations.

---

## 1. Demonstration Credentials & Setup

| User Role | Email Address | Password | Permissions & Dashboard Scope |
|---|---|---|---|
| **System Administrator** | `admin@emergencydrone.org` *(or `admin@dispatch.org`)* | `AdminSecurePassword123!` *(or `Admin@123456`)* | System-wide fleet management, user provisioning, global analytics, audit logs |
| **Fleet Operator** | `operator@emergencydrone.org` *(or `operator@dispatch.org`)* | `OperatorSecurePassword123!` *(or `Operator@123456`)* | Route calculation, drone allocation, simulation controls (start/pause/resume/abort) |
| **Medical Requester** | `requester@hospital.org` | `RequesterSecurePassword123!` | Submitting emergency requests, tracking own request status and route map |

### Quick Start Server Launch:
```powershell
Set-Location "C:\Users\Sahiti\.gemini\antigravity\scratch\smart-emergency-drone-system"
.\.venv\Scripts\Activate.ps1
python run.py
```
*Application Cockpit URL:* `http://127.0.0.1:5000`

---

## 2. Step-by-Step Viva Demonstration Sequence

### Step A: Administrator Authentication
1. Navigate to `http://127.0.0.1:5000/login`.
2. Enter email `admin@emergencydrone.org` and password `AdminSecurePassword123!`.
3. Click **Sign In**.
4. **Evaluator Checkpoint:** Observe session establishment, absence of plain passwords in logs, secure session cookies (`HttpOnly`, `SameSite=Lax`), and automatic redirection to the `/admin/dashboard` showing live system metrics.

---

### Step B: Drone Fleet Inventory Management
1. Click **Fleet Management** in the navigation bar (`/drones`).
2. Inspect the drone table displaying:
   - Drone Code (`UAV-MEDIC-01`, `UAV-HEAVY-01`, etc.)
   - Model Name and Maximum Cargo Payload ($kg$)
   - Battery Storage ($Wh$) and Current Battery Level
   - Operational Status badges (`AVAILABLE`, `IN_TRANSIT`, `MAINTENANCE`)
3. Click **Register Drone** (`/drones/new`), enter a new drone (e.g. `UAV-RAPID-05`, payload 4.0 kg, battery 800 Wh, cruise speed 65 km/h).
4. Submit and verify ACID persistence in the database with status `AVAILABLE`.

---

### Step C: Create Emergency Delivery Request
1. Log in or switch to Requester (`requester@hospital.org`).
2. Click **Create Delivery Request** (`/requests/new`).
3. Fill out the emergency payload form:
   - **Emergency Type:** `BLOOD_SUPPLY` or `ANTIVENOM`
   - **Pickup Location:** Victoria Hospital Central Blood Bank (`17.385044, 78.486671`)
   - **Destination Location:** Regional Trauma Clinic (`17.442000, 78.388000`)
   - **Payload Weight:** `2.20 kg`
   - **Triage Priority:** `CRITICAL`
   - **Description:** *"Urgent emergency blood transfer needed for trauma resuscitation."*
4. Click **Submit Emergency Request**.
5. **Evaluator Checkpoint:** Request is persisted in `PENDING` status with verified geospatial boundaries (lat/lon within valid limits, non-identical coordinates).

---

### Step D & E: Geometric Corridor Generation & Feasibility Inspection
1. Switch to Operator account (`operator@emergencydrone.org`).
2. Navigate to **Delivery Requests** (`/requests`), select the new request, and click **Calculate Routes**.
3. The deterministic routing engine generates 4 geometric airspace corridors:
   - `CORRIDOR_DIRECT`: Direct Air Corridor (50m AGL)
   - `CORRIDOR_NORTH_DETOUR`: Northern Peripheral Detour (60m AGL)
   - `CORRIDOR_SOUTH_DETOUR`: Southern Peripheral Detour (60m AGL)
   - `CORRIDOR_HIGH_ALTITUDE`: High-Altitude Safety Corridor (90m AGL)
4. Feasibility checks are executed against weather observations (wind speed, visibility, rain) and drone battery constraints.
5. Inspect the candidate comparison table showing distance ($km$), estimated duration ($min$), energy ($Wh$), and feasibility flags.

---

### Step F: Contrast Baseline vs. Weighted Optimizer
1. Review the comparison card:
   - **Baseline (Shortest-Feasible):** Selects corridor solely on minimum horizontal distance.
   - **Multi-Objective Weighted Optimizer:** Normalizes distance, duration, energy, and structural penalties:
     $$J = 0.25 \\cdot \\hat{d} + 0.35 \\cdot \\hat{t} + 0.30 \\cdot \\hat{e} + 0.10 \\cdot \\hat{p}$$
2. **Evaluator Checkpoint (Key Algorithmic Finding):** Explain why the naive baseline suffered from an arbitrary tie-break (picking High-Altitude because horizontal distance was equal), while the Multi-Objective Optimizer intelligently penalized the unnecessary 80m vertical altitude climb, choosing the `Direct Air Corridor` with an optimal cost score of $0.0000$.

---

### Step G: Drone Allocation & Concurrency Protection
1. Select the recommended drone (`UAV-MEDIC-01`) and the optimal route.
2. Click **Assign & Dispatch Drone**.
3. **Evaluator Checkpoint:** Verify database transaction atomicity. The delivery request transitions to `ASSIGNED`, and the drone transitions to `RESERVED`/`IN_TRANSIT`. Concurrency row locks prevent another operator from double-dispatching the same drone.

---

### Step H: Interactive Simulation Cockpit Launch
1. Open the interactive simulation view (`/simulation/assignment/<id>`).
2. Observe the Leaflet.js OpenStreetMap interface displaying:
   - Green pickup marker (Hospital Blood Bank)
   - Red destination marker (Trauma Clinic)
   - Blue polyline of the selected flight path
   - Real-time telemetry dashboard (speed, altitude, battery percentage, estimated arrival time)
3. Click **Start Mission Simulation**.
4. The virtual drone marker begins discrete-time kinematic waypoint interpolation, updating coordinates, heading angle, distance covered, and battery drain.

---

### Step I: In-Flight Pause and Resume Controls
1. Click **Pause Simulation** while the drone is in-flight.
2. Verify:
   - Status transitions to `PAUSED`.
   - Kinematic interpolation halts.
   - Drone holds its current latitude, longitude, and remaining battery.
3. Click **Resume Simulation**. Status returns to `RUNNING` and virtual flight continues seamlessly.

---

### Step J: Mission Touchdown & Hardware Release
1. Allow or step the simulation to 100% progress.
2. When the virtual drone arrives at the destination:
   - Simulation state transitions to `COMPLETED`.
   - Delivery Request status automatically transitions to `DELIVERED`.
   - Drone Assignment transitions to `COMPLETED`.
   - The airframe is released back to the fleet with status `AVAILABLE` and updated remaining battery.
   - An immutable post-mission audit log (`AnalysisLog`) is created with predicted vs. simulated metrics.

---

### Step K: Operational Dashboard & Analytics Review
1. Navigate to **Operational Dashboard** (`/dashboard` or `/analytics`).
2. Inspect the real database-backed metrics:
   - Total Delivery Requests incremented.
   - Completed Deliveries count incremented.
   - Fleet Utilization Rate and Mission Success Rate updated.
   - Algorithmic benchmarking cards comparing baseline vs. optimizer metrics.
3. Click **Export CSV** to download live audit datasets for verification.

---

## 3. Invalid Scenario Demonstration: Safety Rejection Proof

To demonstrate fail-safe engineering to examiners:

1. Create an emergency request with a 15 km distance.
2. Select a drone with depleted battery (e.g. 35 Wh) or high payload ($6.0\text{ kg}$ on a $2.5\text{ kg}$ airframe).
3. Click **Calculate Routes**.
4. **Evaluator Checkpoint:** Observe that the system:
   - Evaluates all candidate corridors as `INFEASIBLE`.
   - Displays clear rejection rationale:
     > *"Insufficient battery: route requires 94.3 Wh, usable battery is 29.8 Wh (current: 35.0 Wh with 15% mandatory reserve)."*
   - Strictly disables the **Dispatch** button. Direct API dispatch requests are rejected with HTTP 400 (`InfeasibleAssignmentError`), proving backend enforcement.

---

## 4. Automated Terminal Script for Instant Demonstration
To demonstrate the full 11-step sequence automatically in the terminal:
```powershell
python scripts/demonstrate_full_workflow.py
```
This automated test suite executes all phases in ~5 seconds, verifying database state changes and assertions live.
