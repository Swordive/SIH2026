import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_roles
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.alert import Alert
from app.schemas.alert import AlertCreate, AlertOut

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.post("", response_model=AlertOut, status_code=201)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    """
    Called by the AI/CCTV system when it detects an anomaly. Deliberately
    has NO login requirement -- the AI/CCTV service isn't a logged-in
    user, it's a separate system posting data in. A production version
    would need its own API-key auth; left open for the hackathon build.
    """
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    alert = Alert(
        project_id=payload.project_id,
        message=payload.message,
        severity=payload.severity,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(
    unresolved_only: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    query = db.query(Alert)
    if unresolved_only:
        query = query.filter(Alert.resolved == False)
    return query.order_by(Alert.created_at.desc()).all()


@router.patch("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DEPARTMENT_OFFICIAL, UserRole.PROJECT_INCHARGE)),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved = True
    db.commit()
    db.refresh(alert)
    return alert
    