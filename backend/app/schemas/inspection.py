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
    caption: str | None = None

    # Populated once POST /{id}/evidence/upload's AI analysis has run
    # (immediately, at upload time) -- null for evidence added via the
    # bare-URL EvidenceCreate path, which skips analysis entirely.
    theme: str | None = None
    theme_label: str | None = None
    theme_confidence: float | None = None
    parameter_scores: dict[str, float] | None = None
    ai_findings: list[str] | None = None
    quality_flags: dict[str, bool] | None = None
    analysis_source: str | None = None
    analyzed_at: datetime | None = None


# --- AI inspection-analysis report -------------------------------------
# Viewable and editable by every role EXCEPT pmu_inspector -- enforced
# in app/api/routes/inspections.py, not here.


class ParameterDelta(BaseModel):
    previous: float | None
    current: float | None
    delta: float | None
    trend: str  # improved | declined | stable | newly_assessed | not_assessed_this_time


class PhotoAnalysisOut(BaseModel):
    evidence_id: uuid.UUID | str
    theme: str
    theme_label: str
    confidence: float
    scores: dict[str, float]
    findings: list[str]
    quality_flags: dict[str, bool]
    source: str


class AnalysisEditEntry(BaseModel):
    editor_id: str
    editor_name: str
    edited_at: datetime
    changes: dict


class AnalysisReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inspection_id: uuid.UUID
    project_id: uuid.UUID

    ai_overall_score: float
    ai_grade: str
    ai_parameter_scores: dict[str, float | None]
    ai_parameter_evidence_counts: dict[str, int]
    ai_summary: str
    theme_breakdown: list[dict]

    overall_score: float
    grade: str
    parameter_scores: dict[str, float | None]
    summary: str

    is_edited: bool
    last_edited_by_id: uuid.UUID | None
    last_edited_at: datetime | None
    edit_history: list[dict] | None

    previous_analysis_id: uuid.UUID | None
    comparison_deltas: dict[str, dict] | None
    comparison_summary: str | None
    overall_trend: str | None

    analysis_source: str
    generated_at: datetime
    created_at: datetime


class AnalysisReportUpdate(BaseModel):
    """Everything here is optional -- send only the fields being
    edited. Editing overall_score/parameter_scores/grade/summary never
    touches the ai_* originals, which stay as a permanent reference to
    what the AI actually produced."""
    overall_score: float | None = None
    grade: str | None = None
    parameter_scores: dict[str, float] | None = None
    summary: str | None = None


class AnalysisHistoryEntry(BaseModel):
    """One row in a project's inspection-analysis timeline (oldest to
    newest), used to drive the trend view on the analysis page."""
    inspection_id: uuid.UUID
    completed_at: datetime | None
    overall_score: float
    grade: str
    is_edited: bool
