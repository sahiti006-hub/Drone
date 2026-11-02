# Comprehensive Technical Viva Voce Questions & Answers
**Project Title:** Smart Multipurpose Emergency Drone Delivery and Route Optimization System  
**Degree:** Final Year B.Tech Computer Science & Engineering  
**Scope:** Architecture, Route Optimization, Kinematics, Database, Security, Simulation & Evaluation

---

## Pillar 1: Software Architecture & Design Patterns

### Q1: What architectural pattern is employed in this application?
**Answer:** The application follows a modular, layered Clean Architecture / Service-Oriented Architecture (SOA) pattern within Python Flask:
1. **Presentation Layer (Blueprints & Templates):** Handles HTTP request parsing, cookie extraction, session management, and HTML/Jinja2 template rendering (`app/routes/`).
2. **Service Layer (Business Logic):** Pure Python business logic separated from HTTP concerns (`app/services/`). Services such as `RouteOptimizer`, `AssignmentService`, and `SimulationService` operate on domain models and enforce business invariants.
3. **Data Access / Persistence Layer:** SQLAlchemy 2.0 ORM models defining normalized relational entities (`app/models/`) with explicit foreign key constraints, indexes, and lifecycle hooks.
4. **Configuration & Utilities:** Environment-based settings (`app/config.py`) and centralized database/migration extensions (`app/extensions.py`).

### Q2: Why did you separate business logic into a Service Layer instead of placing it directly inside Flask route handlers?
**Answer:** Placing business logic in route handlers (the "Fat Controller" anti-pattern) causes severe drawbacks:
- It tightly couples business rules to HTTP request objects (`request.form`, `request.json`), preventing the same logic from being called via CLI scripts, cron jobs, background workers, or automated unit tests.
- By isolating business logic into pure Python services (e.g., `RouteOptimizer.optimize()`), the optimization algorithm can be executed, benchmarked, and unit-tested in isolation without mocking the entire Flask WSGI HTTP context.

---

## Pillar 2: Route Optimization & Algorithmic Design

### Q3: How does the candidate route generator work, and why does it not route along street networks?
**Answer:** Drones operate in three-dimensional low-altitude airspace (Very Low Level / VLL airspace, typically 30–120m AGL), not on surface road grids. Ground road networks introduce unnecessary detours and sharp turns irrelevant to multi-rotor flight.
Our `CandidateRouteGenerator` generates alternative geometric airspace corridors:
1. **Direct Air Corridor:** The great-circle straight-line path at nominal altitude (50m AGL).
2. **Northern Peripheral Corridor:** A lateral perpendicular arc offset northward (e.g., $+0.85\text{ km}$ laterally at 60m AGL).
3. **Southern Peripheral Corridor:** A lateral perpendicular arc offset southward (e.g., $-0.85\text{ km}$ laterally at 60m AGL).
4. **High-Altitude Safety Corridor:** Direct horizontal path flown at an elevated ceiling (90m AGL) for obstacle clearance.

### Q4: Explain the mathematical formulation of your Multi-Objective Route Optimizer.
**Answer:** The optimizer employs a normalized weighted-sum scalarization technique to evaluate candidate routes across four competing criteria:
$$J(c) = w_d \\cdot \\hat{d}(c) + w_t \\cdot \\hat{t}(c) + w_e \\cdot \\hat{e}(c) + w_p \\cdot \\hat{p}(c)$$
Where:
- $\\hat{d}, \\hat{t}, \\hat{e}, \\hat{p} \\in [0.0, 1.0]$ are min-max normalized values of cumulative distance ($km$), estimated flight duration ($min$), estimated energy consumption ($Wh$), and structural route penalty.
- $w_d, w_t, w_e, w_p$ are user-configured weights satisfying $\\sum w_i = 1.0$ (Default: $0.25, 0.35, 0.30, 0.10$).
- Min-max normalization for any metric $x$ across feasible candidate set $C$ is computed as:
  $$\\hat{x}(c) = \\frac{x(c) - \\min_{k \\in C} x(k)}{\\max_{k \\in C} x(k) - \\min_{k \\in C} x(k)}$$
  *(If $\\max = \\min$, $\\hat{x} = 0.0$ to avoid division by zero).*

