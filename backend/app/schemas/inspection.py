import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.inspection import InspectionStatus, InspectionType


class InspectionCreate(BaseModel):
    project_id: uuid.UUID
    inspection_type: InspectionType = InspectionType.SURPRISE
    scheduled_at: datetime | None = None


class InspectionReportSubmit(BaseModel):
    report_text: str
    report_latitude: float
    report_longitude: float


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    inspector_id: uuid.UUID | None
    inspection_type: InspectionType
    status: InspectionStatus
    ai_assigned: bool
    scheduled_at: datetime | None
    completed_at: datetime | None
    report_latitude: float | None
    report_longitude: float | None
    report_text: str | None
    created_at: datetime
