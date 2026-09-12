"""
Central app configuration.
Reads values from environment variables / a .env file so nothing
sensitive (DB passwords, JWT secret) is hardcoded.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "GOV-INSPECT"
    ENV: str = "development"
    DEBUG: bool = True

    # --- Database ---
    # Example: postgresql+psycopg2://user:password@localhost:5432/sih_monitoring
    DATABASE_URL: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/sih_monitoring"
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

    # --- AI inspection-report analysis (see app/services/ai_inspection_analysis.py) ---
    # All optional. With none of these set, photo analysis runs
    # entirely offline via OpenCV heuristics + keyword/caption theme
    # matching -- identical behaviour to app/services/ai_vision.py's
    # face-check, and the app works fully out of the box. Setting any
    # one of these keys upgrades photo analysis to a real vision-
    # language model for theme detection + scoring; the service tries
    # providers in VISION_PROVIDER_ORDER and falls back to the next
    # one (and ultimately to the offline heuristic) on any error, so a
    # missing key, a bad key, or no network never breaks the feature.
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None  # Gemini
    VISION_PROVIDER_ORDER: list[str] = ["anthropic", "openai", "google"]
    VISION_API_TIMEOUT_SECONDS: float = 20.0


settings = Settings()
