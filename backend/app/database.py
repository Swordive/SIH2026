"""
SQLAlchemy engine + session handling.
Every request gets its own DB session via the get_db dependency
(defined in api/deps.py) which always closes the session afterward.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Without this, a DB host that's unreachable (paused/sleeping
    # managed DB, wrong host, firewall silently dropping packets
    # instead of refusing the connection) makes every request that
    # touches the DB -- including login -- hang for minutes rather
    # than failing fast with a clear error. 8s is generous for a
    # healthy connection, short enough that a login request fails
    # visibly instead of leaving the "Signing in..." button spinning
    # forever.
    connect_args={"connect_timeout": 8},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
