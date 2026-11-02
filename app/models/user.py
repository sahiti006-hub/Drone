import enum
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class UserRole(str, enum.Enum):
    """Supported user roles in the emergency drone delivery system."""
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    REQUESTER = "REQUESTER"


# Backend role-based permissions matrix
ROLE_PERMISSIONS = {
    UserRole.ADMIN: {
        "manage_users",
        "manage_drones",
        "create_request",
        "view_all_requests",
        "dispatch_drone",
        "abort_mission",
        "run_simulation",
        "view_analytics",
        "system_configuration",
    },
    UserRole.OPERATOR: {
        "manage_drones",
        "view_all_requests",
        "dispatch_drone",
        "abort_mission",
        "run_simulation",
        "view_analytics",
    },
    UserRole.REQUESTER: {
        "create_request",
        "view_own_requests",
    },
}


class User(db.Model):
    """User account entity with role-based access control."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(20),
        nullable=False,
        default=UserRole.REQUESTER.value,
        index=True,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    delivery_requests = db.relationship(
        "DeliveryRequest",
        back_populates="requester",
        lazy="dynamic",
        passive_deletes=False,
    )

    def __init__(self, full_name, email, password, role=UserRole.REQUESTER.value, is_active=True):
        self.full_name = full_name.strip()
        self.email = email.strip().lower()
        self.set_password(password)
        self.role = role.value if isinstance(role, UserRole) else str(role).upper()
        self.is_active = is_active

    def set_password(self, password: str) -> None:
        """Hash and store the user's password securely."""
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against the stored cryptographic hash."""
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles) -> bool:
        """Check if user belongs to any of the specified roles."""
        role_values = [r.value if isinstance(r, UserRole) else str(r).upper() for r in roles]
        return self.role in role_values

    def has_permission(self, permission_name: str) -> bool:
        """Backend authorization: evaluate if the user's role grants permission."""
        if not self.is_active:
            return False
        try:
            user_role = UserRole(self.role)
        except ValueError:
            return False
        return permission_name in ROLE_PERMISSIONS.get(user_role, set())

    def to_dict(self) -> dict:
        """Serialize user model to dictionary (safely excluding password_hash)."""
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
