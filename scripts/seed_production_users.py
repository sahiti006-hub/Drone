"""Production Demonstration User Provisioning and Credential Management Utility.

Safely provisions or rotates demonstration user accounts without displaying
passwords on publicly accessible web pages or falling back to default passwords.
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from app import create_app
from app.extensions import db
from app.models.user import User, UserRole


DEFAULT_ACCOUNTS = [
    {
        "full_name": "Dr. Elena Rostova (Admin)",
        "email": "admin@emergencydrone.org",
        "env_var": "ADMIN_INITIAL_PASSWORD",
        "role": UserRole.ADMIN.value,
    },
    {
        "full_name": "Marcus Vance (Fleet Operator)",
        "email": "operator@emergencydrone.org",
        "env_var": "OPERATOR_INITIAL_PASSWORD",
        "role": UserRole.OPERATOR.value,
    },
    {
        "full_name": "Dr. Sarah Lin (City Hospital Requester)",
        "email": "requester@hospital.org",
        "env_var": "REQUESTER_INITIAL_PASSWORD",
        "role": UserRole.REQUESTER.value,
    },
]


def validate_password_strength(password: str, env_var: str) -> None:
    """Validate that environment-provided password satisfies strict production requirements."""
    if not password or not password.strip():
        raise ValueError(
            f"Mandatory environment variable '{env_var}' is missing or empty. "
            f"An explicit strong password must be provided."
        )

    pwd = password.strip()
    if len(pwd) < 12:
        raise ValueError(
            f"Password in '{env_var}' is too weak (length {len(pwd)}). "
            f"Must be at least 12 characters for production."
        )

    insecure_examples = {
        "adminpassword", "operatorpassword", "requesterpassword",
        "password123", "password123!", "adminsecurepassword123!",
        "operatorsecurepassword123!", "requestersecurepassword123!"
    }
    if pwd.lower() in insecure_examples:
        raise ValueError(
            f"Password in '{env_var}' is a known insecure demo password. "
            f"Please specify a unique, strong password."
        )


def provision_users(rotate=False, app=None):
    """Ensure all required role accounts exist in the configured database without dropping or overwriting data."""
    if app is None:
        app = create_app()

    with app.app_context():
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        # Database schema must be created via migrations, never db.create_all() in production
        if "users" not in tables:
            print("[X] ERROR: Table 'users' does not exist in the database.")
            print("    Production requires migrations to be applied before user provisioning.")
            print("    Please run: flask db upgrade")
            sys.exit(1)

        print(f"[*] Verified database connection and schema. Inspecting accounts...")

        created_count = 0
        rotated_count = 0
        existing_count = 0

        for acc in DEFAULT_ACCOUNTS:
            email = acc["email"].strip().lower()
            env_var = acc["env_var"]
            user = User.query.filter_by(email=email).first()

            if not user:
                # Require explicit password for new provisioning
                password = os.getenv(env_var, "").strip()
                validate_password_strength(password, env_var)

                user = User(
                    full_name=acc["full_name"],
                    email=email,
                    password=password,
                    role=acc["role"],
                    is_active=True,
                )
                db.session.add(user)
                created_count += 1
                print(f"[+] Provisioned new account: {acc['full_name']} <{email}> [{acc['role']}]")

            elif rotate:
                # Rotate password only with explicit flag and validated new password
                password = os.getenv(env_var, "").strip()
                validate_password_strength(password, env_var)

                user.set_password(password)
                user.is_active = True
                rotated_count += 1
                print(f"[+] Rotated password for account: {acc['full_name']} <{email}> [{acc['role']}]")

            else:
                # Idempotent: preserve existing user without overwriting password
                existing_count += 1
                print(f"[-] Account already exists: {acc['full_name']} <{email}> [{acc['role']}] (preserved, password unchanged)")

        db.session.commit()
        print(f"[*] Provisioning summary: {created_count} created, {rotated_count} rotated, {existing_count} preserved.")


def list_users():
    """List all user accounts in the database safely."""
    app = create_app()
    with app.app_context():
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if "users" not in inspector.get_table_names():
            print("[X] ERROR: Table 'users' does not exist. Run 'flask db upgrade' first.")
            sys.exit(1)

        users = User.query.all()
        print(f"\nFound {len(users)} registered users in database:")
        for u in users:
            print(f"  - ID: {u.id:2d} | Role: {u.role:10s} | Active: {str(u.is_active):5s} | {u.full_name} <{u.email}>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DroneDispatch User Provisioning Utility")
    parser.add_argument("--rotate", action="store_true", help="Rotate passwords for existing accounts using environment variables")
    parser.add_argument("--list", action="store_true", help="List all registered user accounts")
    args = parser.parse_args()

    if args.list:
        list_users()
    else:
        provision_users(rotate=args.rotate)