### Q5: What is the baseline algorithm, and how does your optimizer compare against it?
**Answer:** The baseline is the **Shortest-Feasible-Route Selector**. It evaluates all candidate routes against physical constraints and selects the feasible route with minimum horizontal distance ($d$).
- **Key Algorithmic Finding:** In paths where two corridors share identical horizontal distances (e.g., Direct Corridor at 50m vs. High-Altitude Corridor at 90m), the naive baseline suffered from an arbitrary tie-break, picking the High-Altitude airway and subjecting the simulated drone to unnecessary vertical climbs.
- The Weighted Optimizer incorporates structural transition penalties ($alt\_diff \\times 0.01$). It penalizes the 80m vertical climb ($J = 0.1000$) and selects the Direct Air Corridor ($J = 0.0000$), saving energy and reducing flight stress without increasing horizontal distance.

---

## Pillar 3: Aerodynamics, Kinematics & Energy Modeling

### Q6: How do you compute geographic distance between waypoints?
**Answer:** We compute horizontal spherical distance using the **Haversine formula**:
$$a = \\sin^2\\left(\\frac{\\Delta \\phi}{2}\\right) + \\cos(\\phi_1) \\cos(\\phi_2) \\sin^2\\left(\\frac{\\Delta \\lambda}{2}\\right)$$
$$c = 2 \\cdot \\text{atan2}(\\sqrt{a}, \\sqrt{1 - a})$$
$$d = R \\cdot c$$
Where $R = 6,371.0\\text{ km}$ is Earth's mean radius, $\\phi$ is latitude, and $\\lambda$ is longitude in radians. This provides sub-meter precision for regional drone missions without the computational overhead of Vincenty ellipsoidal geodesics.

### Q7: Explain your flight duration and effective speed model.
**Answer:** The duration model accounts for steady-state cruise airspeed and atmospheric headwind resistance:
$$v_{\\text{eff}} = \\max(15.0\\text{ km/h}, v_{\\text{cruise}} - 0.75 \\cdot v_{\\text{headwind}})$$
$$t_{\\text{minutes}} = \\left(\\frac{d}{v_{\\text{eff}}}\\right) \\cdot 60.0 + t_{\\text{transition}}$$
A fixed $1.0\\text{ minute}$ buffer ($t_{\\text{transition}}$) is added to model vertical climb-out and descent landing phases.

