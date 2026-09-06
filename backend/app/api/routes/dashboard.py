from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus
from app.schemas.dashboard import DashboardStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def get_dashboard(
  db: Session = Depends(get_db),
  _user: User = Depends(get_current_user),
   ):
     status_counts = dict(
           db.query(Inspection.status, func.count(Inspection.id))
           .group_by(Inspection.status)
           .all()
       )

     return DashboardStats(
           total_projects=db.query(Project).count(),
           total_inspections=db.query(Inspection).count(),
           pending_inspections=status_counts.get(InspectionStatus.PENDING, 0),
           in_progress_inspections=status_counts.get(InspectionStatus.IN_PROGRESS, 0),
           completed_inspections=status_counts.get(InspectionStatus.COMPLETED, 0),
           missed_inspections=status_counts.get(InspectionStatus.MISSED, 0),
           active_users=db.query(User).filter(User.is_active == True).count(),
           projects_with_live_feed=db.query(Project)
           .filter(Project.cctv_feed_url.isnot(None))
           .count(),
       )

