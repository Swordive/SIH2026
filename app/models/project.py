import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Float, Text
from sqlalchemy.orm import relationship

from app.database import Base


class EntityType(str, enum.Enum):
    PROJECT = "project"
    INSTITUTE = "institute"
    NGO = "ngo"


class Project(Base):
    """A project / institute / NGO running under a DoSJE scheme."""

    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(250), nullable=False)
    entity_type = Column(Enum(EntityType), nullable=False, default=EntityType.PROJECT)
    scheme_name = Column(String(200), nullable=True)  # e.g. name of DoSJE scheme
    address = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # URL/stream key for the live CCTV feed integration
    cctv_feed_url = Column(String(500), nullable=True)

    incharge_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    incharge = relationship("User", back_populates="projects")

    created_at = Column(DateTime, default=datetime.utcnow)

    inspections = relationship("Inspection", back_populates="project")