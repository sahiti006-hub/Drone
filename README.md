# DroneDispatch (Drone)
## Smart Multipurpose Emergency Drone Delivery and Route Optimization System

[![Automated Tests](https://img.shields.io/badge/pytest-162%20passed-success)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-81%25-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.14-blue)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Flask%203.1-informational)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/database-MySQL%20%2F%20SQLAlchemy%202.0-orange)](https://www.sqlalchemy.org/)
[![Frontend](https://img.shields.io/badge/maps-Leaflet.js%20%7C%20OpenStreetMap-green)](https://leafletjs.com/)

---

## 1. Project Overview

**DroneDispatch** is an academic software platform and simulation engine designed for rapid emergency aerial transit and consumer on-demand logistics. The platform coordinates multi-drone fleet allocation, generates 3D flight corridors, evaluates meteorological safety constraints, performs multi-objective route optimization, and executes real-time discrete kinematic flight simulations.

Inspired by on-demand ride-hailing and courier services, DroneDispatch incorporates a full consumer-facing booking workflow, two-way delivery directions (**SEND** outbound and **RECEIVE** inbound collection), dynamic mathematical pricing with surge control, simulated cashless payments, automated invoicing, real-time public parcel tracking, and dynamic in-flight weather rerouting.

---

## 2. Problem Statement

Traditional surface emergency transit and medical courier logistics encounter severe bottlenecks:
1. **Unpredictable Surface Congestion:** Urban gridlock and vehicular traffic introduce high variance into critical medical transit windows (e.g., organ transit, antivenom delivery, blood supply replenishment).
2. **Terrain and Infrastructure Obstacles:** Rural primary healthcare centers, hilly terrains, and disaster-affected zones often suffer from damaged or impassable roadway networks.
3. **Suboptimal Airspace Navigation:** Naive direct point-to-point drone dispatch without dynamic environmental feasibility analysis risks battery exhaustion, cargo overload, and flight through adverse weather conditions.
4. **Lack of Operational Governance:** Emergency logistics require strict role-aware access controls, atomic hardware inventory locking, dynamic pricing transparency, and auditability.

---

## 3. Project Objectives

- **Modular Software Architecture:** Decouple controllers, ORM persistence, domain models, and algorithmic optimization into maintainable, independently testable layers.
- **Deterministic 3D Flight Corridor Generation:** Generate discrete geometric airspace corridors (Direct, Port Peripheral, Starboard Peripheral, High-Altitude) without dependence on road infrastructure.
- **Fail-Safe Feasibility Validation:** Enforce physical multi-rotor bounds including maximum payload rating, battery discharge curves with mandatory 15% non-depletable reserve, sustained wind thresholds, visibility limits, and precipitation tolerance.
- **Multi-Objective Route Optimization:** Formulate and benchmark a normalized scalarized cost optimizer (Distance: 0.35, Energy: 0.30, Risk: 0.20, Time: 0.15) against a shortest-feasible baseline.
- **Interactive Consumer Booking & Tracking:** Provide an intuitive map-based interface supporting SEND and RECEIVE operational workflows, transparent dynamic pricing quotes with 10-minute validity, and live Leaflet.js tracking.
- **Safety-First In-Flight Autonomy:** Continuously monitor simulated weather changes to trigger dynamic rerouting around storm cells or initiate emergency diversions to designated landing zones and helipads.
- **Simulated Cashless Payments:** Provide simulated UPI, Card, Netbanking, and Fleet Wallet transactions with automated invoicing and refund guarantees.

---

## 4. Key Features

- **Role-Based Access Control (RBAC):** Distinct dashboards and security boundaries for Requesters, Operators, and Administrators.
- **Two-Way Delivery Experience:** First-class support for outbound **SEND** (user to recipient) and inbound **RECEIVE** (remote collection to user) delivery models.
- **Universal Cargo Support:** Pre-configured emergency medical categories alongside custom item entry with mass and safety declarations.
- **Real-Time Fleet Availability:** Instant eligibility matching based on battery charge, payload bounds, active maintenance, and range feasibility.
- **Multi-Drone Allocation:** Priority Best-Fit heuristic allocation compared against a First-Come-First-Served (FCFS) baseline.
- **Dynamic Pricing Engine:** Multi-factor pricing model accounting for distance, payload mass, urgency multiplier, weather risk, and demand surge.
- **Weather Intelligence:** Real-time atmospheric analysis enforcing Green/Yellow/Red dispatch thresholds, mid-flight storm rerouting, and helipad diversions.
- **Simulated Cashless Payments:** Mock payment gateway integration supporting UPI, Card, Netbanking, and Wallet transactions with automated refund management.
- **Itemized Tax Invoicing:** Formatted GST-compliant tax invoices detailing all fare components.
- **Public Recipient Tracking:** Anonymous, secure tracking page with masked recipient contact data.
- **Advisory Machine Learning:** Ridge Regression flight duration and energy estimation module.
- **Operational & Financial Analytics:** Comprehensive reporting dashboards with chart visualizations and CSV export capabilities.

---

## 5. SEND and RECEIVE Delivery Workflows

DroneDispatch supports two primary logistical models:

### Workflow A: SEND (Outbound Dispatch)
- **Origin ($\vec{X}_{\text{start}}$):** The requester's home, clinic, or selected dispatch hub.
- **Destination ($\vec{X}_{\text{end}}$):** The remote delivery address or medical facility.
- **Use Case:** A clinic dispatching urgent blood samples, antivenom vials, or defibrillators to a field hospital.
- **UI Experience:** Blue branding badge, pickup location defaulting to user location, manual or map-pinned recipient destination.

### Workflow B: RECEIVE (Inbound Remote Collection)
- **Origin ($\vec{X}_{\text{start}}$):** A remote blood bank, supplier, pharmacy, or diagnostic laboratory.
- **Destination ($\vec{X}_{\text{end}}$):** The requester's current facility or home address.
- **Use Case:** A rural primary health center requesting emergency vaccine pickup from an urban medical warehouse.
- **Collection Safeguards:** Requester specifies remote sender contact name, verified phone number, specific collection instructions, and an authorization verification OTP/PIN.
- **Physical Routing Invariance:** In both models, physical flight kinematics and energy consumption are strictly computed along the true directional vector ($\vec{X}_{\text{start}} \to \vec{X}_{\text{end}}$).

---

## 6. Universal Cargo Delivery Support

The platform enforces cargo payload ratings and packaging restrictions:

| Cargo Category | Max Mass Limit | Special Handling | Safety Flags |
| :--- | :--- | :--- | :--- |
| **Blood & Organs** | 3.5 kg | Temperature-controlled pod, high urgency | Biological, Fragile |
| **Medications** | 4.0 kg | Sealed medical capsule, anti-vibration | Fragile |
| **First Aid & AED** | 5.0 kg | Quick-release latch, emergency beacon | High Priority |
| **Antivenom / Vaccines** | 3.0 kg | Cold-chain refrigeration pod | Temperature-sensitive |
| **Critical Documents** | 1.0 kg | Waterproof tamper-evident pouch | Confidential |
| **Sensitive Electronics** | 3.5 kg | Padded anti-static enclosure | Shock-sensitive |
| **Custom Package** | 5.0 kg | User-declared weight & safety specifications | Configurable |

---

## 7. System Architecture

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
                                  |   /auth, /booking, /admin, /operator  |
                                  |      /simulation, /analytics         |
                                  +---------------------------------------+
                                                     |
                                       Pure Python Business Services
                                                     |
         +--------------------+----------------------+--------------------+--------------------+
         |                    |                      |                    |                    |
+-----------------+  +------------------+  +-------------------+  +------------------+  +------------------+
|  AuthService    |  | DroneService     |  | RouteOptimizer    |  | PricingService   |  | SimulationService |
|  • RBAC & Rate  |  | • State Machine  |  | • Candidate Gen   |  | • Dynamic Multi- |  | • Kinematics     |
|    Limiting     |  | • Fleet Inventory|  | • Multi-Objective |  |   Variable Fare  |  | • Checkpoints    |
|  • Session Guard|  | • Hardware Specs |  | • Feasibility Check|  | • Expiry Timer   |  | • Interpolation  |
+-----------------+  +------------------+  +-------------------+  +------------------+  +------------------+
         |                    |                      |                    |                    |
         +--------------------+----------------------+--------------------+--------------------+
                                                     |
                      +------------------------------+------------------------------+
                      |                                                             |
             +------------------+                                          +------------------+
             | WeatherService   |                                          | PaymentService   |
             | • Safety Gates   |                                          | • Mock Gateway   |
             | • Dynamic Reroute|                                          | • Invoicing      |
             | • Helipad Divers.|                                          | • Refund Manager |
             +------------------+                                          +------------------+
                                                     |
                                       Object-Relational Mapping
                                         (SQLAlchemy 2.0 ORM)
                                                     |
                                  +---------------------------------------+
                                  |       Relational Persistence          |
                                  |    MySQL 8.0 (InnoDB) / SQLite (Test) |
                                  +---------------------------------------+
```

---

## 8. Technology Stack

- **Backend Framework:** Python 3.11+ / Flask 3.1
- **Database & ORM:** MySQL 8.0 (InnoDB engine with row-level locks) / SQLAlchemy 2.0
- **Database Migrations:** Flask-Migrate / Alembic (linear migration chain)
- **Frontend & Mapping:** HTML5, CSS3, JavaScript (ES6+), Leaflet.js, OpenStreetMap tiles
- **Machine Learning:** Scikit-learn (Ridge Regression), NumPy, Pandas
- **Testing & Quality:** Pytest, Pytest-Cov (162 automated tests, 81% code coverage)
- **Containerization:** Docker, Docker Compose, Gunicorn WSGI

---

## 9. Major Modules

1. **Authentication (`app/routes/auth.py`, `app/services/auth_service.py`):** User registration, password hashing (PBKDF2-SHA256), session management, and RBAC enforcement.
2. **Booking & Dispatch (`app/routes/booking_routes.py`, `app/services/delivery_service.py`):** Consumer-facing parcel booking, SEND/RECEIVE mode selection, address geocoding, and order lifecycle management.
3. **Drone Inventory (`app/services/drone_service.py`):** Drone registry, operational status tracking (`IDLE`, `ASSIGNED`, `IN_FLIGHT`, `MAINTENANCE`), battery level monitoring, and specifications.
4. **Route Optimizer (`app/services/route_optimizer.py`):** 3D corridor synthesis, flight feasibility checks, and multi-objective Pareto-like cost evaluation.
5. **Dynamic Pricing (`app/services/pricing_service.py`):** Mathematical fare calculator with surge pricing and time-limited cryptographic quote generation.
6. **Weather Intelligence (`app/services/weather_intelligence_service.py`):** Real-time meteorological risk classification, pre-flight dispatch gates, and in-flight storm alerts.
7. **Simulation Engine (`app/services/simulation_service.py`):** Discrete-time kinematic interpolation, waypoint tracking, battery consumption modeling, dynamic rerouting, and emergency helipad diversion.
8. **Payment Service (`app/services/payment_service.py`):** Simulated payment gateway supporting Card, UPI, Netbanking, and Fleet Wallet, with automated invoice and refund handling.
9. **Advisory ML (`app/ml/prediction_service.py`):** Machine learning surrogate model predicting flight duration and energy consumption.
10. **Analytics & Reporting (`app/routes/analytics_routes.py`, `app/services/analytics_service.py`):** Operational performance metrics, revenue tracking, fleet utilization, and CSV data export.

---

## 10. Route Optimization Methodology

The system generates candidate 3D flight corridors and evaluates them against physical feasibility constraints before selecting the optimal path:

### Candidate Corridor Generation
For any pickup coordinate $\vec{X}_{\text{start}}$ and destination coordinate $\vec{X}_{\text{end}}$:
1. **Direct Path (0m lateral offset):** Direct geometric line at 100m cruising altitude.
2. **Port Corridor (-50m lateral offset):** Lateral deviation to avoid central airspace bottlenecks.
3. **Starboard Corridor (+50m lateral offset):** Alternative lateral deviation path.
4. **High-Altitude Corridor (150m altitude):** Vertical separation corridor for obstacle clearance.

### Multi-Objective Objective Function
Candidate corridors are evaluated using a min-max normalized weighted cost scalarization:

$$\text{Cost} = w_1 \cdot \widehat{\text{Distance}} + w_2 \cdot \widehat{\text{Energy}} + w_3 \cdot \widehat{\text{Risk}} + w_4 \cdot \widehat{\text{Time}}$$

Where normalized weights sum to unity:
- $w_1 = 0.35$ (Distance Minimization)
- $w_2 = 0.30$ (Energy & Battery Conservation)
- $w_3 = 0.20$ (Airspace & Weather Risk Mitigation)
- $w_4 = 0.15$ (Transit Duration Optimization)

$$\sum_{i=1}^{4} w_i = 0.35 + 0.30 + 0.20 + 0.15 = 1.00$$

---

## 11. Drone Feasibility and Battery Reserve

Before dispatch, the engine verifies hard feasibility constraints:
1. **Payload Feasibility:**
   $$\text{Package Mass} \le \text{Drone Max Payload Rating}$$
2. **Energy Feasibility:**
   $$\text{Estimated Flight Energy Consumption} + \text{Emergency Reserve (15\%)} \le \text{Current Battery Capacity}$$
3. **Non-Depletable Battery Reserve:** A mandatory 15% charge is reserved exclusively for emergency maneuvers, headwind compensation, and safe landing procedures.
4. **Range Feasibility:**
   $$\text{Corridor Distance} \le \text{Drone Operational Radius}$$

---

## 12. Weather Intelligence

The system evaluates atmospheric conditions against predefined multi-rotor safety thresholds:

| Condition Metric | Green (Permissible) | Yellow (Cautionary) | Red (Unfeasible - Dispatch Blocked) |
| :--- | :--- | :--- | :--- |
| **Sustained Wind Speed** | $\le 8.0\text{ m/s}$ | $8.1 - 12.0\text{ m/s}$ | $> 12.0\text{ m/s}$ |
| **Precipitation Rate** | $\le 2.0\text{ mm/h}$ | $2.1 - 8.0\text{ mm/h}$ | $> 8.0\text{ mm/h}$ |
| **Visual Range** | $\ge 5.0\text{ km}$ | $2.0 - 4.9\text{ km}$ | $< 2.0\text{ km}$ |

When meteorological conditions are classified as **Red**, the booking interface blocks dispatch and alerts the user with safety advisories.

---

## 13. Emergency Rerouting and Helipad Diversion

### Dynamic In-Flight Rerouting
During flight simulation, if weather conditions deteriorate along an active flight segment:
1. The simulation detects the storm zone obstacle.
2. `RouteOptimizer` dynamically computes an evasion corridor with positive or negative lateral offsets.
3. Active waypoints are dynamically updated, and the drone continues to its destination safely.

### Emergency Helipad Diversion
If a drone suffers catastrophic battery depletion ($<15\%$) or unrecoverable weather degradation:
1. The simulation immediately aborts the delivery mission.
2. The nearest registered emergency helipad or landing zone is selected using Euclidean spatial indexing.
3. The drone diverts to the emergency site and executes a safe landing.
4. The requester's order status transitions to `DIVERTED`, and an automated refund is triggered.

---

## 14. Dynamic Mathematical Pricing

Fares are calculated transparently using an itemized mathematical model:

$$\text{Fare} = \left[ \text{Base Fare} + (\text{Distance} \times \text{Rate}_{\text{km}}) + (\text{Mass} \times \text{Rate}_{\text{kg}}) \right] \times M_{\text{urgency}} \times M_{\text{weather}} \times M_{\text{surge}}$$

### Baseline Parameters:
- **Base Fare:** ₹150.00
- **Distance Rate:** ₹25.00 per kilometer
- **Weight Rate:** ₹15.00 per kilogram
- **Urgency Multiplier ($M_{\text{urgency}}$):**
  - Normal: $1.0\times$
  - High: $1.25\times$
  - Urgent: $1.50\times$
- **Weather Multiplier ($M_{\text{weather}}$):**
  - Green (Normal): $1.0\times$
  - Yellow (Adverse Caution): $1.20\times$
- **Demand Surge Multiplier ($M_{\text{surge}}$):** $1.0\times$ to $2.0\times$ based on active fleet utilization.
- **Quote Expiration:** Quotes are valid for exactly **10 minutes (600 seconds)** with a live UI countdown timer.

---

## 15. Simulated Payment System

DroneDispatch incorporates a simulated cashless payment module:
- **Supported Payment Methods:** Simulated UPI (Virtual Payment Address validation), Simulated Credit/Debit Cards (Luhn algorithm checks), Netbanking, and Fleet Wallet.
- **Transaction Flow:** Quotes transition from `PENDING_PAYMENT` to `CONFIRMED` upon payment authorization.
- **Automated Invoicing:** A GST-compliant tax invoice is generated with itemized base charges, surcharges, and tax calculations.
- **Automated Refunds:** If a mission is cancelled prior to launch or aborted during flight due to safety diversion, `PaymentService.process_refund()` credits the user's wallet or original payment instrument.

---

## 16. Machine Learning Prediction Module

An advisory machine learning module assists human operators by providing fast estimates of mission duration and energy consumption:
- **Model Architecture:** Scikit-learn Ridge Regression with L2 regularization ($\alpha = 1.0$).
- **Features Evaluated:** Flight distance, payload mass, cruise speed, wind speed, headwind component, ambient temperature.
- **Training Data:** Synthetically generated physics simulation dataset spanning 1,000+ flight records.
- **Performance Metrics:** $R^2 \approx 0.94$, Mean Absolute Error ($\text{MAE}$) $\approx 1.2$ minutes.
- **Academic Role:** Advisory only; all physical flight dispatches are governed by deterministic kinematic formulas.

---

## 17. Database Architecture

The persistence layer uses SQLAlchemy 2.0 with a linear Alembic migration chain.

### Core Relational Entities:
1. `User`: User identity, credentials, roles (`admin`, `operator`, `requester`), wallet balance.
2. `Drone`: Fleet inventory, model, max payload, battery capacity, status, coordinates.
3. `DeliveryRequest`: Delivery specifications, direction (`SEND` / `RECEIVE`), pickup/destination coordinates, cargo category, urgency tier, collection metadata (`sender_name`, `sender_phone`, `collection_otp`, `collection_notes`).
4. `Route`: Generated 3D flight paths, total distance, estimated energy, risk index, feasibility status.
5. `RouteWaypoint`: Discrete coordinate waypoints (latitude, longitude, altitude, sequence).
6. `DroneQuote`: Fare quotations, itemized pricing breakdown, expiration timestamps.
7. `DroneBooking`: Confirmed delivery bookings, payment references, tracking numbers.
8. `DronePayment`: Transaction records, payment method, payment status, timestamps.
9. `DroneRefund`: Refund audit records, refund reasons, transaction links.
10. `SavedLocation`: User address book for frequent dispatch and collection points.
11. `DeliveryRating`: Post-delivery feedback and star ratings.
12. `WeatherCondition`: Environmental snapshots, wind vectors, precipitation readings.
13. `ReroutingEvent`: In-flight detour and diversion audit logs.
14. `AuditLog`: System-wide security and administrative audit trail.

---

## 18. Installation Instructions (Windows & Linux)

### Prerequisites:
- Python 3.11, 3.12, or 3.14 installed on your PATH.
- Git installed.
- (Optional) MySQL 8.0 if running in production mode. Local development defaults to SQLite.

### Clone the Repository:
```bash
git clone https://github.com/sahiti006-hub/Drone.git
cd Drone
```

### Windows Setup:
```powershell
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install package dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Linux / macOS Setup:
```bash
# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 19. Environment Configuration

Create a local `.env` configuration file from the provided template:

```bash
# Copy template to .env
cp .env.example .env
```

Ensure the following default development settings in `.env`:
```ini
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=dev-secret-key-change-in-production
HOST=127.0.0.1
PORT=5000
```

---

## 20. Database Migration Instructions

Initialize and apply database migrations to configure all tables:

```powershell
# Verify current migration status
flask db current

# Apply all migrations to the latest revision (head)
flask db upgrade
```

To seed initial demonstration users, drones, and test requests:
```powershell
python scripts/seed_demo_data.py
```

---

## 21. Running the Flask Application

Launch the development server:

```powershell
python run.py
```

The application will be accessible at:
- **Web Portal:** [http://127.0.0.1:5000](http://127.0.0.1:5000) or [http://localhost:5000](http://localhost:5000)
- **Health Check API:** [http://127.0.0.1:5000/api/health](http://127.0.0.1:5000/api/health)

### Default Demonstration Accounts:
| Role | Email | Password | Access Capabilities |
| :--- | :--- | :--- | :--- |
| **Requester** | `requester@dronedispatch.com` | `Requester@123` | SEND/RECEIVE bookings, pricing quotes, mock payments, live tracking |
| **Operator** | `operator@dronedispatch.com` | `Operator@123` | Dispatch cockpit, flight radar, kinematic simulations, maintenance |
| **Administrator** | `admin@dronedispatch.com` | `Admin@123` | Fleet management, financial analytics, system settings, user roles |

---

## 22. Running Automated Tests

Run the complete test suite with coverage:

```powershell
pytest
```

To view code coverage details across individual modules:
```powershell
pytest --cov=app --cov-report=term-missing
```

### Verified Test Baseline:
- **Total Tests:** 162 passed (0 failed, 0 skipped)
- **Execution Time:** ~29 seconds
- **Overall Line Coverage:** **81%** across 4,351 statements
- **Core Modules:**
  - Route Optimizer: **96%**
  - Prediction Service: **98%**
  - Pricing Service: **95%**
  - Weather Intelligence: **93%**
  - Drone Availability: **91%**
  - Drone Allocation: **89%**

---

## 23. Docker Deployment

Deploy the entire stack (Flask application + MySQL 8.0) using Docker Compose:

```bash
# Build and start containers in detached mode
docker compose up --build -d

# Check service logs
docker compose logs -f app

# Stop containers
docker compose down
```

---

## 24. Academic Simulation Limitations & Disclosures

To maintain strict academic integrity, the following limitations must be noted:
1. **Software-Only Drone Simulation:** The application is a software-based kinematic simulation. It does not interface with physical drone hardware, microcontrollers, or flight avionics (e.g., PX4, ArduPilot).
2. **Synthetic ML Training Data:** The advisory Ridge Regression model is trained on synthetic physics-approximated flight logs rather than physical flight telemetry.
3. **Simulated Weather Conditions:** Weather data is generated via internal meteorological simulation models unless an external live provider API is explicitly configured.
4. **Simulated Cashless Payments:** Payment processing, UPI verification, and wallet transactions are simulated; no actual financial clearing or currency transfer takes place.
5. **Simulated Flight Diversions:** In-flight rerouting and emergency helipad landings are computed mathematically and visualized in the browser; they do not represent physical airspace operations.

---

## 25. Future Enhancements

- Integration with physical drone flight controllers using MAVLink / ROS2 protocols.
- Airspace integration with live civil aviation radar (ADS-B) feeds.
- Computer vision landing marker detection (AprilTag / ArUco markers) for precision vertical landing.
- Deep reinforcement learning (DRL) for dynamic multi-agent collision avoidance in high-density airspace.
- Production payment gateway integration with Razorpay, Stripe, or UPI 2.0.

---
*Developed for Final-Year B.Tech Computer Science and Engineering Academic Project Submission.*
