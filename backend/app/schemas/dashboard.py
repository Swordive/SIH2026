from pydantic import BaseModel


class DashboardStats(BaseModel):
       total_projects: int
       total_inspections: int
       pending_inspections: int
       in_progress_inspections: int
       completed_inspections: int
       missed_inspections: int
       active_users: int
       projects_with_live_feed: int