import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]  # /app/backend
load_dotenv(ROOT_DIR / ".env")


class Settings:
    # Database
    MONGO_URL: str = os.environ["MONGO_URL"]
    DB_NAME: str = os.environ["DB_NAME"]

    # Auth
    JWT_SECRET: str = os.environ.get("JWT_SECRET", "wheelind-dev-secret-change-me")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_MINUTES", "1440"))

    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "admin@wheelind.com")
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "admin123")

    # OTP
    OTP_TTL_SECONDS: int = int(os.environ.get("OTP_TTL_SECONDS", "300"))
    OTP_DEBUG: bool = os.environ.get("OTP_DEBUG", "true").lower() == "true"

    # Presence / matching
    HEARTBEAT_TTL_SECONDS: int = int(os.environ.get("HEARTBEAT_TTL_SECONDS", "30"))
    MATCH_RADIUS_METERS: int = int(os.environ.get("MATCH_RADIUS_METERS", "5000"))
    OFFER_TTL_SECONDS: int = int(os.environ.get("OFFER_TTL_SECONDS", "20"))
    MAX_DISPATCH_ATTEMPTS: int = int(os.environ.get("MAX_DISPATCH_ATTEMPTS", "5"))

    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "*")

    # Redis (hot real-time layer)
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    WORKER_POLL_SECONDS: int = int(os.environ.get("WORKER_POLL_SECONDS", "3"))


settings = Settings()
