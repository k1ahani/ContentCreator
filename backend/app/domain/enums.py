"""Enumerations used across the platform.

All values are lowercase snake_case strings so they can be stored in SQLite,
serialised to JSON and compared in TypeScript without translation. Persian
labels live in the frontend locale file (``frontend/src/locales/fa.ts``) so the
backend stays language-neutral; the one exception is the model-recommendation
rationale, which is authored in Persian in ``app/ai/models.py`` because the
model registry is the single source of truth for model metadata.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """``str`` subclass enum. Python 3.12 has ``enum.StrEnum`` but this keeps
    the repr stable across versions and makes JSON encoding automatic."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# --------------------------------------------------------------------------
# Media assets
# --------------------------------------------------------------------------


class AssetType(StrEnum):
    """Kind of file tracked in ``media_assets``.

    The value also decides which project sub-directory the file lives in; see
    ``AssetType.subdir``.
    """

    VIDEO = "video"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    SUBTITLE = "subtitle"
    VOICE = "voice"
    RENDERED_VIDEO = "rendered_video"

    @property
    def subdir(self) -> str:
        return _ASSET_SUBDIR[self]


_ASSET_SUBDIR: dict[AssetType, str] = {
    AssetType.VIDEO: "source",
    AssetType.AUDIO: "audio",
    AssetType.TRANSCRIPT: "transcript",
    AssetType.SUBTITLE: "subtitles",
    AssetType.VOICE: "voice",
    AssetType.RENDERED_VIDEO: "rendered",
}


# --------------------------------------------------------------------------
# Text documents
# --------------------------------------------------------------------------


class DocumentType(StrEnum):
    """Role a text document plays in the pipeline.

    ``TRANSCRIPT_RAW`` is written by the speech-recognition engine and is never
    edited in place - refinement, editing and translation each produce a new
    document, which is what makes "compare before applying" possible.
    """

    TRANSCRIPT_RAW = "transcript_raw"
    TRANSCRIPT_REFINED = "transcript_refined"
    EDITED = "edited"
    TRANSLATION = "translation"
    SPEECH_SCRIPT = "speech_script"
    NOTE = "note"


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


class JobType(StrEnum):
    """Background operations. One value per registered handler in
    ``app/jobs/handlers/``; the registry asserts the mapping is complete at
    startup, so adding a value without a handler fails fast."""

    AUDIO_EXTRACT = "audio_extract"
    TRANSCRIBE = "transcribe"
    TEXT_TASK = "text_task"
    SUBTITLE_GENERATE = "subtitle_generate"
    SUBTITLE_SYNC = "subtitle_sync"
    SUBTITLE_RENDER = "subtitle_render"
    TTS_SYNTHESIZE = "tts_synthesize"


# --------------------------------------------------------------------------
# AI layer
# --------------------------------------------------------------------------


class AITaskType(StrEnum):
    """Kinds of work an LLM provider can be asked to do.

    Note the deliberate boundary: raw speech-to-text is *not* here, because no
    LLM provider accepts audio through a CLI. Audio becomes timed text in
    ``app/transcription/``; ``TRANSCRIPTION_REFINEMENT`` is the LLM stage that
    then fixes punctuation, spelling and Persian normalisation. Likewise speech
    synthesis lives in ``app/tts/`` with its own provider interface and voice
    registry. See docs/AI_SYSTEM.md.
    """

    TRANSCRIPTION_REFINEMENT = "transcription_refinement"
    TEXT_EDITING = "text_editing"
    TRANSLATION = "translation"
    TEXT_ANALYSIS = "text_analysis"
    SUBTITLE_PROCESSING = "subtitle_processing"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


class ProviderCapability(StrEnum):
    """Optional features a provider may advertise."""

    STREAMING = "streaming"
    SYSTEM_PROMPT = "system_prompt"
    FILE_INPUT = "file_input"
    MODEL_SELECTION = "model_selection"


class ModelTier(StrEnum):
    """Coarse capability/cost banding used by the recommendation engine."""

    FAST = "fast"
    BALANCED = "balanced"
    POWERFUL = "powerful"


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------


class Language(StrEnum):
    """Supported content languages.

    Adding a language means adding a member here, an entry in
    ``LANGUAGE_METADATA`` below, and a label in the frontend locale file.
    Nothing else in the pipeline hardcodes a language.
    """

    PERSIAN = "fa"
    ENGLISH = "en"

    @property
    def is_rtl(self) -> bool:
        return LANGUAGE_METADATA[self]["rtl"]

    @property
    def english_name(self) -> str:
        return LANGUAGE_METADATA[self]["english_name"]

    @property
    def native_name(self) -> str:
        return LANGUAGE_METADATA[self]["native_name"]


