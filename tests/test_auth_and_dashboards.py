from app.extensions import db
from app.models.user import User, UserRole
from app.models.delivery_request import DeliveryRequest, RequestPriority, EmergencyType
from app.services.auth_service import AuthService


def test_login_page_renders(client):
    """Ensure the login page renders with HTTP 200 and required input fields."""
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Emergency Drone Dispatch" in response.data
    assert b"name=\"email\"" in response.data
    assert b"name=\"password\"" in response.data


def test_successful_login_and_logout(client):
    """Test full login lifecycle, session population, and logout."""
    user = User("Admin Specialist", "test_admin@dispatch.org", "AdminPass123!", UserRole.ADMIN)
    db.session.add(user)
    db.session.commit()

    # Submit login form
    response = client.post(
        "/login",
        data={"email": "test_admin@dispatch.org", "password": "AdminPass123!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Following /dashboard redirected admin to /admin/dashboard
    assert b"Fleet &amp; System Administration" in response.data or b"Fleet & System Administration" in response.data

    with client.session_transaction() as sess:
        assert sess.get("user_id") == user.id
        assert sess.get("user_role") == "ADMIN"

    # Logout
    logout_resp = client.post("/logout", follow_redirects=True)
    assert logout_resp.status_code == 200
    assert b"You have been signed out safely" in logout_resp.data

    with client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_invalid_login_credentials(client):
    """Test rejection and error reporting on incorrect password."""
    user = User("Operator Jane", "jane@dispatch.org", "CorrectPass123!", UserRole.OPERATOR)
    db.session.add(user)
    db.session.commit()

    response = client.post(
        "/login",
        data={"email": "jane@dispatch.org", "password": "IncorrectPassword"},
    )
    assert response.status_code == 401
    assert b"Invalid email or password" in response.data

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_rate_limiting(client):
    """Ensure account lockout occurs after repeated failed attempts."""
    email = "ratelimit_target@test.org"
    AuthService.clear_login_failures(email)

    for _ in range(5):
        client.post("/login", data={"email": email, "password": "WrongPassword"})

    # 6th attempt should return 429 Too Many Requests
    resp = client.post("/login", data={"email": email, "password": "WrongPassword"})
    assert resp.status_code == 429
    assert b"Too many failed login attempts" in resp.data

    # Cleanup
    AuthService.clear_login_failures(email)


def test_unauthorized_endpoints_redirect_to_login(client):
    """Ensure unauthenticated access to protected portals is redirected to /login."""
    routes = ["/dashboard", "/admin/dashboard", "/operator/dashboard", "/requester/dashboard"]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


def test_role_based_permissions_enforcement(client):
    """Verify that requesters cannot access admin/operator dashboards (403 Forbidden)."""
    requester = User("Dr. Requester", "req_user@hospital.org", "Pass12345!", UserRole.REQUESTER)
    db.session.add(requester)
    db.session.commit()

    # Log in as Requester
    client.post("/login", data={"email": "req_user@hospital.org", "password": "Pass12345!"})

    # Allowed: Requester dashboard
    req_resp = client.get("/requester/dashboard")
    assert req_resp.status_code == 200

    # Forbidden: Admin dashboard
    admin_resp = client.get("/admin/dashboard")
    assert admin_resp.status_code == 403

    # Forbidden: Operator dashboard
    op_resp = client.get("/operator/dashboard")
    assert op_resp.status_code == 403


def test_idor_protection_for_delivery_requests(client):
    """Ensure users cannot access another user's delivery request by manipulating the URL ID."""
    user1 = User("Doctor One", "doc1@hospital.org", "Pass12345!", UserRole.REQUESTER)
    user2 = User("Doctor Two", "doc2@hospital.org", "Pass12345!", UserRole.REQUESTER)
    db.session.add_all([user1, user2])
    db.session.commit()

    req1 = DeliveryRequest(
        requester_id=user1.id,
        emergency_type=EmergencyType.BLOOD_SUPPLY,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=2.0,
    )
    req2 = DeliveryRequest(
        requester_id=user2.id,
        emergency_type=EmergencyType.ANTIVENOM,
        pickup_latitude=12.9716,
        pickup_longitude=77.5946,
        destination_latitude=12.9352,
        destination_longitude=77.6245,
        payload_weight_kg=1.5,
    )
    db.session.add_all([req1, req2])
    db.session.commit()

    # Log in as User 1
    client.post("/login", data={"email": "doc1@hospital.org", "password": "Pass12345!"})

    # User 1 accesses their own request -> 200 OK
    own_resp = client.get(f"/requests/{req1.id}")
    assert own_resp.status_code == 200
    assert b"Emergency Cargo Specification" in own_resp.data

    # User 1 attempts to access User 2's request -> 403 Forbidden!
    foreign_resp = client.get(f"/requests/{req2.id}")
    assert foreign_resp.status_code == 403
    assert b"403 - Access Denied" in foreign_resp.data


def test_requester_order_submission(client):
    """Verify that authenticated requesters can submit new emergency dispatch orders."""
    user = User("Emergency Clinic", "clinic@dispatch.org", "ClinicPass123!", UserRole.REQUESTER)
    db.session.add(user)
    db.session.commit()

    # Log in
    client.post("/login", data={"email": "clinic@dispatch.org", "password": "ClinicPass123!"})

    # Submit emergency delivery request
    post_data = {
        "emergency_type": EmergencyType.DEFIBRILLATOR.value,
        "priority": RequestPriority.CRITICAL.value,
        "payload_weight_kg": 3.2,
        "pickup_latitude": 12.9716,
        "pickup_longitude": 77.5946,
        "destination_latitude": 12.9352,
        "destination_longitude": 77.6245,
    }
    resp = client.post("/requester/requests", data=post_data, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Emergency Delivery Request #" in resp.data

    # Confirm in database
    created = DeliveryRequest.query.filter_by(requester_id=user.id).first()
    assert created is not None
    assert created.emergency_type == EmergencyType.DEFIBRILLATOR.value
    assert float(created.payload_weight_kg) == 3.2
    assert created.priority == "CRITICAL"
