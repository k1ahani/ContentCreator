"""Job entity and live job events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobStatus, JobType


class JobLogLine(BaseModel):
    """One line of captured output. ``stream`` mirrors the source pipe so the
    console component can colour stderr differently."""

    ts: float
    stream: Literal["stdout", "stderr", "system"] = "stdout"
    text: str


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    type: JobType
    status: JobStatus = JobStatus.QUEUED
    #: 0.0 - 1.0. Handlers that cannot measure progress report None.
    progress: float | None = None
    #: Short Persian sentence describing the current step, shown under the bar.
    stage: str = ""
    provider: str | None = None
    model: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    #: Persian, safe to display. Technical detail goes to the job log.
    error: str | None = None
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = self.finished_at or datetime.now(self.started_at.tzinfo)
        return (end - self.started_at).total_seconds()


class JobCreate(BaseModel):
    type: JobType
    project_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None


class JobEvent(BaseModel):
    """Payload pushed to the browser over SSE.

    One envelope for every kind of update keeps the frontend reducer small:
    ``kind`` decides which fields are meaningful.
    """

    kind: Literal["status", "progress", "log", "done"]
    job_id: str
    status: JobStatus | None = None
    progress: float | None = None
    stage: str | None = None
    line: JobLogLine | None = None
    error: str | None = None
    error_code: str | None = None
    output: dict[str, Any] | None = None
