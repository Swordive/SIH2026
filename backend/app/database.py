"""
SQLAlchemy engine + session handling.
Every request gets its own DB session via the get_db dependency
(defined in api/deps.py) which always closes the session afterward.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
