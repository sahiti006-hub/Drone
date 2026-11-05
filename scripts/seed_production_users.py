"""Production Demonstration User Provisioning and Credential Management Utility.

Safely provisions or rotates demonstration user accounts without displaying
passwords on publicly accessible web pages.
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
        "env_var": "ADMIN_PASSWORD",
        "default_pass": "AdminSecurePassword123!",
        "role": UserRole.ADMIN.value,
    },
    {
        "full_name": "Marcus Vance (Fleet Operator)",
        "email": "operator@emergencydrone.org",
        "env_var": "OPERATOR_PASSWORD",
        "default_pass": "OperatorSecurePassword123!",
        "role": UserRole.OPERATOR.value,
    },
    {
        "full_name": "Dr. Sarah Lin (City Hospital Requester)",
        "email": "requester@hospital.org",
        "env_var": "REQUESTER_PASSWORD",
        "default_pass": "RequesterSecurePassword123!",
        "role": UserRole.REQUESTER.value,
    },
]


def provision_users(rotate=False):
    """Ensure all required role accounts exist in the configured database."""
    app = create_app()

    with app.app_context():
        print(f"[*] Target Database URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
        db.create_all()

        for acc in DEFAULT_ACCOUNTS:
            email = acc["email"].strip().lower()
            password = os.getenv(acc["env_var"], acc["default_pass"])
            user = User.query.filter_by(email=email).first()

            if not user:
                user = User(
                    full_name=acc["full_name"],
                    email=email,
                    password=password,
                    role=acc["role"],
                    is_active=True,
                )
                db.session.add(user)
                db.session.commit()
                print(f"[+] Provisioned new user: {acc['full_name']} <{email}> [{acc['role']}]")
            elif rotate:
                user.set_password(password)
                user.is_active = True
                db.session.commit()
                print(f"[+] Rotated credentials for user: {acc['full_name']} <{email}> [{acc['role']}]")
            else:
                print(f"[-] User already exists: {acc['full_name']} <{email}> [{acc['role']}] (active={user.is_active})")

        print("[*] User account provisioning verification complete.")


def list_users():
    """List all user accounts in the database."""
    app = create_app()
    with app.app_context():
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
