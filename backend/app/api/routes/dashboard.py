from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus
from app.schemas.dashboard import DashboardStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def get_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inspection_query = db.query(Inspection)

    # PMU inspectors only get to see their own numbers, not org-wide ones.
    if user.role == UserRole.PMU_INSPECTOR:
        inspection_query = inspection_query.filter(Inspection.inspector_id == user.id)

    status_counts = dict(
        inspection_query.with_entities(Inspection.status, func.count(Inspection.id))
        .group_by(Inspection.status)
        .all()
    )

    if user.role == UserRole.PMU_INSPECTOR:
        total_projects = (
            db.query(Project.id)
            .join(Inspection, Inspection.project_id == Project.id)
            .filter(Inspection.inspector_id == user.id)
            .distinct()
            .count()
        )
        active_users = 1
    else:
        total_projects = db.query(Project).count()
        active_users = db.query(User).filter(User.is_active == True).count()

    # inspection_query is already scoped to "this user's own inspections"
    # for a PMU inspector (see above) and "every inspection" otherwise --
    # the feed lives on the Inspection itself now, so no separate Project
    # join is needed either way.
    inspections_with_live_feed = inspection_query.filter(
        Inspection.cctv_feed_url.isnot(None)
    ).count()

    return DashboardStats(
        total_projects=total_projects,
        total_inspections=inspection_query.count(),
        pending_inspections=status_counts.get(InspectionStatus.PENDING, 0),
        in_progress_inspections=status_counts.get(InspectionStatus.IN_PROGRESS, 0),
        completed_inspections=status_counts.get(InspectionStatus.COMPLETED, 0),
        missed_inspections=status_counts.get(InspectionStatus.MISSED, 0),
        active_users=active_users,
        inspections_with_live_feed=inspections_with_live_feed,
    )
