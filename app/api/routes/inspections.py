import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.inspection import Inspection, InspectionStatus
from app.schemas.inspection import InspectionCreate, InspectionOut, InspectionReportSubmit
from app.services.assignment import run_random_assignment


router = APIRouter(prefix="/api/inspections", tags=["inspections"])

@router.post("/auto-assign", response_model=list[InspectionOut])
def auto_assign_inspections(
    max_assignments: int = 5,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
):
    """
    Runs the random assignment engine on demand: picks projects due
    for inspection and load-balances them across active inspectors.
    The same engine also runs automatically once a day (see
    app/main.py's scheduler) -- this endpoint is for manual triggers
    and demos.
    """
    return run_random_assignment(db, max_assignments=max_assignments)


@router.post("", response_model=InspectionOut, status_code=201)
def create_inspection(
    payload: InspectionCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL)),
):
    """
    Manual creation for now. The AI random-assignment engine (next
    module) will call this same model layer to auto-generate
    inspections and pick an inspector.
    """
    inspection = Inspection(**payload.model_dump())
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.get("", response_model=list[InspectionOut])
def list_inspections(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Inspection).order_by(Inspection.created_at.desc()).all()


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

    inspection.report_text = payload.report_text
    inspection.report_latitude = payload.report_latitude
    inspection.report_longitude = payload.report_longitude
    inspection.status = InspectionStatus.COMPLETED
    inspection.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(inspection)
    return inspection
