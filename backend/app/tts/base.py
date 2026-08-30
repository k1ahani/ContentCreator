"""Text-to-speech provider interface.

Same shape as the AI and transcription layers: an abstract provider, a registry,
availability reporting that never throws, and no caller anywhere that names a
concrete implementation.

Two providers ship in version 1, which is what proves the abstraction is real
rather than aspirational:

* :class:`~app.tts.providers.sapi5.Sapi5Provider` - Windows System.Speech.
  Fully offline, zero dependencies, but limited to whatever voices are
  installed on the machine (usually English only).
* :class:`~app.tts.providers.edge.EdgeTtsProvider` - Microsoft neural voices,
  including real Persian (``fa-IR-DilaraNeural``, ``fa-IR-FaridNeural``), with
  rate and pitch control. Requires an internet connection.

Pause handling is deliberately *not* part of this interface. A provider
synthesises one span of continuous speech; assembling text and silence into a
finished track is the job of ``app/tts/assembler.py``, which uses FFmpeg. That
keeps every provider simple and makes pause behaviour identical across them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from app.domain.enums import Language
from app.domain.tts import SpeechOptions, VoiceSpec
from app.process import CancelToken

LogCallback = Callable[[str, str], None]


#: How a provider is paid for. Shown next to its name so the user knows what
#: they are choosing before they choose it, rather than discovering a quota
#: after a job fails.
Pricing = Literal["free", "freemium", "paid"]


@dataclass(slots=True)
class TTSProviderInfo:
    """What the UI needs to render this provider in the selector."""

    id: str
    display_name: str
    available: bool = False
    unavailable_reason: str | None = None
    hint: str | None = None
    #: True when synthesis works without a network connection.
    offline: bool = False
    supports_pitch: bool = False
    supports_styles: bool = False
    supported_languages: list[Language] = field(default_factory=list)
    voice_count: int = 0
    #: Commercial shape of the service behind this provider.
    pricing: Pricing = "free"
    #: True when the provider cannot work at all until the user pastes a key
    #: into Settings. Distinguishes "not configured yet" (the user's next
    #: step) from "broken" (something to investigate) in the UI.
    requires_api_key: bool = False
    #: Settings key holding that credential, so the UI can link straight to
    #: the field instead of describing where to find it.
    api_key_setting: str | None = None


class TTSProvider(ABC):
    """Base class for every speech synthesis backend."""

    id: str = ""
    display_name: str = ""

    @abstractmethod
    def check_availability(self) -> TTSProviderInfo:
        """Report whether synthesis can run right now. Must not raise."""

    @abstractmethod
    def list_voices(self, language: Language | None = None) -> list[VoiceSpec]:
        """Voices this provider offers, optionally filtered by language.

        Returns an empty list rather than raising when the provider is
        unavailable, so the settings page can render a useful empty state.
        """

    @abstractmethod
    def synthesize(
        self,
        text: str,
        options: SpeechOptions,
        output_path: Path,
        *,
        on_log: LogCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Render one continuous span of ``text`` to ``output_path``.

        Implementations must write a real audio file or raise
        :class:`~app.core.errors.TTSError`. They are never asked to handle
        pauses - see the module docstring.
        """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self.id!r}>"
