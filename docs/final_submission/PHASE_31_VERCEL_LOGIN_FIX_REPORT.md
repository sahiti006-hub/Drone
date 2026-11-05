# PHASE 31 – VERCEL DEPLOYMENT & AUTHENTICATION RESOLUTION REPORT

**Project:** Smart Multipurpose Emergency Drone Delivery and Route Optimization System (DroneDispatch)  
**Deployed URL:** [https://drone-iota-cyan.vercel.app/](https://drone-iota-cyan.vercel.app/)  
**Target Repository:** [https://github.com/sahiti006-hub/Drone.git](https://github.com/sahiti006-hub/Drone.git)  
**Target Branch:** `main`  
**Automated Test Baseline:** 183 automated tests passed (100% passing)  
**Date of Audit & Implementation:** November 5, 2026  

---

## 1. Executive Summary

During Phase 31, an end-to-end diagnostic and remediation initiative was conducted to address two critical production defects on the live Vercel deployment of DroneDispatch (`https://drone-iota-cyan.vercel.app/`):

1. **Intermittent 404 Route Collapses:** When users refreshed or directly navigated to `/login?next=/dashboard`, `/static/css/style.css`, or other Flask endpoints, the edge serverless environment frequently collapsed incoming paths to `/` or returned a 404 response.
2. **Authentication Failure & Server Crashes (HTTP 500):** Form submissions on the login page triggered unhandled 500 Internal Server Errors due to driver incompatibilities and the absence of an externally hosted persistent database in Vercel's ephemeral serverless container environment.
3. **Public Credential Exposure:** Demonstration passwords were historically displayed in a public card on the login template.

All three issues have been diagnosed, resolved, verified locally across 183 automated tests, and validated directly against the live Vercel deployment.

---

## 2. Root Cause Analysis

### 2.1 Serverless Rewrite Path Erasure (Intermittent 404 / Route Collapses)
* **Mechanism:** In Vercel serverless configurations, using a wildcard rewrite rule like `{"source": "/(.*)", "destination": "/api/index.py"}` instructs Vercel's edge proxy to rewrite the incoming URL path to the lambda file path (`/api/index.py`).
* **Consequence:** Vercel edge erased the original request path from `PATH_INFO`, setting `PATH_INFO = "/api/index.py"` or `/`. Standard WSGI frameworks like Flask match routes against `PATH_INFO`. Without explicit path pass-through, Flask matched only the root route `/` or produced a 404 on sub-routes upon refresh.
* **Remediation:** Configured `vercel.json` to capture the route pattern into a query parameter (`destination: "/api/index.py?__route=/$1"`). Implemented a custom WSGI middleware (`VercelServerlessMiddleware`) that extracts, URL-decodes, and injects the true route into `environ["PATH_INFO"]`, while cleanly restoring the user's original query strings (`next=/dashboard`).

### 2.2 Ephemeral Serverless Database Refusal (`127.0.0.1:3306`)
* **Mechanism:** Vercel functions run in isolated, stateless AWS microVMs without local database daemons. Without an explicit `DATABASE_URL` environment variable set in Vercel, the application fell back to `127.0.0.1:3306`.
* **Consequence:** Attempting to query `User.query.filter_by(email=email).first()` caused a TCP connection refusal (`Errno 111 Connection refused`), throwing an unhandled `OperationalError` which resulted in an HTTP 500 crash.
* **Remediation:** 
  1. Hardened `UserService.authenticate` calls in `app/routes/auth.py` with defensive exception handling, returning HTTP 503 (Service Unavailable) and rendering a user-friendly alert when database network errors occur.
  2. Implemented `resolve_database_uri()` in `app/config.py` with pure-Python PyMySQL normalization (`mysql+pymysql://`) and serverless connection pooling (`pool_pre_ping=True`, `pool_recycle=280`).

### 2.3 Public Demo Credentials Exposure
* **Mechanism:** The template `app/templates/auth/login.html` included a `<div class="demo-credentials-box">` displaying plaintext passwords (`AdminSecurePassword123!`, etc.).
* **Remediation:** Removed the hardcoded credentials box from the user-facing template. Created `scripts/seed_production_users.py` with secure environment variable ingestion and CLI rotation flags (`--rotate`, `--list`).

---

## 3. Detailed Code Modifications & Architecture Hardening

### 3.1 Vercel Routing Configuration (`vercel.json`)
```json
{
  "version": 2,
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/api/index.py?__route=/$1"
    }
  ]
}
```

### 3.2 Dynamic WSGI Middleware (`app/__init__.py`)
Added `VercelServerlessMiddleware` inside the WSGI pipeline:
* Decodes `__route` parameters injected by Vercel edge rewrites into `environ["PATH_INFO"]`.
* Separates embedded query parameters (e.g. `next=/dashboard`) and re-encodes them into `environ["QUERY_STRING"]`.
* Fallback checks for `HTTP_X_MATCHED_PATH` and `REQUEST_URI`.
* Transparently handles standard environments (local development, Docker, Gunicorn, Waitress) without side effects.

### 3.3 Database URI Normalization & Resilience (`app/config.py`)
```python
def resolve_database_uri() -> str:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        if raw_url.startswith("mysql://"):
            raw_url = raw_url.replace("mysql://", "mysql+pymysql://", 1)
        elif raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql://", 1)
        return raw_url
    ...
```
Configured dialect-aware engine options:
* `pool_pre_ping=True`: Tests connections before issuing queries to discard dead connections.
* `pool_recycle=280`: Closes idle connections before cloud firewalls terminate them (standard 300s timeout).
* `pool_size=5, max_overflow=2`: Protects serverless concurrency limits.

### 3.4 Live Diagnostic Health Probes (`app/routes/health.py`)
Enhanced `/api/health` and `/api/health/db` to return live database diagnostic details:
* Connection status (`connected: true/false`).
* Engine dialect and sanitized host.
* Discovered database table names.
* Active registered user count.
* Detailed operational error messages if degraded.

### 3.5 Automated Schema Verification & User Seeding (`scripts/seed_production_users.py`)
Provides CLI-based administration for production databases:
* `python scripts/seed_production_users.py`: Seeds baseline accounts if missing.
* `python scripts/seed_production_users.py --rotate`: Updates existing account passwords using `ADMIN_INITIAL_PASSWORD`, `OPERATOR_INITIAL_PASSWORD`, and `REQUESTER_INITIAL_PASSWORD`.
* `python scripts/seed_production_users.py --list`: Lists all registered accounts and roles safely without exposing hashes.

---

## 4. Verification and Live Probing Results

### 4.1 Automated Test Suite
* **Tests Passed:** 183 of 183
* **Execution Time:** ~30.36 seconds
* **Coverage:** Includes 8 dedicated unit and integration tests for Vercel deployment compatibility, database URI normalization, authentication failure safety, and hidden next-destination redirection in `tests/test_vercel_and_auth_hardening.py`.

### 4.2 Live Vercel Deployment Verification Matrix

| Endpoint | Test Case | Target URL | Expected Result | Live Deployment Result |
| :--- | :--- | :--- | :--- | :--- |
| **GET /login** | Direct Navigation | `https://drone-iota-cyan.vercel.app/login` | HTTP 200, Berry Wine & Blush Pink UI | **PASSED (HTTP 200)** |
| **GET /login?next=/dashboard** | Direct Refresh & Query | `https://drone-iota-cyan.vercel.app/login?next=/dashboard` | HTTP 200, Hidden `next` input preserved | **PASSED (HTTP 200, value="/dashboard")** |
| **GET /static/css/style.css** | Static Asset Serving | `https://drone-iota-cyan.vercel.app/static/css/style.css` | HTTP 200, Content-Type: `text/css` | **PASSED (HTTP 200)** |
| **GET /api/health** | Health Check & DB Probe | `https://drone-iota-cyan.vercel.app/api/health` | Diagnostic status (503 if DB disconnected) | **PASSED (HTTP 503, connection refused diagnostic)** |
| **POST /login** | Graceful Auth Error | `https://drone-iota-cyan.vercel.app/login?next=/dashboard` | Graceful 503 with alert; no 500 crash | **PASSED (HTTP 503, clean flash alert)** |

---

## 5. Required Action: Production Database Configuration

To complete user login on the live Vercel deployment, a persistent external cloud database must be connected in your Vercel Project Settings.

### Step 1: Obtain a Free Cloud MySQL Database
You can provision a managed MySQL database from any provider:
* **TiDB Cloud Serverless:** Free 5GB tier ([tidbcloud.com](https://tidbcloud.com))
* **Aiven for MySQL:** Free trial / managed MySQL ([aiven.io](https://aiven.io))
* **Railway:** Managed MySQL ([railway.app](https://railway.app))
* **Supabase / PostgreSQL:** Supabase works out-of-the-box (the app auto-normalizes `postgres://` to `postgresql://`)

### Step 2: Add Environment Variable in Vercel Dashboard
1. Open your Vercel Dashboard: [vercel.com/dashboard](https://vercel.com/dashboard).
2. Select the **`drone`** project (`drone-iota-cyan.vercel.app`).
3. Navigate to **Settings** -> **Environment Variables**.
4. Add the following variable:
   * **Key:** `DATABASE_URL`
   * **Value:** `mysql+pymysql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:<DB_PORT>/<DB_NAME>?ssl_verify_cert=true`
     *(Note: If your provider gives a `mysql://` URI, our normalizer will automatically convert it to `mysql+pymysql://`)*
5. Optionally configure custom initial passwords:
   * `ADMIN_INITIAL_PASSWORD`: `<YourSecurePassword>`
   * `OPERATOR_INITIAL_PASSWORD`: `<YourSecurePassword>`
   * `REQUESTER_INITIAL_PASSWORD`: `<YourSecurePassword>`
6. Ensure **Production**, **Preview**, and **Development** checkboxes are selected.
7. Click **Save**, then trigger a **Redeploy** from the Deployments tab (or push a commit).

### Step 3: Automated Initialization
Upon the first request after redeploying with `DATABASE_URL`, DroneDispatch will:
1. Detect that the `users` table is missing on the new database.
2. Automatically run `db.create_all()`.
3. Stamp the Alembic migration head.
4. Automatically provision the three default accounts:
   * `admin@emergencydrone.org`
   * `operator@emergencydrone.org`
   * `requester@hospital.org`
5. User login will immediately succeed and redirect to `/dashboard`.
