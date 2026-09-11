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
from app.models.inspection import Inspection, InspectionStatus, InspectionType, InspectionEvidence
from app.schemas.inspection import (
    InspectionCreate,
    InspectionOut,
    InspectionReportSubmit,
    InspectionAssign,
    InspectionUpdate,
    EvidenceCreate,
    EvidenceOut,
    CheckinOut,
)
from app.services.assignment import run_random_assignment
from app.services.ai_vision import detect_faces, InvalidImageError
from app.services.geofence import distance_meters, GEOFENCE_RADIUS_METERS
from app.services.dedupe import compute_phash, is_duplicate

router = APIRouter(prefix="/api/inspections", tags=["inspections"])

# Keeps a misbehaving/huge upload from tying up a worker decoding it.
MAX_CHECKIN_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

# Where check-in selfies get saved so an attendance alert can later be
# reviewed against the actual photo (see checkin() below) instead of
# only the face_count number. Served back out at /static/checkins/...
# by the StaticFiles mount in main.py -- created here (module import
# time) so it exists before that mount is set up.
CHECKIN_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "checkins"
CHECKIN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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
    return inspection


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
