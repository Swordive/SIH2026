import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Enum, ForeignKey, Float, Text, Boolean, Integer, JSON
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

    # Where the actual check-in selfie itself was saved (see
    # POST /{id}/checkin), so an attendance alert raised against this
    # inspection can be reviewed against the real photo later instead
    # of only the face_count number. NULL until a check-in happens.
    attendance_photo_url = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    evidence = relationship("InspectionEvidence", back_populates="inspection")
    analysis = relationship(
        "InspectionAnalysisReport",
        back_populates="inspection",
        uselist=False,
        foreign_keys="InspectionAnalysisReport.inspection_id",
    )


class InspectionEvidence(Base):
    """Photo / video evidence attached to an inspection report.

    Each photo is run through the AI inspection-analysis pipeline
    (see app/services/ai_inspection_analysis.py) at upload time: the
    pipeline guesses what the photo is actually *of* (a washroom, a
    cracked wall, an electrical panel, ...) and, from that, which
    quality parameters it's actually evidence for -- a washroom photo
    speaks to cleanliness/hygiene, a cracked-wall photo speaks to
    infrastructure/safety, and so on. The per-photo results below are
    the raw inputs that get aggregated (see InspectionAnalysisReport)
    into the inspection-level score once the report is submitted.
    """

    __tablename__ = "inspection_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inspection_id = Column(UUID(as_uuid=True), ForeignKey("inspections.id"), nullable=False)
    inspection = relationship("Inspection", back_populates="evidence")

    file_url = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=True)  # image / video
    captured_at = Column(DateTime, default=datetime.utcnow)

    # Free-text label the inspector optionally attaches when uploading
    # a photo (e.g. "Boys' washroom, ground floor" / "Crack in east
    # corridor wall"). Purely descriptive context from the person who
    # was actually standing there -- fed into theme detection
    # alongside the pixel analysis, never overriding it outright.
    caption = Column(String(300), nullable=True)

    # --- AI analysis of this specific photo -----------------------
    # Theme = what the photo is actually a picture of, from a fixed
    # taxonomy (see THEME_RULES in ai_inspection_analysis.py):
    # "restroom", "kitchen_dining", "classroom_office", "dormitory",
    # "corridor_common", "structural_damage", "electrical", "water_drainage",
    # "exterior_campus", "fire_safety", "general".
    theme = Column(String(40), nullable=True)
    theme_label = Column(String(120), nullable=True)  # human-readable version of theme
    theme_confidence = Column(Float, nullable=True)  # 0-1

    # Which quality parameters this photo is treated as evidence for,
    # and what it scored on each (0-100). Only the parameters implied
    # by the detected theme are populated -- a washroom photo doesn't
    # get an "aesthetics" score, a cracked-wall photo doesn't get a
    # "hygiene" score.
    parameter_scores = Column(JSON, nullable=True)  # {"cleanliness": 72.0, ...}
    ai_findings = Column(JSON, nullable=True)  # list[str] short bullet observations
    quality_flags = Column(JSON, nullable=True)  # {"blurry": bool, "too_dark": bool, ...}

    analysis_source = Column(String(20), nullable=True)  # "vision_api" | "heuristic"
    analyzed_at = Column(DateTime, nullable=True)


# Every parameter this system ever scores -- kept in one place
# (imported by the schema layer too) so the taxonomy and the model
# stay in sync. See app/services/ai_inspection_analysis.py for how
# each is derived and weighted.
ANALYSIS_PARAMETERS = (
    "cleanliness",
    "hygiene",
    "infrastructure",
    "safety",
    "maintenance",
    "aesthetics",
)


class InspectionAnalysisReport(Base):
    """
    The AI-generated (and subsequently human-editable) analysis for
    one completed inspection: per-parameter point scores rolled up
    from every submitted photo, an overall score + grade, a written
    review, and -- when a prior completed inspection exists for the
    same project -- a comparison against it (improved / declined /
    unchanged per parameter, plus a narrative).

    Deliberately keeps the AI's original output (ai_*) separate from
    the current, possibly hand-edited, values (the plain-named
    columns) rather than overwriting the AI's work in place: the
    original is what the AI actually produced and stays available as
    a reference even after an admin/department official/project
    incharge edits the working copy.

    Visibility rule (enforced in the route layer, not here): viewable
    and editable by every role except pmu_inspector -- the inspector
    submits the raw evidence this is built from, but doesn't see the
    resulting review.
    """

    __tablename__ = "inspection_analysis_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    inspection_id = Column(
        UUID(as_uuid=True), ForeignKey("inspections.id"), nullable=False, unique=True
    )
    inspection = relationship(
        "Inspection", back_populates="analysis", foreign_keys=[inspection_id]
    )
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)

    # --- AI-generated originals (immutable once written) -----------
    ai_overall_score = Column(Float, nullable=False)
    ai_grade = Column(String(30), nullable=False)
    ai_parameter_scores = Column(JSON, nullable=False)  # {"cleanliness": 78.4, ...}
    # How many photos contributed to each parameter's score -- shown
    # in the UI so a score based on 1 photo reads differently from one
    # based on 6.
    ai_parameter_evidence_counts = Column(JSON, nullable=False)  # {"cleanliness": 3, ...}
    ai_summary = Column(Text, nullable=False)
    # Snapshot of every photo's own analysis at the time this report
    # was generated (theme, scores, findings) -- so the photo-by-photo
    # breakdown in the UI doesn't depend on evidence rows never being
    # edited/removed later.
    theme_breakdown = Column(JSON, nullable=False)  # list[dict]

    # --- Working copy (starts identical to the ai_* fields above,
    # then diverges as people edit it) -----------------------------
    overall_score = Column(Float, nullable=False)
    grade = Column(String(30), nullable=False)
    parameter_scores = Column(JSON, nullable=False)
    summary = Column(Text, nullable=False)

    is_edited = Column(Boolean, default=False)
    last_edited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    last_edited_by = relationship("User", foreign_keys=[last_edited_by_id])
    last_edited_at = Column(DateTime, nullable=True)
    # Append-only audit trail: [{editor_id, editor_name, edited_at, changes: {...}}, ...]
    edit_history = Column(JSON, nullable=True)

    # --- Comparison against the previous completed inspection for
    # the same project (null if this is the first analyzed inspection
    # at this project) ------------------------------------------------
    previous_analysis_id = Column(
        UUID(as_uuid=True), ForeignKey("inspection_analysis_reports.id"), nullable=True
    )
    previous_analysis = relationship(
        "InspectionAnalysisReport", remote_side=[id], foreign_keys=[previous_analysis_id]
    )
    comparison_deltas = Column(JSON, nullable=True)
    # {"cleanliness": {"previous": 70.0, "current": 82.0, "delta": 12.0, "trend": "improved"}, ...}
    comparison_summary = Column(Text, nullable=True)
    overall_trend = Column(String(20), nullable=True)  # improved / declined / stable / new_baseline

    analysis_source = Column(String(20), nullable=False, default="heuristic")

    generated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
