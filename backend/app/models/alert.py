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

    # Which specific check-in this alert came from, when it came from
    # one -- e.g. a face-check/duplicate-photo/geofence alert raised
    # by POST /inspections/{id}/checkin (see that route). NULL for
    # alerts that aren't tied to any one inspection, e.g. a general
    # CCTV/AI anomaly posted in by the external AI/CCTV system via
    # POST /api/alerts. This is what lets the dashboard's "Review
    # footage" action send the reviewer to the actual evidence for
    # THIS alert (the submitted selfie for an attendance alert)
    # instead of always falling back to the live camera feed.
    inspection_id = Column(UUID(as_uuid=True), ForeignKey("inspections.id"), nullable=True)
    inspection = relationship("Inspection")

    # What kind of check raised this alert -- "face_check",
    # "geofence", or "duplicate_photo" for the three automatic
    # checks in POST /inspections/{id}/checkin, NULL for anything
    # else (e.g. a general CCTV/AI anomaly with no single inspection
    # behind it). Kept as a plain string rather than an Enum so the
    # external AI/CCTV system posting via POST /api/alerts isn't
    # forced to pick from a fixed list it may not know about yet.
    kind = Column(String(30), nullable=True)

    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="medium")
    resolved = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)