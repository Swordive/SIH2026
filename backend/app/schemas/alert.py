import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AlertCreate(BaseModel):
    project_id: uuid.UUID
    message: str
    severity: str = "medium"


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    inspection_id: uuid.UUID | None
    kind: str | None
    message: str
    severity: str
    resolved: bool
    created_at: datetime
    