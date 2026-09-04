import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.project import EntityType


class ProjectCreate(BaseModel):
    name: str
    entity_type: EntityType = EntityType.PROJECT
    scheme_name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    cctv_feed_url: str | None = None
    incharge_id: uuid.UUID | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    entity_type: EntityType
    scheme_name: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    cctv_feed_url: str | None
    incharge_id: uuid.UUID | None
    created_at: datetime
