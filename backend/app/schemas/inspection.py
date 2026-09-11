import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.inspection import InspectionStatus, InspectionType


class InspectionCreate(BaseModel):
    project_id: uuid.UUID
    inspection_type: InspectionType = InspectionType.SURPRISE
    scheduled_at: datetime | None = None
    cctv_feed_url: str | None = None


class InspectionUpdate(BaseModel):
    """Used to attach/change/remove this inspection's own CCTV feed
    (independent of assigning an inspector/date -- see InspectionAssign)."""
    cctv_feed_url: str | None = None


class InspectionReportSubmit(BaseModel):
    report_text: str
    report_latitude: float
    report_longitude: float


class InspectionAssign(BaseModel):
    """Used by an admin/department official to assign an inspector
    and a date/time to an inspection the random-assignment engine
    already created (unassigned)."""
    inspector_id: uuid.UUID
    scheduled_at: datetime


class CheckinOut(BaseModel):
    """Result of POST /{id}/checkin -- the single, mandatory,
    inspector-only attendance action: GPS + a selfie, both required,
    checked against the project's registered site location, against
    face detection, and against every previous check-in selfie by the
    same inspector."""

    face_count: int
    face_verified: bool
    distance_meters: float | None
    within_geofence: bool | None  # null if the project has no registered site coordinates
    duplicate_photo_detected: bool
    alerts_created: list[str]
    checked_at: datetime


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    inspector_id: uuid.UUID | None
    inspection_type: InspectionType
    status: InspectionStatus
    ai_assigned: bool
    scheduled_at: datetime | None
    completed_at: datetime | None
    cctv_feed_url: str | None
    report_latitude: float | None
    report_longitude: float | None
    report_text: str | None
    attendance_marked_at: datetime | None
    attendance_latitude: float | None
    attendance_longitude: float | None
    attendance_distance_meters: float | None
    attendance_face_checked_at: datetime | None
    attendance_face_count: int | None
    attendance_face_verified: bool | None
    attendance_duplicate_detected: bool | None
    attendance_photo_url: str | None
    created_at: datetime


class EvidenceCreate(BaseModel):
    file_url: str
    file_type: str | None = None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inspection_id: uuid.UUID
    file_url: str
    file_type: str | None
    captured_at: datetime
