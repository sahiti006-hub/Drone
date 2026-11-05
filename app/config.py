import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if present
load_dotenv(BASE_DIR / ".env")


def resolve_database_uri() -> str:
    """Resolve and normalize the SQLAlchemy database URI across local, Docker, and Vercel environments."""
    raw_url = os.getenv("DATABASE_URL", "").strip()
    env = os.getenv("FLASK_ENV", "development").lower()

    if raw_url:
        # Standard cloud database providers (Aiven, TiDB, PlanetScale, Railway, Supabase) often provide mysql://
        # Normalize to mysql+pymysql:// for pure-python PyMySQL driver support in serverless environments
        if raw_url.startswith("mysql://"):
            raw_url = raw_url.replace("mysql://", "mysql+pymysql://", 1)
        elif raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql://", 1)
        elif raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////") and raw_url != "sqlite:///:memory:":
            rel_path = raw_url.replace("sqlite:///", "", 1)
            resolved_path = (BASE_DIR / rel_path).resolve()
            return f"sqlite:///{resolved_path}"
        return raw_url

    # Check individual MySQL environment parameters
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME")
    db_port = os.getenv("DB_PORT", "3306")

    if db_host and db_user and db_name:
        return f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"

    local_sqlite = (BASE_DIR / "instance" / "drone_system.db").resolve()

    # Prevent accidental SQLite fallback in production
    if env == "production":
        if os.getenv("ALLOW_SQLITE_IN_PRODUCTION") == "1":
            return f"sqlite:///{local_sqlite}"
        # In production without DATABASE_URL, do not fall back to local sqlite
        return ""

    # Local SQLite fallback for development
    if local_sqlite.exists() or env == "development":
        return f"sqlite:///{local_sqlite}"

    # Default MySQL connection for container/local environments
    default_user = os.getenv("DB_USER", "drone_user")
    default_pass = os.getenv("DB_PASSWORD", "")
    default_host = os.getenv("DB_HOST", "127.0.0.1")
    default_name = os.getenv("DB_NAME", "smart_emergency_drone_db")
    return f"mysql+pymysql://{default_user}:{default_pass}@{default_host}:{db_port}/{default_name}?charset=utf8mb4"


def resolve_engine_options(db_uri: str) -> dict:
    """Return appropriate engine options based on dialect and execution environment."""
    if not db_uri or db_uri.startswith("sqlite"):
        return {
            "pool_pre_ping": True,
        }
    return {
        "pool_recycle": 280,
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 2,
    }


