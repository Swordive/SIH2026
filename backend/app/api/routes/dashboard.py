from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus
from app.schemas.dashboard import DashboardStats
from app.models.alert import Alert
from app.services.geofence import GEOFENCE_RADIUS_METERS

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

    # Live feed lives on the INSPECTION only (a project itself has no
    # CCTV feed field) -- see Inspection.cctv_feed_url.
    inspections_with_live_feed = inspection_query.filter(
        Inspection.cctv_feed_url.isnot(None)
    ).count()

    unresolved_alerts = db.query(Alert).filter(Alert.resolved == False).count()

    # Scoped the same way as everything else here: a PMU inspector's
    # dashboard only counts flags from their own check-ins. Any of the
    # three AI checks -- face detection, geofencing, duplicate-photo
    # detection -- can flag a check-in.
    flagged_attendance_checks = inspection_query.filter(
        or_(
            Inspection.attendance_face_verified == False,
            Inspection.attendance_distance_meters > GEOFENCE_RADIUS_METERS,
            Inspection.attendance_duplicate_detected == True,
        )
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
        unresolved_alerts=unresolved_alerts,
        flagged_attendance_checks=flagged_attendance_checks,
    )