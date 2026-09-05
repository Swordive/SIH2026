import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Enum, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"                      # Department (MoSJE) super-admin
    DEPARTMENT_OFFICIAL = "department_official"  # views dashboards
    PMU_INSPECTOR = "pmu_inspector"      # performs inspections
    PROJECT_INCHARGE = "project_incharge"  # runs a project/institute/NGO


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.PMU_INSPECTOR)
    organization = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # An inspector can have many inspections assigned to them
    inspections = relationship(
        "Inspection", back_populates="inspector", foreign_keys="Inspection.inspector_id"
    )
    # A project incharge owns/runs one or more projects
    projects = relationship("Project", back_populates="incharge")