class Config:
    """Base configuration with default settings."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = False
    TESTING = False

    # Security & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1" or os.getenv("VERCEL") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour validity

    # Database Configuration
    SQLALCHEMY_DATABASE_URI = resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = resolve_engine_options(SQLALCHEMY_DATABASE_URI)

    # Reverse Proxy Settings
    USE_PROXY_FIX = os.getenv("USE_PROXY_FIX", "0") == "1" or os.getenv("VERCEL") == "1"
    PROXY_FIX_FOR = int(os.getenv("PROXY_FIX_FOR", "1"))
    PROXY_FIX_PROTO = int(os.getenv("PROXY_FIX_PROTO", "1"))
    PROXY_FIX_HOST = int(os.getenv("PROXY_FIX_HOST", "1"))
    PROXY_FIX_PREFIX = int(os.getenv("PROXY_FIX_PREFIX", "1"))

    # Simulation Defaults
    SIMULATION_SPEED_MULTIPLIER = float(os.getenv("SIMULATION_SPEED_MULTIPLIER", "1.0"))
    MAX_DRONE_PAYLOAD_KG = float(os.getenv("MAX_DRONE_PAYLOAD_KG", "5.0"))
    DEFAULT_DRONE_BATTERY_MAH = int(os.getenv("DEFAULT_DRONE_BATTERY_MAH", "5000"))


class DevelopmentConfig(Config):
    """Configuration for local development."""
    DEBUG = True


class TestingConfig(Config):
    """Configuration for automated unit and integration tests."""
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    # Test suite always uses fast, isolated in-memory SQLite
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}


def validate_production_environment(config):
    """Validate that required production environment variables are properly configured.
    
    Raises:
        ValueError: If mandatory production settings (SECRET_KEY, database credentials)
            are missing, empty, or using default insecure placeholders.
    """
    errors = []

    # 1. SECRET_KEY validation
    secret_key = os.getenv("SECRET_KEY", "")
    insecure_defaults = [
        "",
        "dev-secret-key-change-in-production",
        "replace-with-a-secure-random-secret-key-in-production",
        "change-me",
        "secret",
        "password",
    ]
    if not secret_key or secret_key.strip().lower() in insecure_defaults or "change-in-production" in secret_key:
        errors.append(
            "SECRET_KEY is missing or set to an insecure placeholder. "
            "Generate a cryptographically secure random key (e.g. python -c 'import secrets; print(secrets.token_hex(32))')."
        )
    elif len(secret_key) < 32:
        errors.append("SECRET_KEY must be at least 32 characters long in production for cryptographic signing safety.")

    # 2. Database validation & Accidental SQLite fallback prevention
    raw_db_url = os.getenv("DATABASE_URL", "").strip()
    db_uri = raw_db_url or getattr(config, "SQLALCHEMY_DATABASE_URI", "")
    if db_uri and db_uri.startswith("mysql://"):
        db_uri = db_uri.replace("mysql://", "mysql+pymysql://", 1)
    elif db_uri and db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)

    if not raw_db_url:
        db_user = os.getenv("DB_USER", "")
        db_password = os.getenv("DB_PASSWORD", "")
        db_name = os.getenv("DB_NAME", "")
        if not db_user or not db_password or not db_name:
            if os.getenv("ALLOW_SQLITE_IN_PRODUCTION") != "1":
                errors.append(
                    "Database configuration incomplete. In production, provide either DATABASE_URL or set "
                    "DB_USER, DB_PASSWORD, and DB_NAME for MySQL. "
                    "(To permit SQLite in production for standalone demonstrations, set ALLOW_SQLITE_IN_PRODUCTION=1)."
                )

    # Prevent accidental SQLite fallback when DATABASE_URL was not explicitly provided
    if not raw_db_url and db_uri.startswith("sqlite://") and os.getenv("ALLOW_SQLITE_IN_PRODUCTION") != "1":
        errors.append(
            "Accidental SQLite database detected in production. An externally hosted persistent database is required. "
            "(To explicitly allow SQLite for local staging only, set ALLOW_SQLITE_IN_PRODUCTION=1)."
        )

    # 3. Serverless Localhost Check
    if os.getenv("VERCEL") == "1":
        if "127.0.0.1" in db_uri or "localhost" in db_uri:
            errors.append(
                "DATABASE_URL points to localhost/127.0.0.1 in a Vercel serverless environment. "
                "A cloud-hosted database (TiDB Cloud, Aiven, Railway, Supabase) must be configured."
            )

    # 4. Security & Cookie Settings
    if not getattr(config, "SESSION_COOKIE_HTTPONLY", True):
        errors.append("SESSION_COOKIE_HTTPONLY must be True in production to mitigate XSS cookie theft.")
    if getattr(config, "SESSION_COOKIE_SAMESITE", "Lax") not in ("Lax", "Strict"):
        errors.append("SESSION_COOKIE_SAMESITE must be 'Lax' or 'Strict' in production.")
    if not getattr(config, "WTF_CSRF_ENABLED", True):
        errors.append("WTF_CSRF_ENABLED must be True in production.")

    if errors:
        error_msg = "\n".join(f"  [X] {err}" for err in errors)
        raise ValueError(
            f"\n\n{'='*70}\nFATAL CONFIGURATION ERROR - PRODUCTION STARTUP HALTED\n{'='*70}\n"
            f"{error_msg}\n{'='*70}\n"
        )


class ProductionConfig(Config):
    """Configuration for production deployment."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") != "0"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True

    def __init__(self):
        super().__init__()
        validate_production_environment(self)


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
