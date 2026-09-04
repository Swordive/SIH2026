"""
Random inspection assignment engine.

This is the "random assignment of inspection duties through
AI/automation" piece of the problem statement. It picks which
projects need a fresh inspection and which inspector should get it,
then creates the Inspection rows with ai_assigned=True.

Two entry points:
- run_random_assignment(): called manually (via the API) or by the
  daily scheduler in main.py
- pick_inspector() / pick_projects_needing_inspection(): exposed
  separately so they're easy to unit-test or reuse elsewhere.
"""
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus, InspectionType

# How far back to look before considering a project "already covered".
DEFAULT_LOOKBACK_DAYS = 14
# How far into the future a surprise inspection can be scheduled.
MIN_LEAD_HOURS = 1
MAX_LEAD_HOURS = 72


def pick_inspector(db: Session) -> User | None:
    """
    Pick an active PMU inspector, load-balanced: whoever currently has
    the fewest open (pending/in-progress) inspections is most likely
    to be picked. Ties are broken randomly so it isn't deterministic.
    """
    inspectors = (
        db.query(User)
        .filter(User.role == UserRole.PMU_INSPECTOR, User.is_active.is_(True))
        .all()
    )
    if not inspectors:
        return None

    open_statuses = [InspectionStatus.PENDING, InspectionStatus.IN_PROGRESS]
    workload = {
        inspector.id: db.query(Inspection)
        .filter(
            Inspection.inspector_id == inspector.id,
            Inspection.status.in_(open_statuses),
        )
        .count()
        for inspector in inspectors
    }

    min_load = min(workload.values())
    least_loaded = [i for i in inspectors if workload[i.id] == min_load]
    return random.choice(least_loaded)


def pick_projects_needing_inspection(
    db: Session, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> list[Project]:
    """
    Returns projects that have had no inspection (of any status)
    created within the lookback window -- i.e. projects "due" for a
    fresh check.
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    recently_covered_ids = {
        row.project_id
        for row in db.query(Inspection.project_id)
        .filter(Inspection.created_at >= cutoff)
        .distinct()
    }

    all_projects = db.query(Project).all()
    return [p for p in all_projects if p.id not in recently_covered_ids]


def _build_inspection(db: Session, project: Project) -> Inspection | None:
    inspector = pick_inspector(db)
    if inspector is None:
        return None

    inspection_type = random.choice([InspectionType.SURPRISE, InspectionType.VC_RANDOM])
    lead_hours = random.randint(MIN_LEAD_HOURS, MAX_LEAD_HOURS)

    return Inspection(
        project_id=project.id,
        inspector_id=inspector.id,
        inspection_type=inspection_type,
        status=InspectionStatus.PENDING,
        ai_assigned=True,
        scheduled_at=datetime.utcnow() + timedelta(hours=lead_hours),
    )


def run_random_assignment(
    db: Session,
    max_assignments: int = 5,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[Inspection]:
    """
    Core entry point: picks up to `max_assignments` projects that are
    due for inspection, assigns each a load-balanced inspector, and
    commits the new Inspection rows. Returns the created rows.

    Safe to call with zero eligible projects or zero inspectors --
    just returns an empty list in that case rather than erroring,
    since this may run unattended via the scheduler.
    """
    candidates = pick_projects_needing_inspection(db, lookback_days=lookback_days)
    random.shuffle(candidates)
    selected = candidates[:max_assignments]

    created: list[Inspection] = []
    for project in selected:
        inspection = _build_inspection(db, project)
        if inspection is not None:
            db.add(inspection)
            created.append(inspection)

    if created:
        db.commit()
        for inspection in created:
            db.refresh(inspection)

    return created