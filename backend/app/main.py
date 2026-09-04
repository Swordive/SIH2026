from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import Base, engine, SessionLocal
from app import models  # noqa: F401  (ensures all models are registered on Base)
from app.api.routes import auth, users, projects, inspections
from app.services.assignment import run_random_assignment

scheduler = BackgroundScheduler()


def _daily_auto_assignment_job():
    """Runs the random assignment engine once a day, unattended."""
    db = SessionLocal()
    try:
        run_random_assignment(db, max_assignments=settings.DAILY_AUTO_ASSIGN_COUNT)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    # For the hackathon build we create tables directly from the models.
    # Swap this for Alembic migrations once the schema stabilizes.
    Base.metadata.create_all(bind=engine)

    if not scheduler.running:
        scheduler.add_job(
            _daily_auto_assignment_job,
            "interval",
            hours=24,
            id="daily_auto_assignment",
            replace_existing=True,
        )
        scheduler.start()

    yield

    # --- shutdown ---
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(inspections.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}