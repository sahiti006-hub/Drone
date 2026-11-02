# Production & Academic Release Checklist

**System:** Smart Multipurpose Emergency Drone Delivery and Route Optimization System  
**Version:** 1.0.0-phase1  
**Architecture:** Python 3.14 / Flask 3.1 / SQLAlchemy 2.0 / MySQL 8.0 (Production) / SQLite3 (Local Dev/Test)  
**Verification Baseline:** 122 Passed Automated Tests / 83% Statement Coverage  

---

## 1. Prerequisites

### Host Environment Requirements
- **Operating System:** Windows 10/11, macOS, or Linux (Ubuntu 22.04 LTS / Debian 12 recommended).
- **Python Runtime:** Python 3.10, 3.11, 3.12, or 3.14.
- **Relational Database (Option A - Production):** MySQL 8.0+ server running on port 3306 with `utf8mb4` character set.
- **Relational Database (Option B - Standalone Demo):** SQLite 3.35+ (automatically provisioned in `instance/drone_system.db`).
- **Container Runtime (Optional):** Docker Engine 24.0+ and Docker Compose v2.20+.

---

## 2. Configuration Steps

### 2.1 Environment Segregation
The application strictly segregates configurations across three modes:
- `development`: Debug mode enabled, interactive reloaders, local SQLite fallback.
- `testing`: In-memory isolated database (`sqlite:///:memory:`), CSRF disabled for test clients, automated teardown.
- `production`: Debug strictly disabled, hardened session cookies (`HttpOnly`, `SameSite=Lax`, `Secure`), mandatory cryptographic secret validation, no default passwords.

### 2.2 Provisioning the `.env` File
Create a local `.env` file from `.env.example`. **Never commit the `.env` file or passwords to version control:**

```bash
# Copy template
cp .env.example .env
```

### 2.3 Generating Cryptographically Secure Secrets
In production mode, the application validates that `SECRET_KEY` is not empty, too short (< 16 characters), or set to an insecure placeholder. Generate a 64-character random hex string:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste this string into `.env` under `SECRET_KEY=`.

### 2.4 Reverse-Proxy & Cookie Security
When fronted by a reverse proxy (e.g., Nginx, Caddy, AWS ALB, Traefik) terminating TLS/HTTPS:
- Set `USE_PROXY_FIX=1` in `.env`.
- Set `SESSION_COOKIE_SECURE=1` to enforce HTTPS-only cookies.
- If testing locally on plain HTTP, set `SESSION_COOKIE_SECURE=0`.

---

## 3. Database Setup & Initialization

### 3.1 Creating the MySQL Database and Application User
Execute the following SQL commands in MySQL as root or an administrative user:

```sql
-- 1. Create dedicated database with full UTF-8 Unicode support
CREATE DATABASE IF NOT EXISTS `smart_emergency_drone_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 2. Create least-privilege application user
CREATE USER IF NOT EXISTS 'drone_user'@'localhost' IDENTIFIED BY 'StrongRandomPasswordHere!123';

-- 3. Grant schema permissions to the application user
GRANT ALL PRIVILEGES ON `smart_emergency_drone_db`.* TO 'drone_user'@'localhost';
FLUSH PRIVILEGES;
```

*(For Docker or remote setups, replace `'localhost'` with `'%'`).*

### 3.2 Non-Destructive Table Initialization
The system guarantees **zero automatic deletion** of existing databases or tables. To initialize all relational tables, foreign keys, and indexes safely:

```powershell
# Method A: Safe initialization script (idempotent; creates missing tables only)
python scripts/init_db.py

# Method B: Flask-Migrate / Alembic migrations
flask db upgrade
```

### 3.3 Safe Administrator Account Provisioning
Master administrator credentials must **never** be hardcoded in version control. Provision the administrator safely using either interactive prompt or environment variables:

```powershell
# Interactive mode (prompts with hidden password typing):
python scripts/create_admin.py

# Non-interactive / CI/CD mode:
$env:ADMIN_NAME="Chief Dispatcher"
$env:ADMIN_EMAIL="admin@emergencydrone.org"
$env:ADMIN_PASSWORD="YourSecurePassword123!"
python scripts/create_admin.py
```

### 3.4 Demonstration Seed Data (Guardrails)
Demonstration seed data is strictly isolated from production operations.
- In `development` mode: `python scripts/seed_db.py` populates sample users, drones, and hospitals.
- In `production` mode: `seed_db.py` automatically blocks execution with a safety warning unless explicitly forced via `--force` or `ALLOW_PRODUCTION_SEEDING=1`.

---

## 4. Application Startup Instructions

### Option 1: Native Windows Production Startup (Waitress WSGI)
Do **not** use the Flask development server (`flask run` or `python run.py`) in production or evaluation. Use a production WSGI server:

```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run Waitress WSGI server
waitress-serve --host=127.0.0.1 --port=5000 wsgi:app
```

### Option 2: Native Linux Production Startup (Gunicorn WSGI)
On Linux servers or virtual machines:

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Run Gunicorn with worker and thread pooling
gunicorn --bind 0.0.0.0:5000 --workers 3 --threads 2 --timeout 120 wsgi:app
```

