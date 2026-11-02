# Smart Multipurpose Emergency Drone Delivery and Route Optimization System

A modular, simulation-driven emergency dispatch and route optimization platform built for rapid medical, disaster relief, and high-priority supply transit.

---

## 1. Project Overview

The **Smart Multipurpose Emergency Drone Delivery and Route Optimization System** is a full-stack engineering solution designed to simulate, schedule, and optimize autonomous drone delivery operations for mission-critical and emergency supplies (e.g., blood packages, antivenoms, defibrillators, disaster kits).

The system integrates real-time geospatial tracking (via Leaflet.js and OpenStreetMap), multi-criteria route optimization algorithms, dynamic battery/payload depletion modeling, and persistent audit logging via MySQL and Pandas data pipelines.

> **Note on Scope**: In accordance with the engineering specification, this system operates in **simulation mode**. It models physical constraints (speed, payload limits, battery discharge, no-fly zones, and weather factors) through software mathematical models without requiring physical drone hardware control.

---

## 2. Technology Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript (ES6+) | Interactive operator dashboard, status telemetry, request intake forms, responsive layouts |
| **Map Engine** | Leaflet.js, OpenStreetMap | Geospatial rendering, live path interpolation, waypoint and base station markers |
| **Backend** | Python 3.10+, Flask | Modular REST API service, application factory pattern, service-layer orchestration |
| **Security & Auth** | Flask Session, Flask-WTF CSRF, Scrypt Hashing | Role-based access control (RBAC), rate-limiting brute force protection, IDOR guard |
| **Database** | MySQL (with SQLite dev fallback), SQLAlchemy, Flask-Migrate | Normalized 3NF relational schema for drones, orders, routes, assignments, and telemetry |
| **Analytics** | Pandas, NumPy | Route analysis, energy consumption metrics, dispatch efficiency reports |
| **Testing** | Pytest, Pytest-Cov | Unit testing, integration testing, and API contract test automation (28 automated tests) |
| **Version Control** | Git | Distributed version management and change traceability |

---

## 3. Architecture & Modular Design

```text
smart-emergency-drone-system/
│
├── app/
│   ├── __init__.py          # Flask Application Factory (create_app)
│   ├── config.py            # Environment-aware configurations (Dev, Test, Prod)
│   ├── extensions.py        # Extensions lifecycle (SQLAlchemy, Migrate, CSRFProtect)
│   ├── routes/              # HTTP Route Blueprints & Request Handlers
│   │   ├── __init__.py
│   │   ├── health.py        # Health-check and system readiness endpoints
│   │   ├── auth.py          # Authentication (Login, Logout, Rate limiting)
│   │   └── dashboard.py     # Role-specific dashboards & dispatch actions
│   ├── models/              # Normalized Relational Models
│   │   ├── __init__.py      # Package export for models and enums
│   │   ├── user.py          # Users & backend role-based permissions
│   │   ├── drone.py         # Drones, capacities, and state transitions
│   │   ├── delivery_request.py # Emergency intake & coordinate validation
│   │   ├── route.py         # Planned routes & feasibility scores
│   │   ├── route_waypoint.py# Ordered simulation waypoints
│   │   ├── weather_snapshot.py # Weather snapshots with explicit units
│   │   ├── drone_assignment.py # ACID mission dispatches & conflict locking
│   │   ├── simulation_run.py   # Discrete-event simulation runs
│   │   └── analysis_log.py  # Prediction vs actual telemetry logs
│   ├── services/            # Pure Business & Database Access Services
│   │   ├── __init__.py
│   │   ├── auth_service.py  # Session lifecycle, rate-limiting & decorators
│   │   ├── user_service.py  # User authentication & RBAC authorization
│   │   ├── drone_service.py # Fleet management & status transition rules
│   │   └── assignment_service.py # Transactional dispatch & conflict prevention
│   ├── templates/           # Jinja2 Templates
│   │   ├── base.html        # Shared master layout with role-aware sidebar & topbar
│   │   ├── auth/
│   │   │   └── login.html   # Professional login portal with demo credentials
│   │   ├── dashboard/
│   │   │   ├── admin_dashboard.html     # System-wide metrics, fleet oversight & logs
│   │   │   ├── operator_dashboard.html  # Live missions, dispatch console & queue
│   │   │   ├── requester_dashboard.html # Emergency order intake & personal logs
│   │   │   └── request_detail.html      # Cargo specifications & telemetry
│   │   └── errors/
│   │       ├── 403.html     # Forbidden / IDOR violation screen
│   │       ├── 404.html     # Page not found screen
│   │       └── 500.html     # Internal error screen
│   └── static/              # Client-side static assets
│       ├── css/style.css    # Emergency-operations design system
│       └── js/main.js       # Vanilla JS (alerts, form double-submission prevention)
│
├── migrations/              # Alembic / Flask-Migrate versioned migrations
├── scripts/                 # Maintenance, migration, and simulation seed scripts
│   ├── init_db.py           # Database auto-creation & schema initializer
│   ├── seed_db.py           # Demonstration dataset seeder
│   └── create_admin.py      # Secure interactive/automated administrator initializer
├── instance/                # Local runtime instances / sqlite fallbacks
│   └── drone_system.db
├── tests/                   # Pytest test suite (28 automated tests)
│   ├── __init__.py
│   ├── conftest.py          # App context, HTTP client, and clean DB fixtures
│   ├── test_auth_and_dashboards.py # Login, logout, rate limiting, RBAC, IDOR tests
│   ├── test_health.py       # Health endpoint unit and integration tests
│   ├── test_user_model.py   # User hashing, roles, and RBAC tests
│   ├── test_drone_model.py  # Drone state transitions and lifecycle tests
│   ├── test_delivery_request_and_routes.py # Coordinate bounds, routes, and waypoints
│   ├── test_drone_assignment_service.py   # Transactional dispatch & conflict prevention
│   └── test_simulation_and_analysis_logs.py # Simulation lifecycle and logs
├── .env.example             # Template for required environment variables
├── .gitignore               # Ignored files (virtualenvs, secrets, cache)
├── requirements.txt         # Pinned and compatible Python dependencies
├── run.py                   # Application entry point script
└── README.md                # Project documentation and engineering roadmap
```

