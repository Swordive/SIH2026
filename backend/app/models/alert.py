import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Alert(Base):
    """An anomaly/alert raised by the AI/CCTV system for a specific
    project. This is the bridge between the AI/CCTV team's work and
    the admin dashboard's 'View Alerts' panel."""

    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    project = relationship("Project")

    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="medium")
    resolved = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)