### Option 3: Containerized Deployment (Docker Compose)
For automated, single-command reproducible evaluation with an isolated MySQL 8.0 container:

```bash
# 1. Build and start containers in detached mode
docker compose up --build -d

# 2. Verify container status and health checks
docker compose ps

# 3. View application startup and WSGI logs
docker compose logs -f app

# 4. Graceful shutdown
docker compose down
```

---

## 5. Post-Deployment Smoke Tests & Verification

Verify operational readiness after startup:

### Smoke Test 1: Automated Unit & Integration Suite
Execute the 122-test automated suite with line coverage:
```powershell
pytest -q --cov=app
# Expected: 122 passed in ~22s, 83% statement coverage
```

### Smoke Test 2: HTTP Health Probe
Verify that the service returns HTTP 200 and healthy JSON telemetry:
```bash
curl -f http://127.0.0.1:5000/api/health
```
Expected output:
```json
{
  "environment": "production",
  "service": "Smart Multipurpose Emergency Drone Delivery System",
  "simulation_mode": true,
  "status": "healthy",
  "timestamp": "2026-11-03T01:00:00.000000+00:00",
  "version": "1.0.0-phase1"
}
```

### Smoke Test 3: Full End-to-End Mission Verification
Execute the automated 11-phase workflow script:
```powershell
python scripts/demonstrate_full_workflow.py
```
Expected: All 11 phases pass, verifying admin login, drone creation, emergency request submission, 3D corridor generation, multi-objective optimization, simulation start/pause/resume, dynamic rerouting, and safeguard rejection.

### Smoke Test 4: Error Handler Stack Trace Prevention
Request an invalid endpoint or invalid JSON payload to confirm that no stack traces or sensitive internal paths are leaked to clients:
```bash
curl -H "Accept: application/json" http://127.0.0.1:5000/api/nonexistent-route
```
Expected output:
```json
{"error": "Resource Not Found", "status": 404, "success": false}
```

---

## 6. Backup and Recovery Guidance

### 6.1 Backing Up the MySQL Database
Perform a non-blocking logical backup using `mysqldump`:

```bash
# Linux / macOS / Bash:
mysqldump -u drone_user -p --single-transaction --quick --routines --triggers smart_emergency_drone_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Windows PowerShell:
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
mysqldump -u drone_user -p --single-transaction --quick smart_emergency_drone_db > "backup_$timestamp.sql"
```

### 6.2 Restoring the MySQL Database
To restore from a logical backup file:

```bash
mysql -u drone_user -p smart_emergency_drone_db < backup_file.sql
```

### 6.3 Backing Up Docker Persistent Volumes
To create an archive of the persistent MySQL Docker volume without stopping containers:

```bash
docker run --rm -v emergency_drone_mysql_data:/volume -v $(pwd):/backup alpine tar -czf /backup/mysql_data_backup.tar.gz -C /volume ./
```

### 6.4 Backing Up SQLite Instance Database
For standalone demonstrations utilizing local SQLite:

```powershell
Copy-Item instance/drone_system.db instance/drone_system_backup.db
```

---

## 7. Known Operational Boundaries & Limitations

1. **Simulation Model Disclaimer:** The system computes trajectory waypoints, aerodynamic power draw, and speed using discrete mathematical physics equations. It does **not** interface with real-world autopilot microcontrollers (e.g., PX4/ArduPilot via MAVLink) or broadcast physical ADS-B transponder signals.
2. **Atmospheric Modeling:** Meteorological wind is calculated as a corridor-level headwind vector; it does not model turbulent 3D microclimate urban canyon vortices.
3. **Battery Model:** Energy consumption uses aerodynamic power models with a linear state-of-charge estimator rather than an electrochemical Peukert battery degradation curve.
4. **Mandatory Safety Reserve:** The system strictly rejects any flight plan that discharges battery below **15% remaining capacity** at destination.

---

## 8. Rollback Considerations

If an update fails or schema changes encounter issues:

### 8.1 Database Schema Rollback
To revert the last applied migration:
```bash
flask db downgrade
```

### 8.2 Application Code Rollback
To revert the application to the last known stable git tag or commit:
```bash
git checkout <stable-commit-hash>
```

### 8.3 Container Rollback
To rebuild and restart the previous container image:
```bash
docker compose down
docker compose up --build -d
```
All persistent MySQL delivery records and drone inventories remain preserved in the named Docker volume `emergency_drone_mysql_data`.
