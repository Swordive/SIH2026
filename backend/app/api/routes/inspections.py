import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus, InspectionEvidence
from app.schemas.inspection import (
    InspectionCreate,
    InspectionOut,
    InspectionReportSubmit,
    InspectionAssign,
)
from app.services.assignment import run_random_assignment, build_unassigned_inspection

router = APIRouter(prefix="/api/inspections", tags=["inspections"])


@router.post("/auto-assign", response_model=list[InspectionOut])
def auto_assign_inspections(
    max_assignments: int = 5,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
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
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
):
    """
    Adds a single unassigned inspection (random type) for a specific
    project, on demand. Unlike /auto-assign, this bypasses the
    "already covered recently" filter -- use this when you want to
    add another inspection for a project that already has one.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    inspection = build_unassigned_inspection(project)
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.post("", response_model=InspectionOut, status_code=201)
def create_inspection(
    payload: InspectionCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
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


@router.patch("/{inspection_id}/assign", response_model=InspectionOut)
def assign_inspection(
    inspection_id: uuid.UUID,
    payload: InspectionAssign,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
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
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
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
