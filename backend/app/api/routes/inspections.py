import mimetypes
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.alert import Alert
from app.models.inspection import (
    Inspection,
    InspectionStatus,
    InspectionType,
    InspectionEvidence,
    InspectionAnalysisReport,
    ANALYSIS_PARAMETERS,
)
from app.schemas.inspection import (
    InspectionCreate,
    InspectionOut,
    InspectionReportSubmit,
    InspectionAssign,
    InspectionUpdate,
    EvidenceCreate,
    EvidenceOut,
    CheckinOut,
    AnalysisReportOut,
    AnalysisReportUpdate,
    AnalysisHistoryEntry,
)
from app.services.assignment import run_random_assignment
from app.services.ai_vision import detect_faces, InvalidImageError
from app.services.geofence import distance_meters, GEOFENCE_RADIUS_METERS
from app.services.dedupe import compute_phash, is_duplicate
from app.services import ai_inspection_analysis as analysis_engine

router = APIRouter(prefix="/api/inspections", tags=["inspections"])

# Roles allowed to view/edit the AI analysis report -- every role
# except pmu_inspector. The inspector supplies the raw evidence this
# is built from, but does not see the resulting review (see
# InspectionAnalysisReport's docstring in app/models/inspection.py).
ANALYSIS_VIEWER_ROLES = (UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)

# Keeps a misbehaving/huge upload from tying up a worker decoding it.
MAX_CHECKIN_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_EVIDENCE_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB

