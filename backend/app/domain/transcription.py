"""Transcription domain model.

Segments carry real timings produced by the speech-recognition engine. Those
timings are what make the subtitle timeline meaningful - they are measured from
the audio, not guessed from character counts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import Language


class TranscriptWord(BaseModel):
    """A single word with its own timing, when the engine provides them."""

    start: float
    end: float
    text: str
    probability: float | None = None


class TranscriptSegment(BaseModel):
    """A timed chunk of speech as returned by the engine."""

    index: int = 0
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    words: list[TranscriptWord] = Field(default_factory=list)
    #: Mean log-probability reported by the model, when available. Used only to
    #: flag low-confidence passages in the UI, never to drop text.
    confidence: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class TranscriptionResult(BaseModel):
    """Full output of one transcription run."""

    text: str = ""
    language: Language = Language.PERSIAN
    #: Language the engine detected, which may differ from the requested one.
    detected_language: str | None = None
    language_probability: float | None = None
    duration_seconds: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)
    engine: str = ""
    model: str = ""
    processing_seconds: float = 0.0

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class TranscriptionOptions(BaseModel):
    """Knobs exposed to the user for one transcription run."""

    language: Language = Language.PERSIAN
    #: Engine model size. Larger is slower and more accurate.
    model_size: str = "small"
    #: Let the engine detect the language instead of forcing one.
    auto_detect_language: bool = False
    #: Drop segments the engine marks as silence. Improves subtitle timing.
    vad_filter: bool = True
    #: Optional domain hint - names, jargon - that biases decoding.
    initial_prompt: str | None = None
