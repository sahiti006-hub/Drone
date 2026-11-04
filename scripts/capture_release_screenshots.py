"""Capture the 14 academic release screenshots using Playwright Edge and local Flask test server.

Screenshots captured:
1. Login page (01_login_page.png)
2. Requester dashboard (02_requester_dashboard.png)
3. SEND booking view (03_send_booking.png)
4. RECEIVE booking view (04_receive_booking.png)
5. Universal cargo selection (05_universal_cargo_selection.png)
6. Custom item form (06_custom_item_form.png)
7. Drone availability search results (07_drone_availability.png)
8. Pricing confirmation (08_pricing_confirmation.png)
9. Live tracking cockpit (09_live_tracking.png)
10. Dynamic weather rerouting view (10_weather_rerouting.png)
11. Booking history with two-way filters (11_booking_history.png)
12. Admin dashboard (12_admin_dashboard.png)
13. Operator dashboard (13_operator_dashboard.png)
14. Itemized tax invoice (14_payment_invoice.png)
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
from app.models.user import User, UserRole
from app.models.drone import Drone, DroneStatus
from app.models.drone_booking import DroneBooking, BookingStatus
from app.models.delivery_request import DeliveryRequest, RequestStatus
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.services.drone_availability_service import DroneAvailabilityService
from app.services.payment_service import PaymentService
from app.services.weather_intelligence_service import WeatherIntelligenceService

OUTPUT_DIR = BASE_DIR / "docs" / "final_submission" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PORT = 5006
BASE_URL = f"http://127.0.0.1:{PORT}"


def run_server(app):
    """Run Flask application in a background server thread."""
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def prepare_demo_bookings(app):
    """Ensure realistic demo bookings exist for clean screenshot presentation."""
    with app.app_context():
        requester = User.query.filter_by(role=UserRole.REQUESTER.value).first()
        if not requester:
            requester = User(
                full_name="Dr. Sarah Jenkins (Apollo Emergency)",
                email="requester@hospital.org",
                password="RequesterSecurePassword123!",
                role=UserRole.REQUESTER.value,
            )
            db.session.add(requester)
            db.session.commit()

        # Ensure active drone exists
        drone = Drone.query.filter_by(status=DroneStatus.AVAILABLE.value).first()
        if not drone:
            drone = Drone(
                drone_code="AERO-DEMO-01",
                model_name="SkyLifter Heavy Duty",
                maximum_payload_kg=12.0,
                battery_capacity_wh=3200.0,
                current_battery_wh=3200.0,
                cruise_speed_kmh=65.0,
                status=DroneStatus.AVAILABLE.value,
            )
            db.session.add(drone)
            db.session.commit()

        # Clear weather override initially
        WeatherIntelligenceService.clear_demonstration_scenario()

        # Check existing bookings
        b_send = DroneBooking.query.filter_by(delivery_direction="SEND").first()
        if not b_send:
            search1 = DroneAvailabilityService.search_available_drones(
                requester_id=requester.id,
                pickup_lat=12.9634,
                pickup_lng=77.5756,
                dest_lat=12.9833,
                dest_lng=77.6044,
                cargo_weight_kg=2.0,
                cargo_category="BLOOD_UNITS",
                priority="HIGH",
                delivery_direction="SEND",
            )
            q1_id = search1["available_drones"][0]["quote_id"]
            b_send = DroneAvailabilityService.confirm_and_lock_booking(
                quote_id=q1_id,
                requester_id=requester.id,
                weather_acknowledged=True,
                notes="Urgent O-Negative blood units transit to Victoria Hospital.",
                delivery_direction="SEND",
            )
            # Pay and mark in-flight
            PaymentService.process_payment(booking_id=b_send.id, payment_method="SIMULATED_UPI")
            b_send.status = BookingStatus.IN_FLIGHT.value
            db.session.commit()

        # Check receive booking
        drone.status = DroneStatus.AVAILABLE.value
        db.session.commit()

        b_recv = DroneBooking.query.filter_by(delivery_direction="RECEIVE").first()
        if not b_recv:
            search2 = DroneAvailabilityService.search_available_drones(
                requester_id=requester.id,
                pickup_lat=12.9352,
                pickup_lng=77.6245,
                dest_lat=12.9716,
                dest_lng=77.5946,
                cargo_weight_kg=1.5,
                cargo_category="ANTIVENOM_SERUM",
                priority="CRITICAL",
                delivery_direction="RECEIVE",
            )
            q2_id = search2["available_drones"][0]["quote_id"]
            b_recv = DroneAvailabilityService.confirm_and_lock_booking(
                quote_id=q2_id,
                requester_id=requester.id,
                weather_acknowledged=True,
                notes="Collect polyvalent antivenom from Apollo Pharmacy hub.",
                delivery_direction="RECEIVE",
                collection_readiness="READY",
                collection_contact_name="Apollo Pharmacy Depot Central",
                collection_contact_phone="+91 98765 43210",
                collection_instructions="Collect from cold-chain dispatch locker B-4",
            )
            PaymentService.process_payment(booking_id=b_recv.id, payment_method="SIMULATED_CARD")
            b_recv.status = BookingStatus.DELIVERED.value
            db.session.commit()

        # Check rerouted booking
        drone.status = DroneStatus.AVAILABLE.value
        db.session.commit()

        b_reroute = DroneBooking.query.filter_by(status=BookingStatus.REROUTED.value).first()
        if not b_reroute:
            search3 = DroneAvailabilityService.search_available_drones(
                requester_id=requester.id,
                pickup_lat=12.9200,
                pickup_lng=77.6100,
                dest_lat=12.9800,
                dest_lng=77.6500,
                cargo_weight_kg=1.8,
                cargo_category="DEFIBRILLATOR",
                priority="CRITICAL",
                delivery_direction="SEND",
            )
            q3_id = search3["available_drones"][0]["quote_id"]
            b_reroute = DroneAvailabilityService.confirm_and_lock_booking(
                quote_id=q3_id,
                requester_id=requester.id,
                weather_acknowledged=True,
                delivery_direction="SEND",
            )
            PaymentService.process_payment(booking_id=b_reroute.id, payment_method="SIMULATED_UPI")
            b_reroute.status = BookingStatus.REROUTED.value
            db.session.commit()

        return b_send.id, b_recv.id, b_reroute.id


def capture_all_release_screenshots():
    app = create_app("development")
    send_id, recv_id, reroute_id = prepare_demo_bookings(app)

    # Start Flask server thread
    server_thread = threading.Thread(target=run_server, args=(app,), daemon=True)
    server_thread.start()
    time.sleep(2.5)

    print(f"[*] Capturing 14 Release Screenshots from {BASE_URL}...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 850})
        page = context.new_page()

        # ----------------------------------------------------------------------
        # Screen 1: Login Page
        # ----------------------------------------------------------------------
        print("[1/14] Capturing 01_login_page.png...", flush=True)
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "01_login_page.png"))

        # Log in as Requester
        print("[*] Logging in as Requester (requester@hospital.org)...", flush=True)
        page.fill('input[name="email"]', "requester@hospital.org")
        page.fill('input[name="password"]', "RequesterSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # ----------------------------------------------------------------------
        # Screen 2: Requester Dashboard
        # ----------------------------------------------------------------------
        print("[2/14] Capturing 02_requester_dashboard.png...", flush=True)
        page.goto(f"{BASE_URL}/requester/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "02_requester_dashboard.png"))

        # ----------------------------------------------------------------------
        # Screen 3: SEND Booking Mode
        # ----------------------------------------------------------------------
        print("[3/14] Capturing 03_send_booking.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/new?direction=SEND")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        page.screenshot(path=str(OUTPUT_DIR / "03_send_booking.png"))

        # ----------------------------------------------------------------------
        # Screen 4: RECEIVE Booking Mode
        # ----------------------------------------------------------------------
        print("[4/14] Capturing 04_receive_booking.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/new?direction=RECEIVE")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        page.screenshot(path=str(OUTPUT_DIR / "04_receive_booking.png"))

        # ----------------------------------------------------------------------
        # Screen 5: Universal Cargo Selection
        # ----------------------------------------------------------------------
        print("[5/14] Capturing 05_universal_cargo_selection.png...", flush=True)
        # Scroll to cargo grid
        page.evaluate("const g = document.querySelector('.cargo-categories-grid') || document.querySelector('.cargo-grid'); if (g) g.scrollIntoView({behavior: 'instant', block: 'center'});")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "05_universal_cargo_selection.png"))

        # ----------------------------------------------------------------------
        # Screen 6: Custom Item Form
        # ----------------------------------------------------------------------
        print("[6/14] Capturing 06_custom_item_form.png...", flush=True)
        page.evaluate("const c = document.querySelector('[data-category=\"CUSTOM_DELIVERY\"]') || document.querySelector('[data-category=\"CUSTOM_ITEM\"]'); if (c) c.click();")
        time.sleep(0.5)
        page.fill('#custom_item_name', "Titanium Surgical Fracture Plates")
        page.fill('#package_dimensions', "25x15x10 cm")
        page.evaluate("const p = document.getElementById('customItemPanel'); if (p) p.scrollIntoView({behavior: 'instant', block: 'center'});")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "06_custom_item_form.png"))

        # ----------------------------------------------------------------------
        # Screen 7: Drone Availability Search Results
        # ----------------------------------------------------------------------
        print("[7/14] Capturing 07_drone_availability.png...", flush=True)
        page.click('#btnFindDrones')
        time.sleep(2.5)  # Wait for AJAX search response and card animation
        page.evaluate("const el = document.getElementById('resultsSection') || document.getElementById('step5Section'); if (el) el.scrollIntoView({behavior: 'instant', block: 'start'});")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "07_drone_availability.png"))

        # ----------------------------------------------------------------------
        # Screen 8: Pricing Confirmation & Cockpit Review
        # ----------------------------------------------------------------------
        print("[8/14] Capturing 08_pricing_confirmation.png...", flush=True)
        # Click on first drone card to reveal booking summary and price breakdown
        page.evaluate("const firstCard = document.querySelector('.drone-card') || document.querySelector('.drone-option-card'); if (firstCard) firstCard.click();")
        time.sleep(1.0)
        page.evaluate("const sumCard = document.getElementById('bookingSummaryCard'); if (sumCard) sumCard.scrollIntoView({behavior: 'instant', block: 'center'});")
        time.sleep(0.5)
        page.screenshot(path=str(OUTPUT_DIR / "08_pricing_confirmation.png"))

        # ----------------------------------------------------------------------
        # Screen 9: Live Tracking Cockpit
        # ----------------------------------------------------------------------
        print("[9/14] Capturing 09_live_tracking.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/{send_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(2.0)  # Wait for Leaflet map tiles and drone icon
        page.screenshot(path=str(OUTPUT_DIR / "09_live_tracking.png"))

        # ----------------------------------------------------------------------
        # Screen 10: Weather Rerouting View
        # ----------------------------------------------------------------------
        print("[10/14] Capturing 10_weather_rerouting.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/{reroute_id}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        page.screenshot(path=str(OUTPUT_DIR / "10_weather_rerouting.png"))

        # ----------------------------------------------------------------------
        # Screen 11: Booking History with Two-Way Filters
        # ----------------------------------------------------------------------
        print("[11/14] Capturing 11_booking_history.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/history")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "11_booking_history.png"))

        # ----------------------------------------------------------------------
        # Screen 12: Admin Dashboard
        # ----------------------------------------------------------------------
        print("[12/14] Capturing 12_admin_dashboard.png...", flush=True)
        page.goto(f"{BASE_URL}/logout")
        page.wait_for_load_state("networkidle")
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="email"]', "admin@emergencydrone.org")
        page.fill('input[name="password"]', "AdminSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        page.goto(f"{BASE_URL}/admin/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "12_admin_dashboard.png"))

        # ----------------------------------------------------------------------
        # Screen 13: Operator Dashboard
        # ----------------------------------------------------------------------
        print("[13/14] Capturing 13_operator_dashboard.png...", flush=True)
        page.goto(f"{BASE_URL}/logout")
        page.wait_for_load_state("networkidle")
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="email"]', "operator@emergencydrone.org")
        page.fill('input[name="password"]', "OperatorSecurePassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        page.goto(f"{BASE_URL}/operator/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)
        page.screenshot(path=str(OUTPUT_DIR / "13_operator_dashboard.png"))

        # ----------------------------------------------------------------------
        # Screen 14: Payment Invoice
        # ----------------------------------------------------------------------
        print("[14/14] Capturing 14_payment_invoice.png...", flush=True)
        page.goto(f"{BASE_URL}/booking/{recv_id}/invoice")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        page.screenshot(path=str(OUTPUT_DIR / "14_payment_invoice.png"))

        browser.close()

    print(f"\n[+] All 14 release screenshots successfully captured and saved to {OUTPUT_DIR}!", flush=True)


if __name__ == "__main__":
    capture_all_release_screenshots()
