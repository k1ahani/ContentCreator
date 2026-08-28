"""Subtitle domain model.

A subtitle track is an ordered list of cues with float-second timings, never a
single blob of text. Serialisation to SRT/VTT/ASS happens at the edge in
``app/media/subtitles/``; the timeline editor, the renderer and the database
all operate on these structures.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    Language,
    SubtitleAlignment,
    SubtitlePosition,
)


class SubtitleStyle(BaseModel):
    """Appearance of a subtitle track.

    Maps onto an ASS style block at render time (see
    ``app/media/subtitles/style.py``) and onto CSS in the live preview. Keeping
    one model for both is what makes the preview trustworthy.
    """

    font_family: str = "Vazirmatn"
    font_size: int = Field(default=28, ge=8, le=200)
    #: ASS supports bold as a flag; the UI exposes it as a weight.
    bold: bool = False
    italic: bool = False
    #: ``#RRGGBB``.
    text_color: str = "#FFFFFF"
    background_color: str = "#000000"
    #: 0.0 transparent - 1.0 opaque.
    background_opacity: float = Field(default=0.65, ge=0.0, le=1.0)
    outline_color: str = "#000000"
    outline_width: float = Field(default=2.0, ge=0.0, le=20.0)
    shadow_depth: float = Field(default=0.0, ge=0.0, le=20.0)
    position: SubtitlePosition = SubtitlePosition.BOTTOM
    alignment: SubtitleAlignment = SubtitleAlignment.CENTER
    margin_vertical: int = Field(default=40, ge=0, le=1000)
    margin_horizontal: int = Field(default=60, ge=0, le=1000)

    @field_validator("text_color", "background_color", "outline_color")
    @classmethod
    def _validate_hex(cls, value: str) -> str:
        text = value.strip().upper()
        if not text.startswith("#"):
            text = f"#{text}"
        if len(text) != 7 or any(c not in "0123456789ABCDEF" for c in text[1:]):
            raise ValueError(f"expected #RRGGBB colour, got {value!r}")
        return text


class SubtitleCue(BaseModel):
    """A single timed caption."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    track_id: str
    #: Position in the track, 0-based. Kept explicit so reordering after a
    #: split/merge is a single UPDATE rather than a re-sort by time.
    index: int = 0
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    #: Per-cue overrides on top of the track style. Empty means "inherit".
    style_overrides: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_order(self) -> "SubtitleCue":
        if self.end <= self.start:
            raise ValueError("subtitle end must be greater than start")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def characters_per_second(self) -> float:
        """Readability metric. Above ~21 CPS is generally too fast to read."""
        return len(self.text) / self.duration if self.duration > 0 else 0.0


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str = ""
    language: Language = Language.PERSIAN
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    #: Document the cues were generated from, if any.
    source_document_id: str | None = None
    created_at: datetime
    updated_at: datetime
    cues: list[SubtitleCue] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return max((cue.end for cue in self.cues), default=0.0)


class CueCreate(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    index: int | None = None


class CueUpdate(BaseModel):
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = Field(default=None, ge=0.0)
    text: str | None = None
    style_overrides: dict[str, Any] | None = None


class TrackCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    language: Language = Language.PERSIAN
    style: SubtitleStyle | None = None
    source_document_id: str | None = None
