from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.services.auth_service import AuthService
from app.services.user_service import UserService

auth_bp = Blueprint("auth", __name__)


def is_safe_redirect_url(target: str) -> bool:
    """Ensure the target redirection URL is local to prevent open-redirect vulnerabilities."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return test_url.scheme in ("", "http", "https") and ref_url.netloc == (test_url.netloc or ref_url.netloc) and not target.startswith("//")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user authentication and session establishment."""
    # If already logged in, redirect straight to dashboard
    current_user = AuthService.get_current_user()
    if current_user:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))
        next_url = request.args.get("next") or request.form.get("next")

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template("auth/login.html", email=email), 400

        # Check rate-limiting
        is_locked, remaining_seconds = AuthService.is_rate_limited(email)
        if is_locked:
            flash(
                f"Too many failed login attempts. Account temporarily locked. Please retry in {remaining_seconds} seconds.",
                "danger",
            )
            return render_template("auth/login.html", email=email), 429

        # Verify credentials
        user = UserService.authenticate(email, password)
        if not user:
            AuthService.record_login_failure(email)
            flash("Invalid email or password. Please verify your credentials.", "danger")
            return render_template("auth/login.html", email=email), 401

        if not user.is_active:
            flash("Your account has been deactivated. Contact the system administrator.", "danger")
            return render_template("auth/login.html", email=email), 403

        # Login and establish session
        AuthService.login_user(user, remember=remember)
        flash(f"Welcome back, {user.full_name}.", "success")

        if next_url and is_safe_redirect_url(next_url):
            return redirect(next_url)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Terminate the authenticated user session."""
    AuthService.logout_user()
    flash("You have been signed out safely.", "info")
    return redirect(url_for("auth.login"))