LANGUAGE_METADATA: dict[Language, dict] = {
    Language.PERSIAN: {
        "english_name": "Persian",
        "native_name": "فارسی",
        "rtl": True,
        # ISO-639-1 code understood by the Whisper family.
        "asr_code": "fa",
    },
    Language.ENGLISH: {
        "english_name": "English",
        "native_name": "English",
        "rtl": False,
        "asr_code": "en",
    },
}


# --------------------------------------------------------------------------
# Subtitles
# --------------------------------------------------------------------------


class SubtitleFormat(StrEnum):
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"


class SubtitleAlignment(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class SubtitlePosition(StrEnum):
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class SubtitleSegmentationMode(StrEnum):
    """How generated cue boundaries are chosen from a transcript.

    Controls *only* subtitle generation (``app/media/subtitles/segmentation.py``)
    - never touches manual timeline edits, which are always exact regardless
    of what mode originally produced a cue.
    """

    #: One cue per complete sentence; never split mid-sentence.
    SENTENCE = "sentence"
    #: The original behaviour: sentence -> clause -> word-wrap cascade bounded
    #: by a character-length target. The right default for most content.
    AUTOMATIC = "automatic"
    #: Fixed word count per cue, few words (fast-paced, social-media style).
    SHORT = "short"
    #: Fixed word count per cue, a comfortable reading amount.
    NORMAL = "normal"
    #: Fixed word count per cue, user-specified exactly (see
    #: ``words_per_cue`` - as low as one word per cue, e.g. karaoke-style).
    CUSTOM = "custom"


class SubtitleRetimeMode(StrEnum):
    """How a *whole track* is retimed in one batch operation.

    These are the manual counterpart to audio-based synchronisation
    (``JobType.SUBTITLE_SYNC``): pure arithmetic on the existing cue times, no
    media analysis, applied to every cue as a group so the user never has to
    drag fifty cues one at a time. See ``app/media/subtitles/sync.py``.
    """

    #: Move every cue by a signed offset. Fixes "the whole track is 1.4s late".
    SHIFT = "shift"
    #: Multiply every timing by a factor around an anchor point. Fixes drift
    #: that grows through the file (a frame-rate mismatch, 25 vs 23.976 fps).
    SCALE = "scale"
    #: Recompute each cue's duration from its own text at a target reading
    #: speed and repack the track sequentially - "subtitle display speed".
    READING_SPEED = "reading_speed"
    #: Stretch or compress the track so its last cue ends at a target time,
    #: keeping the first cue's start where it is.
    STRETCH = "stretch"


class SubtitleTimingSource(StrEnum):
    """Where a track's current cue timings actually came from.

    Reported by every job that writes timings so the UI can tell the user how
    much to trust them - an honest distinction the platform has made since
    subtitle generation shipped (see docs/SUBTITLE_SYSTEM.md).
    """

    #: Measured by the speech-recognition engine during transcription.
    ASR_SEGMENTS = "asr_segments"
    #: Distributed by character count over a known duration. Approximate.
    ESTIMATED = "estimated"
    #: Existing cue text matched against words the ASR engine measured in this
    #: project's own audio. The strongest signal available after the fact.
    AUDIO_ALIGNED = "audio_aligned"
    #: Cue text could not be matched to the audio (a translated track, say), so
    #: cues were distributed across the *speech regions* the engine found.
    #: Better than ESTIMATED - it skips silence - but still approximate.
    SPEECH_DISTRIBUTED = "speech_distributed"
    #: Produced by a manual batch retime or by hand in the timeline editor.
    MANUAL = "manual"


# --------------------------------------------------------------------------
# Text to speech
# --------------------------------------------------------------------------


class VoiceGender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class VoiceAge(StrEnum):
    YOUNG = "young"
    ADULT = "adult"
    MATURE = "mature"
    UNKNOWN = "unknown"


class SpeakingStyle(StrEnum):
    FRIENDLY = "friendly"
    CASUAL = "casual"
    PROFESSIONAL = "professional"
    FORMAL = "formal"
    ENERGETIC = "energetic"
    CALM = "calm"
    NEUTRAL = "neutral"


class SpeechSegmentKind(StrEnum):
    """A speech script is an ordered list of these. Pauses are structured
    elements rather than markers inside the text, so the editor can drag them
    around and the synthesiser can honour them exactly."""

    TEXT = "text"
    PAUSE = "pause"
