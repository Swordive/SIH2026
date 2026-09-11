import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_roles, get_current_user
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.inspection import Inspection, InspectionEvidence
from app.models.alert import Alert
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Clear out dependent rows first (evidence -> inspections, and
    # alerts) since Inspection.project_id and Alert.project_id are
    # both required FKs -- otherwise Postgres would reject the delete
    # with a foreign-key violation. Alerts are easy to miss here
    # because they can exist even without any inspections (e.g. one
    # posted directly by the AI/CCTV system), so they're cleared
    # independently of the inspection cleanup below.
    inspection_ids = [
        row.id for row in db.query(Inspection.id).filter(Inspection.project_id == project_id)
    ]
    if inspection_ids:
        db.query(InspectionEvidence).filter(
            InspectionEvidence.inspection_id.in_(inspection_ids)
        ).delete(synchronize_session=False)
        db.query(Inspection).filter(Inspection.project_id == project_id).delete(
            synchronize_session=False
        )

    db.query(Alert).filter(Alert.project_id == project_id).delete(synchronize_session=False)

    db.delete(project)
    db.commit()
    return None
