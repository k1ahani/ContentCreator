"""Media asset entity.

Binary data never enters SQLite. A row records *where* a file is plus the
metadata needed to display it, and the file itself lives under
``storage/projects/<project-id>/<subdir>/``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AssetType


class MediaAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    type: AssetType
    original_filename: str
    #: Absolute path on disk. Files inside the workspace are also exposed
    #: through /api/files/{asset_id} for the browser to stream.
    path: str
    size_bytes: int = 0
    format: str = ""
    duration_seconds: float | None = None
    #: Free-form probe output (codec, resolution, sample rate, ...).
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @property
    def exists_on_disk(self) -> bool:
        from pathlib import Path

        return Path(self.path).is_file()


class MediaProbe(BaseModel):
    """Normalised subset of ``ffprobe`` output."""

    duration_seconds: float | None = None
    format_name: str = ""
    size_bytes: int = 0
    bit_rate: int | None = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
