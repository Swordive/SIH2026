"""
Random inspection assignment engine.

This is the "random assignment of inspection duties through
AI/automation" piece of the problem statement -- scoped as an
AI-assist, not a fully autonomous decision: the engine picks a
project and randomizes the inspection TYPE, but leaves WHO performs
it and WHEN to a human admin/department official. That assignment
step happens via the separate PATCH /api/inspections/{id}/assign
endpoint (see routes/inspections.py).

Entry point:
- run_random_assignment(): called manually (via the API, once per
  click of "Run random assignment") or by the daily scheduler in
  main.py. Creates unassigned Inspection rows (inspector_id=None,
  scheduled_at=None) for randomly chosen projects, each with a
  randomly chosen inspection type. Not limited to one inspection per
  project -- can be run as many times as needed, including for
  projects that already have pending inspections.
"""
import random

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.inspection import Inspection, InspectionStatus, InspectionType


def build_unassigned_inspection(project: Project) -> Inspection:
    """
    Builds an unassigned inspection for the given project: only the
    project and a randomly chosen inspection type are set. inspector_id
    and scheduled_at are left None -- an admin/department official
    fills those in afterward via PATCH /api/inspections/{id}/assign.

    Public (no leading underscore) because it's also used by the
    "manually add another inspection for this project" endpoint.
    """
    inspection_type = random.choice([InspectionType.SURPRISE, InspectionType.VC_RANDOM])

    return Inspection(
        project_id=project.id,
        inspector_id=None,
        inspection_type=inspection_type,
        status=InspectionStatus.PENDING,
        ai_assigned=True,
        scheduled_at=None,
    )


def run_random_assignment(db: Session, max_assignments: int = 5) -> list[Inspection]:
    """
    Core entry point: randomly picks up to `max_assignments` projects
    (from ALL projects, regardless of whether they already have
    pending/recent inspections) and creates unassigned Inspection rows
    for them (random type, no inspector/date yet). Returns the created
    rows. An admin/department official then assigns each one to a
    specific inspector and date/time.

    Deliberately not filtered by "already covered recently" -- this
    can be clicked repeatedly to keep generating new inspections,
    including multiple for the same project.

    Safe to call with zero projects -- just returns an empty list
    rather than erroring.
    """
    all_projects = db.query(Project).all()
    if not all_projects:
        return []

    random.shuffle(all_projects)
    selected = all_projects[:max_assignments]

    created: list[Inspection] = [build_unassigned_inspection(project) for project in selected]
    db.add_all(created)

    if created:
        db.commit()
        for inspection in created:
            db.refresh(inspection)

    return created
