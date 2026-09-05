"""
SQLAlchemy engine + session handling.
Every request gets its own DB session via the get_db dependency
(defined in api/deps.py) which always closes the session afterward.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# SQLite needs this extra flag because, by default, it only allows the
# thread that created a connection to use it -- but FastAPI can handle
# requests on different threads. This flag relaxes that restriction,
# which is safe here since each request gets its own session anyway.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()