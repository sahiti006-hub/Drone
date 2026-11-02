# Smart Multipurpose Emergency Drone Delivery and Route Optimization System

A modular, simulation-driven emergency dispatch and route optimization platform built for rapid medical, disaster relief, and high-priority supply transit.

---

## 1. Project Overview

The **Smart Multipurpose Emergency Drone Delivery and Route Optimization System** is a full-stack engineering solution designed to simulate, schedule, and optimize autonomous drone delivery operations for mission-critical and emergency supplies (e.g., blood packages, antivenoms, defibrillators, disaster kits).

The system integrates real-time geospatial tracking (via Leaflet.js and OpenStreetMap), multi-criteria route optimization algorithms, dynamic battery/payload depletion modeling, and persistent audit logging via MySQL and Pandas data pipelines.

> **Note on Scope**: In accordance with the initial engineering specification, this system operates in **simulation mode**. It models physical constraints (speed, payload limits, battery discharge, no-fly zones, and weather factors) through software mathematical models without requiring physical drone hardware control.

---

## 2. Technology Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript (ES6+) | Interactive operator dashboard, status telemetry, request intake forms |
| **Map Engine** | Leaflet.js, OpenStreetMap | Geospatial rendering, live path interpolation, waypoint and base station markers |
| **Backend** | Python 3.10+, Flask | Modular REST API service, application factory pattern, service-layer orchestration |
| **Database** | MySQL, SQLAlchemy, PyMySQL | Relational schema for drones, orders, hubs, flight logs, and telemetry histories |
| **Analytics** | Pandas, NumPy | Route analysis, energy consumption metrics, dispatch efficiency reports |
| **Testing** | Pytest, Pytest-Cov | Unit testing, integration testing, and API contract test automation |
| **Version Control** | Git | Distributed version management and change traceability |

---

## 3. Architecture & Modular Design

The project uses the **Flask Application Factory Pattern** combined with strict separation of concerns:

```text
smart-emergency-drone-system/
│
├── app/
│   ├── __init__.py          # Flask Application Factory (create_app)
│   ├── config.py            # Environment-aware configurations (Dev, Test, Prod)
│   ├── extensions.py        # Extensions lifecycle management (SQLAlchemy)
│   ├── routes/              # HTTP Route Blueprints & Request Handlers
│   │   ├── __init__.py
│   │   └── health.py        # Health-check and system readiness endpoints
│   ├── models/              # Relational database models (Drones, Deliveries, Stations)
│   │   └── __init__.py
│   ├── services/            # Pure business logic (Routing, Battery, Simulation)
│   │   └── __init__.py
│   ├── templates/           # Server-side HTML Jinja2 templates
│   └── static/              # Client-side static assets
│       ├── css/             # Stylesheets (CSS3 custom properties)
│       ├── js/              # Vanilla JavaScript (Leaflet map controller, telemetry)
│       └── images/          # Markers, icons, and diagrams
│
├── tests/                   # Pytest test suite
│   ├── __init__.py
│   ├── conftest.py          # App context and HTTP client fixtures
│   └── test_health.py       # Health endpoint unit and integration tests
│
├── scripts/                 # Maintenance, migration, and simulation seed scripts
├── instance/                # Local runtime instances / temp files
├── .env.example             # Template for required environment variables
├── .gitignore               # Ignored files (virtualenvs, secrets, cache)
├── requirements.txt         # Pinned and compatible Python dependencies
├── run.py                   # Application entry point script
└── README.md                # Project documentation and engineering roadmap
```

### Architectural Principles:
1. **Application Factory (`create_app`)**: Allows dynamic instantiation across development, testing, and production environments with isolated configs.
2. **Layered Decoupling**:
   - `routes/` handles HTTP parsing, validation, and JSON formatting.
   - `services/` contains purely functional business calculations (Haversine/Dijkstra routing, battery discharge algorithms).
   - `models/` manages persistence and database mappings.
3. **Environment Security**: Sensitive keys and database credentials are fully externalized via `.env`. No credentials or passwords are hardcoded.

---

## 4. Prerequisites

Before installing, ensure your environment meets the following requirements:
- **Operating System**: Windows 10/11, Linux, or macOS (commands below are tailored for Windows PowerShell).
- **Python**: Version 3.10 to 3.14 (Verified with Python 3.14.6).
- **MySQL Server**: MySQL 8.0+ (Required starting from Phase 2).
- **Git**: Installed and available on `PATH`.

---

## 5. Quickstart & Setup Guide (Windows PowerShell)

### Step 1: Open Terminal in Project Directory
```powershell
cd "C:\Users\Sahiti\.gemini\antigravity\scratch\smart-emergency-drone-system"
```

### Step 2: Create and Activate Python Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> *Tip: If PowerShell execution policy restricts script execution, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`.*

### Step 3: Install Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy the `.env.example` template to `.env`:
```powershell
Copy-Item .env.example .env
```
Update `.env` with your local database and server parameters as needed.

### Step 5: Execute Automated Test Suite
```powershell
pytest -v
```

### Step 6: Start the Development Server
```powershell
python run.py
```
The server will boot and display:
```text
[*] Starting Smart Emergency Drone Delivery System in development mode...
[*] Listening on http://127.0.0.1:5000
[*] Health check available at http://127.0.0.1:5000/api/health
```

### Step 7: Verify System Health
Open your browser or run:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/health" -Method Get
```
Response:
```json
{
  "environment": "development",
  "service": "Smart Multipurpose Emergency Drone Delivery System",
  "simulation_mode": true,
  "status": "healthy",
  "timestamp": "2026-11-02T12:01:43.026063+00:00",
  "version": "1.0.0-phase1"
}
```

---

## 6. Phased Development Roadmap

| Phase | Title | Scope & Deliverables | Status |
| :---: | :--- | :--- | :---: |
| **Phase 1** | **Foundation & Architecture** | Project structure, environment configuration, application factory, dependency definition, health-check endpoint, and automated test suite. | **Completed** |
| **Phase 2** | **Data Models & Persistence** | MySQL schema design, SQLAlchemy ORM models (Drones, Stations, Orders, Deliveries), migration and seeder scripts, model test cases. | Upcoming |
| **Phase 3** | **Route Optimization Engine** | Geospatial distance calculation (Haversine), Dijkstra/A* routing with no-fly zone avoidance, battery and payload feasibility validator. | Planned |
| **Phase 4** | **Delivery Simulation Engine** | Discrete-time simulation service, waypoint interpolation, simulated telemetry broadcast, incident handling (battery low, rerouting). | Planned |
| **Phase 5** | **Interactive Web Dashboard** | Leaflet.js real-time drone tracking map, dispatch console, order submission form, emergency telemetry metrics. | Planned |
| **Phase 6** | **Analytics & System Verification** | Pandas analytics pipeline for post-flight metrics, full integration test suite, deployment documentation. | Planned |

---

## 7. Phase 1 Acceptance Criteria

- [x] Dedicated project folder established with modular architecture.
- [x] Dependencies pinned in `requirements.txt`.
- [x] Virtual environment configured and verified on Windows PowerShell.
- [x] Strict `.gitignore` protecting secrets, virtual environments, and caches.
- [x] Environment variable configuration template `.env.example` created.
- [x] Application Factory pattern implemented in `app/__init__.py`.
- [x] `/api/health` endpoint returning 200 OK and system status JSON.
- [x] Automated test suite configured and passing under `pytest`.
- [x] Server start and HTTP probe verified.
