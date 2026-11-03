"""Database initialization script.

Ensures the database exists (handling MySQL server connections)
and creates all relational tables, constraints, and indexes.
"""

import os
import sys
from pathlib import Path
import pymysql
from dotenv import load_dotenv

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from app import create_app
from app.extensions import db


def create_mysql_database_if_needed():
    """Connect to MySQL server and ensure the target database exists."""
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = int(os.getenv("DB_PORT", "3306"))
    db_user = os.getenv("DB_USER", "drone_user")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "smart_emergency_drone_db")

    print(f"[*] Attempting connection to MySQL server at {db_host}:{db_port}...")
    try:
        connection = pymysql.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            charset="utf8mb4",
            connect_timeout=5,
        )
        with connection.cursor() as cursor:
            sql = f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            cursor.execute(sql)
            print(f"[+] MySQL Database `{db_name}` is verified/created successfully.")
        connection.close()
        return True
    except pymysql.MySQLError as err:
        print(f"[!] Warning: Could not connect to MySQL server at {db_host}:{db_port} - {err}")
        print("    If MySQL is not currently running, you can use SQLite for local development by adding:")
        print("    DATABASE_URL=sqlite:///instance/drone_system.db in your .env file.")
        return False


def init_database():
    """Initialize database tables using the configured SQLAlchemy engine."""
    app = create_app()

    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        print(f"[*] Target Database URI: {db_uri}")

        if db_uri.startswith("mysql"):
            mysql_ready = create_mysql_database_if_needed()
            if not mysql_ready:
                print("[!] Aborting MySQL table creation. Please ensure MySQL server is active.")
                return False
        elif db_uri.startswith("sqlite:///"):
            sqlite_file = db_uri.replace("sqlite:///", "")
            if sqlite_file and sqlite_file != ":memory:":
                sqlite_path = Path(sqlite_file)
                if not sqlite_path.is_absolute():
                    sqlite_path = BASE_DIR / sqlite_path
                sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            print("[*] Creating all database tables, foreign keys, and indexes...")
            db.create_all()
            print("[+] All tables created successfully:")
            for table_name in db.metadata.tables.keys():
                print(f"    - {table_name}")

            # Synchronize Alembic migration state so subsequent migrations remain aligned
            try:
                from flask_migrate import stamp
                stamp(revision="head")
                print("[+] Synchronized Alembic migration state to 'head' revision.")
            except Exception as stamp_err:
                print(f"[-] Note: Alembic migration stamp skipped ({stamp_err})")

            return True
        except Exception as exc:
            print(f"[X] Database initialization error: {exc}")
            return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
