from pydantic import BaseModel


class DashboardStats(BaseModel):
       total_projects: int
       total_inspections: int
       pending_inspections: int
       in_progress_inspections: int
       completed_inspections: int
       missed_inspections: int
       active_users: int
       inspections_with_live_feed: int
       unresolved_alerts: int
       # AI attendance face-checks that came back NOT verified (0 or
       # 2+ faces) -- see POST /{id}/attendance/face-check.
       flagged_attendance_checks: int
