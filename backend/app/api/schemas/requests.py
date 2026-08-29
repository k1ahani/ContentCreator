"""Request bodies.

Kept separate from the domain models on purpose: a domain model describes what
the platform stores, a request schema describes what a client may send. Letting
a client post a full domain model would let it set ids, timestamps and derived
counters.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.enums import (
    AITaskType,
    AssetType,
    DocumentType,
    Language,
    ProjectStatus,
    SpeakingStyle,
    SubtitleFormat,
    SubtitleSegmentationMode,
)
from app.domain.subtitle import SubtitleStyle


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus | None = None


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------


class ImportAssetRequest(BaseModel):
    """Register a file the user picked from their own filesystem.

    ``copy_into_project`` defaults to false: a 4 GB video does not need to be
    duplicated to be worked on, and the platform never writes to the source.
    """

    path: str = Field(min_length=1, max_length=4096)
    type: AssetType = AssetType.VIDEO
    copy_into_project: bool = False


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


class CreateDocumentRequest(BaseModel):
    type: DocumentType = DocumentType.NOTE
    title: str = Field(default="", max_length=200)
    content: str = ""
    language: Language = Language.PERSIAN
    source_document_id: str | None = None


class UpdateDocumentRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    language: Language | None = None


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


class ExtractAudioRequest(BaseModel):
    asset_id: str
    preset: Literal["opus", "mp3", "wav"] | None = None


class TranscribeRequest(BaseModel):
    asset_id: str
    language: Language | None = None
    model_size: str | None = None
    auto_detect_language: bool = False
    vad_filter: bool | None = None
    #: Run the LLM refinement pass afterwards.
    refine: bool | None = None
    #: Model for the refinement pass. None means "use the recommendation".
    ai_model: str | None = None
    initial_prompt: str | None = Field(default=None, max_length=2000)


class TextTaskRequest(BaseModel):
    task: AITaskType
    document_id: str | None = None
    content: str | None = None
    prompt: str | None = Field(default=None, max_length=8000)
    variables: dict[str, str] | None = None
    source_language: Language | None = None
    target_language: Language | None = None
    provider: str | None = None
    model: str | None = None
    #: False returns the result without creating a document - used by the
    #: editor so a rejected suggestion leaves nothing behind.
    save: bool = True


class GenerateSubtitleRequest(BaseModel):
    document_id: str | None = None
    text: str | None = None
    #: Measured timings from a transcription run.
    segments: list[dict[str, Any]] | None = None
    #: A transcribe job to lift segments from.
    job_id: str | None = None
    track_id: str | None = None
    language: Language | None = None
    name: str | None = Field(default=None, max_length=200)
    duration_seconds: float | None = Field(default=None, ge=0)
    max_chars: int | None = Field(default=None, ge=10, le=400)
    #: How cue boundaries are chosen. Defaults to AUTOMATIC (the original
    #: character-length cascade) when omitted - see
    #: app/media/subtitles/segmentation.py.
    segmentation_mode: SubtitleSegmentationMode | None = None
    #: Exact words per cue, used only when segmentation_mode is CUSTOM.
    words_per_cue: int | None = Field(default=None, ge=1, le=20)


class RenderSubtitleRequest(BaseModel):
    track_id: str
    asset_id: str
    quality: Literal["high", "balanced", "fast"] | None = None
    export_subtitle: bool = True


class SpeechSegmentInput(BaseModel):
    kind: Literal["text", "pause"] = "text"
    id: str | None = None
    text: str | None = None
    seconds: float | None = Field(default=None, ge=0.05, le=60.0)


class SynthesizeSpeechRequest(BaseModel):
    segments: list[SpeechSegmentInput] | None = None
    document_id: str | None = None
    text: str | None = None
    voice_id: str | None = None
    language: Language | None = None
    style: SpeakingStyle | None = None
    rate: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch: float | None = Field(default=None, ge=-12.0, le=12.0)
    output_format: Literal["mp3", "wav"] | None = None
    name: str | None = Field(default=None, max_length=120)


# --------------------------------------------------------------------------
# Subtitles
# --------------------------------------------------------------------------


class CreateTrackRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    language: Language = Language.PERSIAN
    style: SubtitleStyle | None = None
    source_document_id: str | None = None


class UpdateTrackRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    language: Language | None = None
    style: SubtitleStyle | None = None


class CreateCueRequest(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    index: int | None = Field(default=None, ge=0)


class UpdateCueRequest(BaseModel):
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = Field(default=None, ge=0.0)
    text: str | None = None
    style_overrides: dict[str, Any] | None = None


class SplitCueRequest(BaseModel):
    """Split a cue at ``at_seconds``, an absolute position on the timeline."""

    at_seconds: float = Field(gt=0.0)
    #: Optional explicit texts for the two halves. When omitted the text is
    #: split proportionally at the nearest word boundary.
    first_text: str | None = None
    second_text: str | None = None


class MergeCuesRequest(BaseModel):
    """Merge a cue with the one after it."""

    separator: str = " "


class ExportSubtitleRequest(BaseModel):
    format: SubtitleFormat = SubtitleFormat.SRT


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


class UpdateSettingsRequest(BaseModel):
    values: dict[str, Any] = Field(min_length=1)


class ResetSettingsRequest(BaseModel):
    key: str | None = None
