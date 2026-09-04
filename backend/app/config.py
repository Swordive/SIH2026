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
    # Example: postgresql+psycopg2://user:password@localhost:5432/sih_monitoring
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/sih_monitoring"
    )

    # --- Auth / JWT ---
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # --- CORS ---
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

        # --- Random assignment engine ---
    # How many projects the daily scheduler auto-assigns inspections to.
    DAILY_AUTO_ASSIGN_COUNT: int = 5


settings = Settings()
