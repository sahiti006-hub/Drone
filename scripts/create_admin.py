"""Safe Administrator Account Creation Utility.

Allows administrators to initialize their master credentials securely
via interactive prompt or environment variables, without committing
passwords to source code or git repositories.

Usage:
  # Interactive mode:
  python scripts/create_admin.py

  # Automated/Environment-driven mode:
  $env:ADMIN_NAME="Chief Administrator"
  $env:ADMIN_EMAIL="admin@emergencydrone.org"
  $env:ADMIN_PASSWORD="SecurePassword123!"
  python scripts/create_admin.py
"""

import os
import sys
import getpass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from app import create_app
from app.extensions import db
from app.models.user import User, UserRole


def create_administrator():
    """Create or update the system administrator account safely."""
    app = create_app()

    with app.app_context():
        print("=" * 65)
        print("  EMERGENCY DRONE DISPATCH - SECURE ADMINISTRATOR INITIALIZATION")
        print("=" * 65)

        # Check environment variables first (useful in automated deployments)
        env_name = os.getenv("ADMIN_NAME")
        env_email = os.getenv("ADMIN_EMAIL")
        env_password = os.getenv("ADMIN_PASSWORD")

        if env_email and env_password:
            name = env_name or "System Administrator"
            email = env_email.strip().lower()
            password = env_password
            print(f"[*] Reading administrator credentials from environment: {email}")
        else:
            # Interactive prompt
            try:
                name = input("Enter Administrator Full Name [System Admin]: ").strip() or "System Admin"
                email = input("Enter Administrator Email: ").strip().lower()
                if not email or "@" not in email:
                    print("[X] Error: Valid email address is required.")
                    return False

                password = getpass.getpass("Enter Secure Password (min 8 chars): ")
                confirm = getpass.getpass("Confirm Secure Password: ")

                if password != confirm:
                    print("[X] Error: Passwords do not match.")
                    return False

            except (KeyboardInterrupt, EOFError):
                print("\n[!] Setup aborted.")
                return False

        if len(password) < 8:
            print("[X] Error: Administrator password must be at least 8 characters long.")
            return False

        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            reset_requested = "--reset-password" in sys.argv
            if not reset_requested:
                print(f"[!] User '{email}' already exists.")
                print("    Preserving existing credentials (administrator password will not be silently reset).")
                print("    To force a password update, rerun with: python scripts/create_admin.py --reset-password")
                # Ensure account has administrator role and is active
                if existing_user.role != UserRole.ADMIN.value or not existing_user.is_active:
                    existing_user.role = UserRole.ADMIN.value
                    existing_user.is_active = True
                    db.session.commit()
                    print(f"[+] User '{email}' role confirmed as ADMIN.")
                return True

            print(f"[*] Resetting password for existing user '{email}' as requested via --reset-password...")
            existing_user.full_name = name
            existing_user.role = UserRole.ADMIN.value
            existing_user.is_active = True
            existing_user.set_password(password)
            db.session.commit()
            print(f"[+] User '{email}' password successfully updated.")
            return True

        admin_user = User(
            full_name=name,
            email=email,
            password=password,
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.session.add(admin_user)
        db.session.commit()
        print(f"[+] Administrator account '{email}' created successfully with ID #{admin_user.id}!")
        return True


if __name__ == "__main__":
    success = create_administrator()
    sys.exit(0 if success else 1)
