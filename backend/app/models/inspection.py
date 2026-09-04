import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Enum, ForeignKey, Float, Text, Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class InspectionStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MISSED = "missed"


class InspectionType(str, enum.Enum):
    SURPRISE = "surprise"
    SCHEDULED = "scheduled"
    VC_RANDOM = "vc_random"  # random video-conference check-in


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    project = relationship("Project", back_populates="inspections")

    inspector_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    inspector = relationship(
        "User", back_populates="inspections", foreign_keys=[inspector_id]
    )

    inspection_type = Column(Enum(InspectionType), nullable=False, default=InspectionType.SURPRISE)
    status = Column(Enum(InspectionStatus), nullable=False, default=InspectionStatus.PENDING)

    # True if this inspection's inspector/date was picked by the
    # random-assignment engine rather than a human.
    ai_assigned = Column(Boolean, default=True)

    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Geo-tag captured at the moment the report was filed
    report_latitude = Column(Float, nullable=True)
    report_longitude = Column(Float, nullable=True)
    report_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    evidence = relationship("InspectionEvidence", back_populates="inspection")


class InspectionEvidence(Base):
    """Photo / video evidence attached to an inspection report."""

    __tablename__ = "inspection_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inspection_id = Column(UUID(as_uuid=True), ForeignKey("inspections.id"), nullable=False)
    inspection = relationship("Inspection", back_populates="evidence")

    file_url = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=True)  # image / video
    captured_at = Column(DateTime, default=datetime.utcnow)