### Q8: Explain the energy consumption model ($Wh$) and its scientific limitations.
**Answer:** Electric power consumed during multi-rotor flight is modeled using steady-state hover and aerodynamic parasite drag equations:
$$P_{\\text{outbound}} = P_{\\text{base}} + (c_{\\text{payload}} \\cdot m_{\\text{payload}}) + (c_{\\text{aero}} \\cdot v_{\\text{cruise}}^2) \\quad [\\text{Watts}]$$
$$E_{\\text{outbound}} = P_{\\text{outbound}} \\cdot \\left(\\frac{t_{\\text{minutes}}}{60.0}\\right) \\quad [\\text{Watt-hours}]$$
- $P_{\\text{base}} = 240.0\\text{ W}$ (Base avionics and motor hover power).
- $c_{\\text{payload}} = 38.0\\text{ W/kg}$ (Induced power penalty per kilogram of medical cargo).
- $c_{\\text{aero}} = 0.016\\text{ W/(km/h)}^2$ (Parasite airframe drag scaling quadratically with speed).
- **Academic Disclaimer:** This is an analytical simulation model. It does not model turbulent wind shear, battery cell internal resistance degradation (Peukert's law), or thermal voltage sag under high discharge rates.

---

## Pillar 4: Database Design & Concurrency Protection

### Q9: Describe your database schema normalization and relationship design.
**Answer:** The database is normalized to Third Normal Form (3NF):
- `users`: Stores credentials, roles (`ADMIN`, `OPERATOR`, `REQUESTER`), and active flags.
- `drones`: Fleet hardware state, payload ratings, battery capacities, and operational statuses (`AVAILABLE`, `IN_TRANSIT`, `MAINTENANCE`).
- `delivery_requests`: Emergency orders referencing `users.id` (`ON DELETE RESTRICT` to preserve medical provenance).
- `routes`: Persisted candidate and selected paths referencing `delivery_requests.id` (`ON DELETE CASCADE`).
- `route_waypoints`: Ordered $(lat, lon, alt)$ coordinates referencing `routes.id`.
- `drone_assignments`: Operational junction table linking `delivery_requests`, `drones`, and `routes`.
- `simulation_runs`: Real-time telemetry, checkpoints, and execution clocks.
- `analysis_logs`: Immutable post-flight audit records with predicted vs. simulated metrics.

### Q10: How do you prevent race conditions (double-dispatch) when two operators attempt to assign the same drone simultaneously?
**Answer:** In `AssignmentService.create_assignment()`, we enforce ACID transaction isolation and explicit row-level locking:
1. `db.session.begin()` opens an atomic transaction.
2. The drone record is locked during selection:
   ```python
   drone = Drone.query.filter_by(id=drone_id).with_for_update().first()
   ```
3. The service verifies `drone.status == DroneStatus.AVAILABLE.value`.
4. The status is immediately mutated to `DroneStatus.RESERVED.value` and committed within the transaction block.
5. If another concurrent thread attempts to select the same drone, it either blocks until the transaction completes or encounters `status != AVAILABLE`, raising an explicit `ConflictingAssignmentError`.

---

## Pillar 5: Application Security & RBAC

### Q11: How is password storage and session authentication secured?
**Answer:**
- Passwords are never stored in plaintext. They are hashed using Werkzeug's cryptographic PBKDF2/Scrypt key derivation function with unique cryptographic salt per user.
- Upon successful login, `session.clear()` is called to regenerate the session ID and eliminate **Session Fixation** vulnerabilities.
- Production cookies are configured with `SESSION_COOKIE_HTTPONLY = True` (blocks JavaScript XSS access), `SESSION_COOKIE_SAMESITE = "Lax"` (mitigates CSRF), and `SESSION_COOKIE_SECURE = True` (requires HTTPS).
- In-memory rate limiting locks out an IP/email after 5 consecutive failed login attempts for 5 minutes.

### Q12: How do you prevent Insecure Direct Object References (IDOR) on delivery requests?
**Answer:** Authorization is strictly enforced at the database query level, never by hiding frontend buttons.
When a user accesses `/requests/<id>`, `DeliveryService.get_request_by_id(request_id, user=user)` inspects the user role:
- If `user.role == "REQUESTER"`, the query enforces `filter_by(id=request_id, requester_id=user.id)`. If another user's ID is requested, an explicit HTTP 403 Forbidden is aborted.
- Only users with `ADMIN` or `OPERATOR` roles can access cross-organizational requests.

### Q13: What web security headers are configured, and why?
**Answer:** An `@app.after_request` middleware injects defensive HTTP response headers:
- `X-Content-Type-Options: nosniff`: Prevents MIME-type confusion attacks.
- `X-Frame-Options: SAMEORIGIN`: Defends against clickjacking in external iframes.
- `X-XSS-Protection: 1; mode=block`: Activates legacy browser XSS filters.
- `Referrer-Policy: strict-origin-when-cross-origin`: Restricts URL referrer leakage.
- `Content-Security-Policy`: Restricts unauthorized script and resource execution.

---

## Pillar 6: Simulation Engine & Scientific Evaluation

### Q14: How does the discrete-time kinematic simulation engine work?
**Answer:** The simulation models flight along an ordered waypoint corridor without physical flight controllers:
1. It maintains a simulation clock with discrete time step increments $\\Delta t$ and configurable speed multipliers ($1.0\\times$ to $10.0\\times$).
2. For each step, it calculates distance traveled $\\Delta d = v_{\\text{eff}} \\cdot \\Delta t$ and interpolates the virtual position between current waypoint $W_k$ and target $W_{k+1}$:
   $$lat(t) = lat_k + \\alpha \\cdot (lat_{k+1} - lat_k), \\quad \\alpha = \\frac{d_{\\text{covered}}}{d_{\\text{segment}}}$$
3. Compass bearing is computed using the great-circle forward azimuth formula:
   $$\\theta = \\text{atan2}(\\sin(\\Delta \\lambda) \\cos(\\phi_2), \\cos(\\phi_1) \\sin(\\phi_2) - \\sin(\\phi_1) \\cos(\\phi_2) \\cos(\\Delta \\lambda))$$
4. Real-time checkpoints are synchronized to the MySQL/SQLite database via `/simulation/api/<id>/checkpoint` with strict parameter boundary validation.

### Q15: How do you ensure reproducibility in your evaluation experiments?
**Answer:**
- Deterministic synthetic inputs with fixed geographic coordinates, payload masses, and drone specifications (`scripts/run_optimizer_experiments.py`).
- Both Baseline and Optimizer receive identical candidate sets and physical constraints in every trial.
- Provenance metadata is recorded alongside results: Python version, operating system platform, hardware processor, UTC timestamp, and Git commit hash (`data/experiments/experiment_metadata.json`).
- Automated tests (`tests/test_evaluation_framework.py`) verify that benchmarks execute repeatedly with identical outputs.
