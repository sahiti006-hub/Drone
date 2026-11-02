import pytest
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User, UserRole
from app.services.user_service import UserService, UserServiceError


def test_user_password_hashing(app):
    """Test secure password hashing and verification."""
    user = User(
        full_name="Alice Medic",
        email="alice@emergency.org",
        password="ValidPassword123!",
        role=UserRole.REQUESTER,
    )
    assert user.password_hash != "ValidPassword123!"
    assert user.check_password("ValidPassword123!") is True
    assert user.check_password("WrongPassword") is False


def test_user_short_password_rejected(app):
    """Test that passwords shorter than minimum length are rejected."""
    with pytest.raises(ValueError, match="at least 6 characters"):
        User(
            full_name="Bob Short",
            email="bob@emergency.org",
            password="123",
            role=UserRole.REQUESTER,
        )


def test_user_role_based_permissions(app):
    """Test backend authorization based on roles."""
    admin = User("Admin User", "admin_perm@emergency.org", "Pass12345!", UserRole.ADMIN)
    operator = User("Operator User", "operator_perm@emergency.org", "Pass12345!", UserRole.OPERATOR)
    requester = User("Requester User", "requester_perm@emergency.org", "Pass12345!", UserRole.REQUESTER)

    # Admin permissions
    assert admin.has_permission("manage_users") is True
    assert admin.has_permission("dispatch_drone") is True
    assert admin.has_permission("system_configuration") is True

    # Operator permissions
    assert operator.has_permission("manage_users") is False  # Restricted to Admin
    assert operator.has_permission("dispatch_drone") is True
    assert operator.has_permission("view_all_requests") is True

    # Requester permissions
    assert requester.has_permission("dispatch_drone") is False
    assert requester.has_permission("create_request") is True
    assert requester.has_permission("view_own_requests") is True
    assert requester.has_permission("view_all_requests") is False


def test_inactive_user_denied_permissions(app):
    """Inactive users must have all permissions revoked."""
    user = User("Inactive User", "inactive@emergency.org", "Pass12345!", UserRole.ADMIN, is_active=False)
    assert user.has_permission("manage_users") is False


def test_user_email_uniqueness(app):
    """Ensure duplicate emails trigger an integrity violation."""
    u1 = User("First", "duplicate@test.org", "Pass12345!", UserRole.REQUESTER)
    u2 = User("Second", "duplicate@test.org", "Pass12345!", UserRole.REQUESTER)

    db.session.add(u1)
    db.session.commit()

    db.session.add(u2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_user_service_registration_and_authentication(app):
    """Test registration and authentication via UserService."""
    user = UserService.register_user(
        full_name="Dr. Taylor",
        email="taylor@hospital.org",
        password="HospitalPass123!",
        role=UserRole.REQUESTER.value,
    )
    assert user.id is not None

    # Authenticate successfully
    authenticated = UserService.authenticate("taylor@hospital.org", "HospitalPass123!")
    assert authenticated is not None
    assert authenticated.id == user.id

    # Authenticate with bad password
    assert UserService.authenticate("taylor@hospital.org", "WrongPass") is None

    # Duplicate registration raises UserServiceError
    with pytest.raises(UserServiceError):
        UserService.register_user(
            full_name="Duplicate Taylor",
            email="taylor@hospital.org",
            password="AnotherPass123!",
        )
