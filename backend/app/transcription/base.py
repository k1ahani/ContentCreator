"""Speech-recognition provider interface.

**Why this is a separate layer from ``app/ai/``.** No LLM CLI accepts audio: the
Claude CLI takes text on stdin and returns text. Turning speech into *timed*
text is a fundamentally different capability, and the subtitle timeline depends
on real timestamps measured from the waveform - something a language model
cannot invent. So transcription gets its own provider interface, and the LLM
participates in the pipeline afterwards as a refinement stage
(``AITaskType.TRANSCRIPTION_REFINEMENT``), doing what it is genuinely good at:
punctuation, spelling and Persian normalisation.

The two layers are deliberately symmetric - registry, provider interface,
availability reporting - so the mental model transfers. Adding a transcription
provider (a cloud ASR API, whisper.cpp, a different local engine) means
implementing this interface and registering it; see
docs/EXTENDING_THE_APPLICATION.md.

Implementers must:

* never raise from :meth:`check_availability` - a missing engine is a state the
  UI renders, not an exception;
* report progress through ``on_progress`` (0.0-1.0) so long files show movement;
* poll ``cancel_token`` between segments and stop promptly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.domain.enums import Language
from app.domain.transcription import TranscriptionOptions, TranscriptionResult
from app.process import CancelToken

#: ``(fraction_or_None, persian_stage_label)``
ProgressCallback = Callable[[float | None, str], None]
#: ``(stream, line)`` - mirrors the AI layer's console callback.
LogCallback = Callable[[str, str], None]


@dataclass(slots=True)
class EngineModel:
    """One selectable engine model (a Whisper size, a cloud tier, ...)."""

    id: str
    label_fa: str
    #: Approximate on-disk size of the weights, in megabytes. 0 when remote.
    size_mb: int = 0
    description_fa: str = ""
    #: False until the weights are present locally.
    downloaded: bool = False
    recommended: bool = False


@dataclass(slots=True)
class TranscriptionProviderInfo:
    """What the UI needs to render this engine's status."""

    id: str
    display_name: str
    available: bool = False
    unavailable_reason: str | None = None
    #: Persian, actionable: what the user should do about it.
    hint: str | None = None
    version: str | None = None
    #: True when the engine runs entirely on this machine.
    offline: bool = True
    supported_languages: list[Language] = field(default_factory=list)
    models: list[EngineModel] = field(default_factory=list)
    provides_word_timings: bool = False


class TranscriptionProvider(ABC):
    """Base class for every speech-recognition engine."""

    id: str = ""
    display_name: str = ""

    @abstractmethod
    def check_availability(self) -> TranscriptionProviderInfo:
        """Report whether this engine can run. Must not raise."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        *,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file into timed segments.

        Raises :class:`~app.core.errors.TranscriptionEngineNotAvailableError`
        when the engine is not installed, and
        :class:`~app.core.errors.ProcessCancelledError` when cancelled.
        """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self.id!r}>"
