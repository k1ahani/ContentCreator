"""Response bodies.

Only shapes that are not already a domain model live here. Where a domain model
is exactly what the client needs (Project, Job, SubtitleTrack), routers return
it directly rather than duplicating the definition.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.domain.asset import MediaAsset, MediaProbe
from app.domain.job import Job
from app.domain.subtitle import RetimeReport, SubtitleCue

T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    """A page of items plus the total, so the UI can show counts."""

    items: list[T]
    total: int


class RetimeResponse(BaseModel):
    """The retimed cues plus what the operation actually changed.

    A plain ``ListResponse`` would leave the UI unable to say anything more
    useful than "done": the report is what lets it tell the user that eleven
    cues moved, three overlaps were resolved and nothing ran past the end of
    the video - facts the user needs to decide whether to keep the result.
    """

    items: list[SubtitleCue]
    total: int
    report: RetimeReport


class JobAcceptedResponse(BaseModel):
    """Returned by every endpoint that starts background work.

    Always 202: the caller then follows the job over SSE or by polling.
    """

    job: Job
    message: str = "وظیفه در صف اجرا قرار گرفت."


class ImportedAssetResponse(BaseModel):
    asset: MediaAsset
    probe: MediaProbe | None = None


class DependencyStatus(BaseModel):
    """One external tool's health, as shown on the dashboard."""

    id: str
    label_fa: str
    available: bool
    #: True when the platform cannot work at all without this.
    required: bool
    version: str | None = None
    path: str | None = None
    detail_fa: str | None = None
    hint_fa: str | None = None


class SystemStatusResponse(BaseModel):
    """The dependency doctor's report."""

    ready: bool
    app_version: str
    python_version: str
    platform: str
    dependencies: list[DependencyStatus]
    workspace_path: str
    database_path: str
    active_jobs: int
    queued_jobs: int


class TaskInfo(BaseModel):
    """An AI task as the UI presents it."""

    id: str
    label_fa: str
    description_fa: str
    preferred_tier: str
    max_input_chars: int


class PromptInfo(BaseModel):
    id: str
    name_fa: str
    task: str
    category: str
    description_fa: str
    body: str
    variables: list[str] = Field(default_factory=list)
    is_builtin: bool = True


class AudioPresetInfo(BaseModel):
    id: str
    label_fa: str
    extension: str
    approx_mb_per_hour: float
    description_fa: str
    sample_rate: int | None = None


class RenderQualityInfo(BaseModel):
    id: str
    label_fa: str
    description_fa: str
    crf: int


class MediaCapabilitiesResponse(BaseModel):
    audio_presets: list[AudioPresetInfo]
    render_qualities: list[RenderQualityInfo]
    ffmpeg_available: bool
    ffmpeg_version: str | None = None


class SettingsResponse(BaseModel):
    values: dict[str, Any]
    grouped: dict[str, dict[str, Any]]
    defaults: dict[str, Any]


class OperationResponse(BaseModel):
    """Generic acknowledgement for actions with no meaningful payload."""

    ok: bool = True
    message: str = ""