# Where check-in selfies get saved so an attendance alert can later be
# reviewed against the actual photo (see checkin() below) instead of
# only the face_count number. Served back out at /static/checkins/...
# by the StaticFiles mount in main.py -- created here (module import
# time) so it exists before that mount is set up.
CHECKIN_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "checkins"
CHECKIN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Where inspection-report evidence photos get saved (see
# add_evidence_upload() below). Served back out at /static/evidence/...
# by the StaticFiles mount in main.py.
EVIDENCE_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "evidence"
EVIDENCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/auto-assign", response_model=list[InspectionOut])
def auto_assign_inspections(
    max_assignments: int = 5,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    """
    Runs the random assignment engine on demand: picks up to
    max_assignments random projects and creates unassigned
    inspections for them with a randomly chosen type. Not limited to
    one per project -- click again for more, including repeats for
    the same project. An admin/department official assigns an
    inspector and date/time to each one afterward via
    PATCH /{inspection_id}/assign.
    """
    return run_random_assignment(db, max_assignments=max_assignments)


@router.post("/manual", response_model=InspectionOut, status_code=201)
def add_manual_inspection(
    project_id: uuid.UUID,
    inspection_type: InspectionType = InspectionType.SURPRISE,
    cctv_feed_url: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    """
    Adds a single unassigned inspection for a specific project, with
    a type chosen by the admin/department official. Unlike
    /auto-assign, this bypasses the "already covered recently" filter
    -- use this when you want to add another inspection for a project
    that already has one. Marked ai_assigned=False since a human
    picked both the project and the type here.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    inspection = Inspection(
        project_id=project.id,
        inspector_id=None,
        inspection_type=inspection_type,
        status=InspectionStatus.PENDING,
        ai_assigned=False,
        scheduled_at=None,
        cctv_feed_url=cctv_feed_url,
    )
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.post("", response_model=InspectionOut, status_code=201)
def create_inspection(
    payload: InspectionCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    """Manual creation with full control, e.g. for a scheduled
    (non-surprise) inspection where the admin already knows the
    inspector and date upfront."""
    inspection = Inspection(**payload.model_dump())
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.get("", response_model=list[InspectionOut])
def list_inspections(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    query = db.query(Inspection)

    # PMU inspectors only see inspections assigned to them -- never
    # anyone else's. Every other role (admin, department official,
    # project incharge) continues to see the full list.
    if current_user.role == UserRole.PMU_INSPECTOR:
        query = query.filter(Inspection.inspector_id == current_user.id)

    return query.order_by(Inspection.created_at.desc()).all()

@router.get("/{inspection_id}", response_model=InspectionOut)
def get_inspection(
       inspection_id: uuid.UUID,
       db: Session = Depends(get_db),
       _user: User = Depends(get_current_user),
   ):
       inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
       if not inspection:
           raise HTTPException(status_code=404, detail="Inspection not found")
       return inspection


@router.patch("/{inspection_id}", response_model=InspectionOut)
def update_inspection(
    inspection_id: uuid.UUID,
    payload: InspectionUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    """
    Attaches, changes, or clears this specific inspection's CCTV feed.
    Kept separate from PATCH /{id}/assign since setting up a camera is
    a distinct step from picking an inspector and date -- either can
    happen first, and this can be called again later to swap feeds.
    """
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(inspection, field, value)

    db.commit()
    db.refresh(inspection)
    return inspection


@router.patch("/{inspection_id}/assign", response_model=InspectionOut)
def assign_inspection(
    inspection_id: uuid.UUID,
    payload: InspectionAssign,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    """
    Assigns an inspector and a date/time to an inspection that the
    random-assignment engine already created (project + type chosen,
    but left unassigned). This is the human-in-the-loop step: the
    engine surfaces what needs inspecting, the admin decides who does
    it and when.
    """
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    inspector = db.query(User).filter(User.id == payload.inspector_id).first()
    if not inspector:
        raise HTTPException(status_code=404, detail="Inspector not found")
    if inspector.role != UserRole.PMU_INSPECTOR:
        raise HTTPException(
            status_code=400, detail="Selected user is not a PMU inspector"
        )
    if not inspector.is_active:
        raise HTTPException(status_code=400, detail="Selected inspector is not active")

    inspection.inspector_id = inspector.id
    inspection.scheduled_at = payload.scheduled_at

    db.commit()
    db.refresh(inspection)
    return inspection


@router.delete("/{inspection_id}", status_code=204)
def delete_inspection(
    inspection_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    db.query(InspectionEvidence).filter(
        InspectionEvidence.inspection_id == inspection_id
    ).delete()
    db.delete(inspection)
    db.commit()
    return None


@router.post("/{inspection_id}/submit-report", response_model=InspectionOut)
def submit_report(
    inspection_id: uuid.UUID,
    payload: InspectionReportSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.PMU_INSPECTOR, UserRole.ADMIN)
    ),
):
    """
    Finalizes the inspection report. Any evidence photos should be
    uploaded first via POST /{id}/evidence/upload (each is analyzed
    individually the moment it's uploaded); this call takes the
    written report text + geo-tag, marks the inspection COMPLETED,
    and then rolls every already-analyzed photo up into one
    inspection-level AI analysis report -- see
    _generate_analysis_report() below and
    app/services/ai_inspection_analysis.py for the actual scoring.
    """
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    if (
        current_user.role == UserRole.PMU_INSPECTOR
        and inspection.inspector_id != current_user.id
    ):
        raise HTTPException(
            status_code=403, detail="This inspection is not assigned to you"
        )

    inspection.report_text = payload.report_text
    inspection.report_latitude = payload.report_latitude
    inspection.report_longitude = payload.report_longitude
    inspection.status = InspectionStatus.COMPLETED
    inspection.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(inspection)

    _generate_analysis_report(db, inspection)

    db.refresh(inspection)
    return inspection


def _generate_analysis_report(db: Session, inspection: Inspection) -> InspectionAnalysisReport:
    """Aggregates every analyzed evidence photo for this inspection
    (plus the report text) into one InspectionAnalysisReport, and
    compares it against the most recent previously-completed
    inspection's analysis for the same project, if one exists. Safe
    to call again for the same inspection (e.g. report resubmitted) --
    replaces the existing analysis row rather than duplicating it,
    but preserves edit_history so manual edits aren't silently lost
    on a re-submit.
    """
    evidence_rows = (
        db.query(InspectionEvidence)
        .filter(
            InspectionEvidence.inspection_id == inspection.id,
            InspectionEvidence.parameter_scores.isnot(None),
        )
        .order_by(InspectionEvidence.captured_at.asc())
        .all()
    )
    photo_records = [
        (
            str(row.id),
            analysis_engine.PhotoAnalysis(
                theme=row.theme,
                theme_label=row.theme_label,
                confidence=row.theme_confidence or 0.5,
                scores=row.parameter_scores or {},
                findings=row.ai_findings or [],
                quality_flags=row.quality_flags or {},
                source=row.analysis_source or "heuristic",
            ),
        )
        for row in evidence_rows
    ]

    aggregated = analysis_engine.aggregate_analysis(photo_records, inspection.report_text or "")

    # Most recent COMPLETED inspection for the same project that
    # already has its own analysis, excluding this one -- "previous"
    # is by completion time, not creation time, so a late-filed report
    # for an earlier visit doesn't jump the queue.
    previous = (
        db.query(InspectionAnalysisReport)
        .join(Inspection, InspectionAnalysisReport.inspection_id == Inspection.id)
        .filter(
            Inspection.project_id == inspection.project_id,
            Inspection.id != inspection.id,
            Inspection.status == InspectionStatus.COMPLETED,
        )
        .order_by(Inspection.completed_at.desc())
        .first()
    )

    comparison_deltas = comparison_summary = overall_trend = None
    previous_analysis_id = None
    if previous is not None:
        previous_analysis_id = previous.id
        previous_completed_at = (
            previous.inspection.completed_at if previous.inspection else None
        )
        comparison_deltas, comparison_summary, overall_trend = analysis_engine.compare_analyses(
            current_scores=aggregated.parameter_scores,
            current_overall=aggregated.overall_score,
            previous_scores=previous.parameter_scores,
            previous_overall=previous.overall_score,
            previous_date=previous_completed_at,
        )
    else:
        overall_trend = "new_baseline"

    existing = (
        db.query(InspectionAnalysisReport)
        .filter(InspectionAnalysisReport.inspection_id == inspection.id)
        .first()
    )

    if existing is None:
        existing = InspectionAnalysisReport(
            inspection_id=inspection.id,
            project_id=inspection.project_id,
        )
        db.add(existing)

    existing.ai_overall_score = aggregated.overall_score
    existing.ai_grade = aggregated.grade
    existing.ai_parameter_scores = aggregated.parameter_scores
    existing.ai_parameter_evidence_counts = aggregated.parameter_evidence_counts
    existing.ai_summary = aggregated.summary
    existing.theme_breakdown = aggregated.theme_breakdown

    # A re-submit (report edited/resubmitted before anyone reviewed
    # it) refreshes the working copy from the new AI output too; once
    # a human has actually edited the report (is_edited=True), a
    # re-submit no longer silently overwrites their edits -- the new
    # AI output is still recorded in ai_* above for reference, but the
    # working copy is left alone.
    if not existing.is_edited:
        existing.overall_score = aggregated.overall_score
        existing.grade = aggregated.grade
        existing.parameter_scores = aggregated.parameter_scores
        existing.summary = aggregated.summary

    existing.previous_analysis_id = previous_analysis_id
    existing.comparison_deltas = comparison_deltas
    existing.comparison_summary = comparison_summary
    existing.overall_trend = overall_trend
    existing.analysis_source = aggregated.source
    existing.generated_at = datetime.utcnow()

    db.commit()
    db.refresh(existing)
    return existing


@router.post("/{inspection_id}/checkin", response_model=CheckinOut)
async def checkin(
    inspection_id: uuid.UUID,
    latitude: float = Form(...),
    longitude: float = Form(...),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PMU_INSPECTOR)),
):
    """
    The one mandatory attendance action for the assigned PMU
    inspector, physically at the project site: GPS coordinates and a
    selfie, both required (no optional path -- an inspection with no
    check-in has no attendance record at all). Nothing here is
    admin-performable; admins review the results, they don't produce
    them.

    Two independent AI checks run against the submission, each
    capable of raising an Alert on its own:

    1. Face detection (see app/services/ai_vision.py) on the photo --
       flags check-ins where the selfie doesn't show exactly one
       person (0 faces: blank/stale photo; 2+: someone else's device,
       a proxy holding up someone else's photo).
    2. Geofencing (see app/services/geofence.py) -- compares the
       submitted GPS against the project's registered site
       coordinates (Project.latitude/longitude, the CCTV feed's
       actual location), not wherever the browser/device making the
       request happens to be. Flags check-ins made too far from the
       registered site. If the project has no registered coordinates
       yet, this check is skipped (within_geofence/distance_meters
       come back null) rather than guessed at.
    3. Duplicate-photo detection (see app/services/dedupe.py) --
       compares this selfie's perceptual hash against every previous
       check-in selfie by the same inspector. Flags the classic
       "photographed once, resubmitted forever" pattern instead of
       taking a fresh selfie each time.
    """
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    if inspection.inspector_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="This inspection is not assigned to you"
        )

    if inspection.status not in (InspectionStatus.PENDING, InspectionStatus.IN_PROGRESS):
        raise HTTPException(
            status_code=400,
            detail=f"This inspection is already {inspection.status.value}",
        )

    image_bytes = await photo.read()
    if len(image_bytes) > MAX_CHECKIN_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8MB)")

    try:
        face_result = detect_faces(image_bytes)
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Persist the selfie itself (previously this photo was decoded for
    # the checks above and then discarded -- there was no way to look
    # at it again afterwards, which is exactly what "Review footage"
    # on an attendance alert needs). A fresh uuid per upload (not just
    # the inspection id) so a re-check-in via "Check in again" doesn't
    # clobber the file behind an alert already raised against the
    # previous attempt.
    ext = mimetypes.guess_extension(photo.content_type or "") or ".jpg"
    if ext == ".jpe":  # mimetypes' preferred guess for image/jpeg on some platforms
        ext = ".jpg"
    photo_filename = f"{inspection.id}_{uuid.uuid4().hex}{ext}"
    (CHECKIN_UPLOAD_DIR / photo_filename).write_bytes(image_bytes)
    photo_url = f"/static/checkins/{photo_filename}"

    project = db.query(Project).filter(Project.id == inspection.project_id).first()

    face_verified = face_result.face_count == 1
    checked_at = datetime.utcnow()

    site_distance = None
    within_geofence = None
    if project is not None and project.latitude is not None and project.longitude is not None:
        site_distance = distance_meters(
            latitude, longitude, project.latitude, project.longitude
        )
        within_geofence = site_distance <= GEOFENCE_RADIUS_METERS

    photo_hash = compute_phash(image_bytes)
    duplicate_of = (
        db.query(Inspection)
        .filter(
            Inspection.inspector_id == current_user.id,
            Inspection.id != inspection.id,
            Inspection.attendance_photo_hash.isnot(None),
        )
        .all()
    )
    duplicate_match = next(
        (row for row in duplicate_of if is_duplicate(photo_hash, row.attendance_photo_hash)),
        None,
    )
    duplicate_detected = duplicate_match is not None

    inspection.attendance_marked_at = checked_at
    inspection.attendance_latitude = latitude
    inspection.attendance_longitude = longitude
    inspection.attendance_distance_meters = site_distance
    inspection.attendance_face_checked_at = checked_at
    inspection.attendance_face_count = face_result.face_count
    inspection.attendance_face_verified = face_verified
    inspection.attendance_photo_hash = photo_hash
    inspection.attendance_duplicate_detected = duplicate_detected
    inspection.attendance_photo_url = photo_url
    if inspection.status == InspectionStatus.PENDING:
        inspection.status = InspectionStatus.IN_PROGRESS

    alerts_created = []

    if not face_verified:
        if face_result.face_count == 0:
            severity = "high"
            message = (
                "AI attendance check: no face detected in the check-in "
                f"photo for inspection {inspection.id} — possible proxy "
                "attendance."
            )
        else:
            severity = "medium"
            message = (
                f"AI attendance check: {face_result.face_count} faces "
                f"detected in the check-in photo for inspection "
                f"{inspection.id} — expected exactly one."
            )
        db.add(
            Alert(
                project_id=inspection.project_id,
                inspection_id=inspection.id,
                kind="face_check",
                message=message,
                severity=severity,
            )
        )
        alerts_created.append("face")

    if within_geofence is False:
        db.add(
            Alert(
                project_id=inspection.project_id,
                inspection_id=inspection.id,
                kind="geofence",
                message=(
                    "AI attendance check: check-in GPS is "
                    f"{site_distance:.0f}m from the registered site "
                    f"location for inspection {inspection.id} — "
                    "possible incorrect or spoofed location."
                ),
                severity="high",
            )
        )
        alerts_created.append("geofence")

    if duplicate_detected:
        db.add(
            Alert(
                project_id=inspection.project_id,
                inspection_id=inspection.id,
                kind="duplicate_photo",
                message=(
                    "AI attendance check: the check-in selfie for "
                    f"inspection {inspection.id} appears to be the same "
                    f"photo used for a previous check-in (inspection "
                    f"{duplicate_match.id}) — possible reused/stale photo."
                ),
                severity="high",
            )
        )
        alerts_created.append("duplicate_photo")

    db.commit()
    db.refresh(inspection)

    return CheckinOut(
        face_count=face_result.face_count,
        face_verified=face_verified,
        distance_meters=site_distance,
        within_geofence=within_geofence,
        duplicate_photo_detected=duplicate_detected,
        alerts_created=alerts_created,
        checked_at=checked_at,
    )


@router.post("/{inspection_id}/evidence", response_model=EvidenceOut, status_code=201)
def add_evidence(
       inspection_id: uuid.UUID,
       payload: EvidenceCreate,
       db: Session = Depends(get_db),
       _user: User = Depends(get_current_user),
   ):
       """Attaches an already-hosted file by URL, with no AI analysis
       (there's no image to analyze -- just a reference). For a photo
       the inspector is uploading directly from the field, use
       POST /{id}/evidence/upload instead, which runs it through the
       AI theme/parameter analysis pipeline immediately."""
       inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
       if not inspection:
           raise HTTPException(status_code=404, detail="Inspection not found")

       evidence = InspectionEvidence(
           inspection_id=inspection_id,
           file_url=payload.file_url,
           file_type=payload.file_type,
       )
       db.add(evidence)
       db.commit()
       db.refresh(evidence)
       return evidence


@router.post("/{inspection_id}/evidence/upload", response_model=EvidenceOut, status_code=201)
async def add_evidence_upload(
    inspection_id: uuid.UUID,
    photo: UploadFile = File(...),
    caption: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PMU_INSPECTOR, UserRole.ADMIN)),
):
    """
    The field-upload path for inspection-report evidence: the
    inspector attaches a photo (with an optional short caption, e.g.
    "Boys' washroom, ground floor") while filling out their report,
    before calling POST /{id}/submit-report.

    The photo is run through app/services/ai_inspection_analysis.py
    immediately, right here: its theme is detected (from the caption/
    report-text keywords, or from a hosted vision API if one is
    configured -- see app/services/vision_api_client.py), and it's
    scored on whichever quality parameters that theme implies. The
    per-photo results are stored on the InspectionEvidence row itself;
    submit-report later rolls every photo's results up into one
    inspection-level report.
    """
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    if (
        current_user.role == UserRole.PMU_INSPECTOR
        and inspection.inspector_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="This inspection is not assigned to you")

    image_bytes = await photo.read()
    if len(image_bytes) > MAX_EVIDENCE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 12MB)")

    ext = mimetypes.guess_extension(photo.content_type or "") or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    filename = f"{inspection.id}_{uuid.uuid4().hex}{ext}"
    (EVIDENCE_UPLOAD_DIR / filename).write_bytes(image_bytes)
    file_url = f"/static/evidence/{filename}"

    try:
        result = analysis_engine.analyze_photo(
            image_bytes,
            caption=caption,
            context_text=inspection.report_text or "",
            media_type=photo.content_type or "image/jpeg",
        )
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    evidence = InspectionEvidence(
        inspection_id=inspection_id,
        file_url=file_url,
        file_type="image",
        caption=caption,
        theme=result.theme,
        theme_label=result.theme_label,
        theme_confidence=result.confidence,
        parameter_scores=result.scores,
        ai_findings=result.findings,
        quality_flags=result.quality_flags,
        analysis_source=result.source,
        analyzed_at=datetime.utcnow(),
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/{inspection_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(
       inspection_id: uuid.UUID,
       db: Session = Depends(get_db),
       _user: User = Depends(get_current_user),
   ):
       return (
           db.query(InspectionEvidence)
           .filter(InspectionEvidence.inspection_id == inspection_id)
           .order_by(InspectionEvidence.captured_at.desc())
           .all()
       )


@router.delete("/{inspection_id}/evidence/{evidence_id}", status_code=204)
def delete_evidence(
    inspection_id: uuid.UUID,
    evidence_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PMU_INSPECTOR, UserRole.ADMIN)),
):
    """Lets an inspector remove a photo they uploaded by mistake
    before submitting the report. Only available before submission --
    once an inspection is COMPLETED its evidence is part of the
    generated analysis and stays put."""
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    if (
        current_user.role == UserRole.PMU_INSPECTOR
        and inspection.inspector_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="This inspection is not assigned to you")
    if inspection.status == InspectionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot remove evidence from a completed inspection")

    evidence = (
        db.query(InspectionEvidence)
        .filter(InspectionEvidence.id == evidence_id, InspectionEvidence.inspection_id == inspection_id)
        .first()
    )
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    db.delete(evidence)
    db.commit()
    return None


# --- AI analysis report: view / edit / history --------------------
# Every endpoint below is off-limits to pmu_inspector by design -- see
# ANALYSIS_VIEWER_ROLES and InspectionAnalysisReport's docstring.


@router.get("/{inspection_id}/analysis", response_model=AnalysisReportOut)
def get_analysis(
    inspection_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*ANALYSIS_VIEWER_ROLES)),
):
    analysis = (
        db.query(InspectionAnalysisReport)
        .filter(InspectionAnalysisReport.inspection_id == inspection_id)
        .first()
    )
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="No analysis report yet -- the inspection report hasn't been submitted.",
        )
    return analysis


@router.patch("/{inspection_id}/analysis", response_model=AnalysisReportOut)
def update_analysis(
    inspection_id: uuid.UUID,
    payload: AnalysisReportUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ANALYSIS_VIEWER_ROLES)),
):
    analysis = (
        db.query(InspectionAnalysisReport)
        .filter(InspectionAnalysisReport.inspection_id == inspection_id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis report to edit yet")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return analysis

    changes = {}
    if "overall_score" in updates and updates["overall_score"] != analysis.overall_score:
        changes["overall_score"] = {"from": analysis.overall_score, "to": updates["overall_score"]}
        analysis.overall_score = updates["overall_score"]
    if "grade" in updates and updates["grade"] != analysis.grade:
        changes["grade"] = {"from": analysis.grade, "to": updates["grade"]}
        analysis.grade = updates["grade"]
    if "summary" in updates and updates["summary"] != analysis.summary:
        changes["summary"] = {"from": "(previous text)", "to": "(edited)"}
        analysis.summary = updates["summary"]
    if "parameter_scores" in updates:
        new_scores = dict(analysis.parameter_scores or {})
        param_changes = {}
        for param, value in updates["parameter_scores"].items():
            if param not in ANALYSIS_PARAMETERS:
                continue
            old_value = new_scores.get(param)
            if old_value != value:
                param_changes[param] = {"from": old_value, "to": value}
            new_scores[param] = value
        if param_changes:
            changes["parameter_scores"] = param_changes
            analysis.parameter_scores = new_scores

    if changes:
        analysis.is_edited = True
        analysis.last_edited_by_id = current_user.id
        analysis.last_edited_at = datetime.utcnow()
        history = list(analysis.edit_history or [])
        history.append({
            "editor_id": str(current_user.id),
            "editor_name": current_user.full_name,
            "edited_at": analysis.last_edited_at.isoformat(),
            "changes": changes,
        })
        analysis.edit_history = history

    db.commit()
    db.refresh(analysis)
    return analysis


@router.get("/project/{project_id}/analysis-history", response_model=list[AnalysisHistoryEntry])
def project_analysis_history(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*ANALYSIS_VIEWER_ROLES)),
):
    """Every analyzed inspection for a project, oldest first -- the
    trend line the comparison view on the analysis page is built on
    top of."""
    rows = (
        db.query(InspectionAnalysisReport)
        .join(Inspection, InspectionAnalysisReport.inspection_id == Inspection.id)
        .filter(Inspection.project_id == project_id)
        .order_by(Inspection.completed_at.asc())
        .all()
    )
    return [
        AnalysisHistoryEntry(
            inspection_id=row.inspection_id,
            completed_at=row.inspection.completed_at if row.inspection else None,
            overall_score=row.overall_score,
            grade=row.grade,
            is_edited=row.is_edited,
        )
        for row in rows
    ]


@router.get("/analysis/summary")
def analysis_summary(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*ANALYSIS_VIEWER_ROLES)),
):
    """Lightweight {inspection_id: {overall_score, grade, overall_trend}}
    map for every analyzed inspection -- lets the inspections table
    show a score/grade badge per row without an N+1 fetch per
    inspection. Never exposed to pmu_inspector."""
    rows = db.query(InspectionAnalysisReport).all()
    return {
        str(row.inspection_id): {
            "overall_score": row.overall_score,
            "grade": row.grade,
            "overall_trend": row.overall_trend,
            "is_edited": row.is_edited,
        }
        for row in rows
    }
