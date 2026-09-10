import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Enum, ForeignKey, Float, Text, Boolean, Integer
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

    inspection_type = Column(
        Enum(InspectionType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
        default=InspectionType.SURPRISE,
    )
    status = Column(
        Enum(InspectionStatus, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
        default=InspectionStatus.PENDING,
    )

    # True if this inspection's inspector/date was picked by the
    # random-assignment engine rather than a human.
    ai_assigned = Column(Boolean, default=True)

    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # URL/stream key for THIS assignment's live CCTV feed -- different
    # inspections (even for the same project) can point at different
    # cameras/streams. Set by an admin/department official, typically
    # once an inspector and date have been assigned.
    cctv_feed_url = Column(String(500), nullable=True)

       # Geo-tag captured at the moment the report was filed
    report_latitude = Column(Float, nullable=True)
    report_longitude = Column(Float, nullable=True)
    report_text = Column(Text, nullable=True)

    # Set when the assigned inspector checks in as physically present
    # for this inspection. GPS is optional -- some check-ins (e.g. a
    # VC_RANDOM video-call inspection) may not have a meaningful
    # location to capture.
    attendance_marked_at = Column(DateTime, nullable=True)
    attendance_latitude = Column(Float, nullable=True)
    attendance_longitude = Column(Float, nullable=True)
    # Distance in meters between the coordinates above and the
    # project's registered site location (Project.latitude/longitude
    # -- the CCTV feed's actual location), computed at check-in time.
    # NULL if the project has no registered coordinates to compare
    # against.
    attendance_distance_meters = Column(Float, nullable=True)

    # AI attendance verification (presence detection, not identity
    # matching -- see app/services/ai_vision.py). Both set together
    # with the fields above by POST /{id}/checkin.
    attendance_face_checked_at = Column(DateTime, nullable=True)
    attendance_face_count = Column(Integer, nullable=True)
    # True only when exactly one face was found. NULL means no check-in
    # has happened yet for this inspection.
    attendance_face_verified = Column(Boolean, nullable=True)

    # Perceptual hash of the check-in selfie (see
    # app/services/dedupe.py), used to catch the same photo being
    # reused across multiple check-ins by the same inspector.
    attendance_photo_hash = Column(String(16), nullable=True)
    attendance_duplicate_detected = Column(Boolean, nullable=True)

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
