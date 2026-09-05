"""
Central app configuration.
Reads values from environment variables / a .env file so nothing
sensitive (DB passwords, JWT secret) is hardcoded.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "DoSJE Smart Monitoring & Inspection System"
    ENV: str = "development"
    DEBUG: bool = True

    # --- Database ---
    # SQLite for the hackathon prototype -- a single local file, no
    # separate database server needed.
    DATABASE_URL: str = "sqlite:///./sih_monitoring.db"

    # --- Auth / JWT ---
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # --- CORS ---
    ALLOWED_ORIGINS: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Random assignment engine ---
    # How many projects the daily scheduler auto-assigns inspections to.
    DAILY_AUTO_ASSIGN_COUNT: int = 5


settings = Settings()