---

## 4. Role-Based Access Control (RBAC) & Security

| Role | Permitted Actions | Portal Route |
| :--- | :--- | :--- |
| **`ADMIN`** | System-wide statistics, fleet oversight, manage users, all delivery requests, route evaluations, simulation logs, system health. | `/admin/dashboard` |
| **`OPERATOR`** | Operational delivery requests queue, available fleet inspection, dispatching eligible drones to requests, aborting/completing missions. | `/operator/dashboard` |
| **`REQUESTER`** | Emergency cargo order submission, tracking personal delivery requests, viewing estimated delivery arrival. | `/requester/dashboard` |

### Security Protections Enforced:
1. **Server-Side Authorization**: Evaluated in decorators `@login_required` and `@role_required(*roles)`.
2. **Insecure Direct Object Reference (IDOR) Guard**: In `/requests/<request_id>`, requesters are restricted from viewing any delivery request where `req.requester_id != current_user.id` (returns HTTP `403 Forbidden`).
3. **Password Security**: Scrypt hashing via Werkzeug (`generate_password_hash`); plaintext passwords are never stored or logged.
4. **Brute-Force Rate Limiting**: Temporary 5-minute lockout triggered after 5 consecutive failed attempts per IP/account.
5. **CSRF Protection**: All state-changing HTML forms (`POST`) require valid CSRF tokens via Flask-WTF.
6. **Session Fixation Prevention**: Session regenerates upon login (`session.clear()`) with `HttpOnly` and `SameSite=Lax` cookie flags.

---

## 5. Pre-Seeded Demonstration Accounts

When the database is seeded (`python scripts/seed_db.py`), three accounts are available:

| Role | Email | Password |
| :--- | :--- | :--- |
| **Admin** | `admin@emergencydrone.org` | `AdminSecurePassword123!` |
| **Operator** | `operator@emergencydrone.org` | `OperatorSecurePassword123!` |
| **Requester** | `requester@hospital.org` | `RequesterSecurePassword123!` |

---

## 6. Creating New Users & Safe Admin Setup

### Method 1: Safe Administrator Setup Script
To create the first production administrator without committing default passwords to version control:
```powershell
# Interactive mode (prompts securely for password):
python scripts/create_admin.py

# Or via environment variables:
$env:ADMIN_NAME="Chief Administrator"
$env:ADMIN_EMAIL="superadmin@emergencydrone.org"
$env:ADMIN_PASSWORD="CustomSecurePassword123!"
python scripts/create_admin.py
```

### Method 2: Programmatic Service Layer
New users of any role can be provisioned in code via `UserService`:
```python
from app.services.user_service import UserService

user = UserService.register_user(
    full_name="Dr. Marcus Bell",
    email="mbell@hospital.org",
    password="SecurePassword123!",
    role="REQUESTER",  # "ADMIN", "OPERATOR", or "REQUESTER"
)
```

---

## 7. Windows PowerShell Quickstart Guide

### Step 1: Open Terminal & Activate Virtual Environment
```powershell
Set-Location "C:\Users\Sahiti\.gemini\antigravity\scratch\smart-emergency-drone-system"
.\.venv\Scripts\Activate.ps1
```

### Step 2: Initialize Database & Seed Demo Data
```powershell
python scripts/init_db.py
python scripts/seed_db.py
```

### Step 3: Run Full Automated Test Suite (28 Tests)
```powershell
pytest -v
```

### Step 4: Launch Development Server
```powershell
python run.py
```
Open **`http://127.0.0.1:5000/login`** in your browser.

---

## 8. Development Roadmap

| Phase | Title | Scope & Deliverables | Status |
| :---: | :--- | :--- | :---: |
| **Phase 1** | **Foundation & Architecture** | Project structure, environment config, application factory, health-check endpoint, and initial test suite. | **Completed** |
| **Phase 2** | **Data Models & Persistence Layer** | Normalized 3NF MySQL/SQLAlchemy schema, Flask-Migrate versioning, state machines, conflict prevention transactions, demonstration seeder, and test suite. | **Completed** |
| **Phase 3** | **Authentication, RBAC & Dashboards** | Secure session authentication, CSRF protection, rate limiting, shared emergency layout, role-specific dashboards, IDOR guard, and admin creator. | **Completed** |
| **Phase 4** | **Route Optimization Engine** | Haversine distance calculations, Dijkstra / A* routing with no-fly zone polygon avoidance, battery and payload feasibility validator. | Upcoming |
| **Phase 5** | **Delivery Simulation Engine** | Discrete-time simulation service, waypoint interpolation, simulated telemetry broadcast, incident handling (battery low, rerouting). | Planned |
| **Phase 6** | **Interactive Web Dashboard** | Leaflet.js real-time drone tracking map, dispatch console, order submission form, emergency telemetry metrics. | Planned |
| **Phase 7** | **Analytics & System Verification** | Pandas analytics pipeline for post-flight metrics, full integration test suite, deployment documentation. | Planned |
