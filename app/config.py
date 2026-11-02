import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if present
load_dotenv(BASE_DIR / ".env")


class Config:
    """Base configuration with default settings."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = False
    TESTING = False

    # Security & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour validity

    # MySQL Database Settings
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_USER = os.getenv("DB_USER", "drone_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "smart_emergency_drone_db")

    # Priority: explicit DATABASE_URL -> constructed MySQL URI
    _raw_db_url = os.getenv("DATABASE_URL")
    if _raw_db_url and _raw_db_url.startswith("sqlite:///") and not _raw_db_url.startswith("sqlite:////") and _raw_db_url != "sqlite:///:memory:":
        _rel_path = _raw_db_url.replace("sqlite:///", "")
        _resolved_path = (BASE_DIR / _rel_path).resolve()
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{_resolved_path}"
    elif _raw_db_url:
        SQLALCHEMY_DATABASE_URI = _raw_db_url
    else:
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }

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


class ProductionConfig(Config):
    """Configuration for production deployment."""
    DEBUG = False
    TESTING = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
