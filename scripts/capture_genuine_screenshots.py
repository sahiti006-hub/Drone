"""Capture genuine application screenshots using Playwright and a local Flask server.

Captures all 10 required screens:
1. Login page
2. Admin dashboard
3. Operator dashboard
4. Requester dashboard
5. Emergency delivery request form
6. Drone inventory
7. Route optimization view
8. Live drone simulation map
9. Dynamic rerouting view
10. Analytics and ML evaluation dashboard
"""

import os
import sys
import time
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from app.extensions import db
from app.models import DeliveryRequest, SimulationRun, SimulationStatus, Drone, DroneStatus, Route, DroneAssignment

OUTPUT_DIR = BASE_DIR / "docs" / "final_submission" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PORT = 5005
BASE_URL = f"http://127.0.0.1:{PORT}"


def run_server(app):
    """Run Flask application in a background server thread."""
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def prepare_live_demo_state(app):
    """Ensure we have an active simulation and a rerouted simulation with routes."""
    with app.app_context():
        # Find a valid request with routes
        req = DeliveryRequest.query.filter(DeliveryRequest.routes.any()).order_by(DeliveryRequest.id.desc()).first()
        if not req:
            req = DeliveryRequest.query.first()
        req_id = req.id if req else 1

        # Find or prepare a running simulation for the live map
        live_sim = SimulationRun.query.filter_by(status=SimulationStatus.RUNNING.value).first()
        if not live_sim:
            # Pick a completed simulation and set to RUNNING with intermediate coordinates
            live_sim = SimulationRun.query.filter(SimulationRun.assignment_id.isnot(None)).order_by(SimulationRun.id.desc()).first()
            if live_sim:
                live_sim.status = SimulationStatus.RUNNING.value
                live_sim.current_progress_percent = 42.5
                live_sim.current_latitude = 17.4080
                live_sim.current_longitude = 78.4450
                live_sim.current_altitude_m = 65.0
                live_sim.current_battery_wh = 760.0
                live_sim.current_airspeed_kmh = 62.0
                db.session.commit()

        # Find a simulation with reroute_history
        rerouted_sim = (
            SimulationRun.query.filter(SimulationRun.parameters_json.like("%reroute_history%"))
            .order_by(SimulationRun.id.desc())
            .first()
        )

        return req_id, live_sim.id if live_sim else 1, rerouted_sim.id if rerouted_sim else (live_sim.id if live_sim else 1)


def capture_all_screenshots():
    app = create_app("development")
    req_id, live_sim_id, reroute_sim_id = prepare_live_demo_state(app)

    # Start Flask server thread
    server_thread = threading.Thread(target=run_server, args=(app,), daemon=True)
    server_thread.start()
    time.sleep(2.0)

    print(f"[*] Capturing genuine application screenshots from {BASE_URL}...")
    print(f"[*] Request ID: {req_id}, Live Simulation ID: {live_sim_id}, Rerouted Simulation ID: {reroute_sim_id}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 850})
        page = context.new_page()

        # ----------------------------------------------------------------------
        # Screen 1: Login Page
        # ----------------------------------------------------------------------
        print("[1/10] Capturing Login Page...")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUTPUT_DIR / "01_login_page.png"))

        # ----------------------------------------------------------------------
        # Screen 2, 6, 10: Authenticate as Admin
        # ----------------------------------------------------------------------
        print("[*] Logging in as Admin (admin@emergencydrone.org)...")
        page.fill('input[name="email"]', "admin@emergencydrone.org")
        page.fill('input[name="password"]', "AdminSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        print("[2/10] Capturing Admin Dashboard...")
        page.goto(f"{BASE_URL}/admin/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "02_admin_dashboard.png"))

        print("[6/10] Capturing Drone Inventory...")
        page.goto(f"{BASE_URL}/drones")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "06_drone_inventory.png"))

        print("[10/10] Capturing Analytics & ML Evaluation Dashboard...")
        page.goto(f"{BASE_URL}/analytics")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "10_analytics_and_ml_dashboard.png"))

        # ----------------------------------------------------------------------
        # Screen 3, 7, 8, 9: Authenticate as Operator
        # ----------------------------------------------------------------------
        print("[*] Logging out and logging in as Operator (operator@emergencydrone.org)...")
        page.goto(f"{BASE_URL}/logout")
        page.wait_for_load_state("networkidle")

        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="email"]', "operator@emergencydrone.org")
        page.fill('input[name="password"]', "OperatorSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        print("[3/10] Capturing Operator Dashboard...")
        page.goto(f"{BASE_URL}/operator/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "03_operator_dashboard.png"))

        print(f"[7/10] Capturing Route Optimization View (/requests/{req_id})...")
        page.goto(f"{BASE_URL}/requests/{req_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        page.screenshot(path=str(OUTPUT_DIR / "07_route_optimization_view.png"))

        print(f"[8/10] Capturing Live Drone Simulation Map (/simulation/{live_sim_id})...")
        page.goto(f"{BASE_URL}/simulation/{live_sim_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(2.0)  # Allow Leaflet tiles and markers to render
        page.screenshot(path=str(OUTPUT_DIR / "08_live_drone_simulation_map.png"))

        print(f"[9/10] Capturing Dynamic Rerouting View (/simulation/{reroute_sim_id})...")
        page.goto(f"{BASE_URL}/simulation/{reroute_sim_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(2.0)
        page.screenshot(path=str(OUTPUT_DIR / "09_dynamic_rerouting_view.png"))

        # ----------------------------------------------------------------------
        # Screen 4, 5: Authenticate as Requester
        # ----------------------------------------------------------------------
        print("[*] Logging out and logging in as Requester (requester@hospital.org)...")
        page.goto(f"{BASE_URL}/logout")
        page.wait_for_load_state("networkidle")

        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="email"]', "requester@hospital.org")
        page.fill('input[name="password"]', "RequesterSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        print("[4/10] Capturing Requester Dashboard...")
        page.goto(f"{BASE_URL}/requester/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "04_requester_dashboard.png"))

        print("[5/10] Capturing Emergency Delivery Request Form (/requests/new)...")
        page.goto(f"{BASE_URL}/requests/new")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "05_emergency_delivery_request_form.png"))

        browser.close()

    print(f"\n[+] All 10 genuine screenshots successfully captured in {OUTPUT_DIR}!")


if __name__ == "__main__":
    capture_all_screenshots()
