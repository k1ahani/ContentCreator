"""Project entity."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProjectStatus


class Project(BaseModel):
    """A unit of work. Everything else in the platform hangs off a project."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime
    updated_at: datetime

    #: Denormalised counters, filled by the service layer for list views.
    asset_count: int = 0
    document_count: int = 0
    active_job_count: int = 0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus | None = None
