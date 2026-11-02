from app.extensions import db
from app.models.user import User, UserRole


class UserServiceError(Exception):
    """Base exception for user service operations."""
    pass


class UserService:
    """Service layer governing user authentication, registration, and backend authorization."""

    @staticmethod
    def register_user(full_name: str, email: str, password: str, role: str = UserRole.REQUESTER.value) -> User:
        """Register a new user with hashed password."""
        email_clean = email.strip().lower()
        if User.query.filter_by(email=email_clean).first():
            raise UserServiceError(f"A user with email '{email_clean}' already exists.")

        user = User(
            full_name=full_name,
            email=email_clean,
            password=password,
            role=role,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def authenticate(email: str, password: str) -> User | None:
        """Authenticate user by email and password."""
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user or not user.is_active:
            return None
        if not user.check_password(password):
            return None
        return user

    @staticmethod
    def authorize_permission(user_id: int, required_permission: str) -> bool:
        """Verify that the user is active and has the required backend permission."""
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return False
        return user.has_permission(required_permission)
