import time
from functools import wraps
from flask import session, redirect, url_for, request, abort, flash, g, has_request_context
from app.extensions import db
from app.models.user import User, UserRole

# In-memory failure tracker for rate-limiting brute-force login attempts
# Format: {identifier: {"count": int, "locked_until": float, "last_attempt": float}}
_LOGIN_FAILURES = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300  # 5 minutes
ATTEMPT_WINDOW_SECONDS = 600   # 10 minutes


class AuthService:
    """Authentication, session lifecycle, and rate-limiting security service."""

    @staticmethod
    def get_client_ip() -> str:
        """Extract the client IP address considering proxy headers."""
        if has_request_context():
            if request.headers.get("X-Forwarded-For"):
                return request.headers.get("X-Forwarded-For").split(",")[0].strip()
            return request.remote_addr or "127.0.0.1"
        return "127.0.0.1"

    @classmethod
    def is_rate_limited(cls, email: str) -> tuple[bool, int]:
        """Check if the account or IP is temporarily locked out due to failed attempts.

        Returns:
            tuple: (is_locked: bool, remaining_seconds: int)
        """
        now = time.time()
        identifier = f"{cls.get_client_ip()}:{email.strip().lower()}"
        record = _LOGIN_FAILURES.get(identifier)

        if not record:
            return False, 0

        # Check active lockout
        if record.get("locked_until", 0) > now:
            remaining = int(record["locked_until"] - now)
            return True, remaining

        # Reset count if window expired
        if now - record.get("last_attempt", 0) > ATTEMPT_WINDOW_SECONDS:
            _LOGIN_FAILURES.pop(identifier, None)
            return False, 0

        return False, 0

    @classmethod
    def record_login_failure(cls, email: str) -> None:
        """Record a failed login attempt and trigger temporary lockout if threshold reached."""
        now = time.time()
        identifier = f"{cls.get_client_ip()}:{email.strip().lower()}"
        record = _LOGIN_FAILURES.setdefault(identifier, {"count": 0, "locked_until": 0, "last_attempt": now})

        record["count"] += 1
        record["last_attempt"] = now

        if record["count"] >= MAX_LOGIN_ATTEMPTS:
            record["locked_until"] = now + LOCKOUT_DURATION_SECONDS

    @classmethod
    def clear_login_failures(cls, email: str) -> None:
        """Clear failed login records upon successful authentication."""
        identifier = f"{cls.get_client_ip()}:{email.strip().lower()}"
        _LOGIN_FAILURES.pop(identifier, None)

    @classmethod
    def login_user(cls, user: User, remember: bool = False) -> None:
        """Establish a secure user session with session regeneration."""
        session.clear()  # Prevent session fixation
        session.permanent = bool(remember)
        session["user_id"] = user.id
        session["user_name"] = user.full_name
        session["user_email"] = user.email
        session["user_role"] = user.role
        g.current_user = user
        cls.clear_login_failures(user.email)

    @staticmethod
    def logout_user() -> None:
        """Terminate the active session completely."""
        session.clear()
        g.current_user = None

    @staticmethod
    def get_current_user() -> User | None:
        """Retrieve the active user from session or database context."""
        if hasattr(g, "current_user") and g.current_user:
            return g.current_user

        user_id = session.get("user_id")
        if not user_id:
            return None

        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            session.clear()
            return None

        g.current_user = user
        return user


def login_required(f):
    """Decorator requiring an authenticated session before accessing the endpoint."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = AuthService.get_current_user()
        if not current_user:
            if request.is_json:
                return {"error": "Authentication required", "status": 401}, 401
            flash("Please sign in to access this portal.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """Decorator restricting endpoint access to specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user = AuthService.get_current_user()
            if not current_user:
                if request.is_json:
                    return {"error": "Authentication required", "status": 401}, 401
                flash("Please sign in to access this resource.", "warning")
                return redirect(url_for("auth.login", next=request.path))

            allowed_values = [r.value if isinstance(r, UserRole) else str(r).upper() for r in allowed_roles]
            if current_user.role not in allowed_values:
                if request.is_json:
                    return {"error": "Forbidden: Insufficient privileges", "status": 403}, 403
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
