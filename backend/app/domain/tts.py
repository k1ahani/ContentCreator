"""Text-to-speech domain model.

A *speech script* is an ordered list of segments. Pauses are first-class
segments rather than markers embedded in prose, which means the editor can
reorder them, the synthesiser can honour them exactly, and a future provider
that supports SSML can render them natively without re-parsing text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import (
    Language,
    SpeakingStyle,
    SpeechSegmentKind,
    VoiceAge,
    VoiceGender,
)


class TextSegment(BaseModel):
    kind: Literal[SpeechSegmentKind.TEXT] = SpeechSegmentKind.TEXT
    id: str
    text: str = ""


class PauseSegment(BaseModel):
    kind: Literal[SpeechSegmentKind.PAUSE] = SpeechSegmentKind.PAUSE
    id: str
    #: Silence duration in seconds.
    seconds: float = Field(default=1.0, ge=0.05, le=60.0)


SpeechSegment = TextSegment | PauseSegment


class VoiceSpec(BaseModel):
    """A voice as advertised by a TTS provider."""

    id: str
    provider: str
    #: Human-readable name shown in the selector.
    name: str
    language: Language
    #: Full BCP-47 tag the voice actually speaks, e.g. ``en-GB`` or ``fa-IR``.
    #: ``language`` is the platform's coarse enum and cannot express accent;
    #: with dozens of English voices on offer the accent is the thing a user is
    #: actually choosing between, so it is carried separately rather than
    #: buried inside the display name.
    locale: str = ""
    gender: VoiceGender = VoiceGender.UNKNOWN
    age: VoiceAge = VoiceAge.UNKNOWN
    #: Styles this voice can be asked to use. Providers that do not support
    #: styles advertise ``[NEUTRAL]``.
    styles: list[SpeakingStyle] = Field(default_factory=lambda: [SpeakingStyle.NEUTRAL])
    supports_pitch: bool = False
    supports_rate: bool = True
    description: str = ""
    #: A sample the provider already hosts, when it publishes one. Providers
    #: without hosted samples leave this empty and the platform synthesises a
    #: preview on demand instead - see
    #: ``GET /api/ai/tts/voices/{voice_id}/preview``.
    preview_url: str | None = None


class SpeechOptions(BaseModel):
    """Synthesis parameters chosen by the user."""

    voice_id: str
    language: Language = Language.PERSIAN
    style: SpeakingStyle = SpeakingStyle.NEUTRAL
    #: 1.0 is the voice's natural rate. Providers clamp to their own range.
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    #: Semitone offset. Ignored by providers without pitch support.
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    output_format: Literal["mp3", "wav"] = "mp3"


class SpeechScript(BaseModel):
    """Full input to a synthesis job."""

    segments: list[SpeechSegment] = Field(default_factory=list)
    options: SpeechOptions

    @model_validator(mode="after")
    def _require_speech(self) -> "SpeechScript":
        has_text = any(
            seg.kind == SpeechSegmentKind.TEXT and seg.text.strip()
            for seg in self.segments
        )
        if not has_text:
            raise ValueError("speech script must contain at least one non-empty text segment")
        return self

    @property
    def plain_text(self) -> str:
        """Concatenated prose, used for previews and character counting."""
        return " ".join(
            seg.text.strip()
            for seg in self.segments
            if seg.kind == SpeechSegmentKind.TEXT and seg.text.strip()
        )

    @property
    def total_pause_seconds(self) -> float:
        return sum(
            seg.seconds for seg in self.segments if seg.kind == SpeechSegmentKind.PAUSE
        )
