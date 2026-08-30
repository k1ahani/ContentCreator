"""Any speech service that speaks the OpenAI ``/audio/speech`` protocol.

One provider, two very different deployments, which is exactly why it is
written against the *protocol* rather than against a company:

* **Paid, hosted** - OpenAI's own endpoint. Good multilingual quality,
  per-character billing, needs a key.
* **Free, local** - a self-hosted server that implements the same route
  (Kokoro-FastAPI, LocalAI, openedai-speech and others all do). Runs on the
  user's own machine, costs nothing, needs no key, and works with no internet
  at all. Point ``voice.openai_base_url`` at ``http://localhost:8880/v1`` and
  the same code path drives it.

That is the honest argument for having this provider alongside ElevenLabs: it
is not a second premium vendor, it is the seam through which every
OpenAI-shaped service - including the free self-hosted ones - reaches this
platform without another module being written. Adding one more commercial
vendor with its own protocol would be a new file; adding a compatible server
is a settings change.

Voice discovery follows the same split. OpenAI publishes no listing endpoint,
so the built-in voice names below are used; compatible servers usually *do*
expose ``GET /audio/voices``, and when one answers, its catalogue wins. A
local server with forty voices therefore shows forty voices, not this file's
eleven.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.core.errors import ProcessCancelledError, TTSError
from app.core.logging import get_logger
from app.domain.enums import Language, SpeakingStyle, VoiceAge, VoiceGender
from app.domain.tts import SpeechOptions, VoiceSpec
from app.process import CancelToken
from app.tts.base import LogCallback, TTSProvider, TTSProviderInfo
from app.tts.http import get_json, post_json_for_audio

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"

API_KEY_SETTING = "voice.openai_api_key"
BASE_URL_SETTING = "voice.openai_base_url"

_ID_SEPARATOR = ":"
_ID_PREFIX = "oai"

#: OpenAI's published voice names, with the gender each actually reads as.
#: Used when the endpoint offers no listing of its own.
_BUILTIN_VOICES: tuple[tuple[str, VoiceGender, str], ...] = (
    ("alloy", VoiceGender.UNKNOWN, "Balanced and neutral; the safe default."),
    ("ash", VoiceGender.MALE, "Deeper and steady; good for narration."),
    ("ballad", VoiceGender.MALE, "Softer, more expressive delivery."),
    ("coral", VoiceGender.FEMALE, "Bright and warm."),
    ("echo", VoiceGender.MALE, "Even and measured."),
    ("fable", VoiceGender.UNKNOWN, "Storytelling cadence."),
    ("nova", VoiceGender.FEMALE, "Clear and energetic."),
    ("onyx", VoiceGender.MALE, "Deep and authoritative."),
    ("sage", VoiceGender.FEMALE, "Calm and considered."),
    ("shimmer", VoiceGender.FEMALE, "Light and friendly."),
    ("verse", VoiceGender.MALE, "Conversational and natural."),
)

#: This protocol has no style parameter at all, so the platform's speaking
#: styles are expressed the only way the endpoint allows - as a speed nudge,
#: combined with the user's own rate. Stated plainly rather than pretending
#: the service has named styles it does not have (the Edge provider makes the
#: same trade for the same reason; see its ``_STYLE_PROSODY``).
_STYLE_SPEED: dict[SpeakingStyle, float] = {
    SpeakingStyle.NEUTRAL: 1.00,
    SpeakingStyle.FRIENDLY: 1.03,
    SpeakingStyle.CASUAL: 1.05,
    SpeakingStyle.PROFESSIONAL: 0.98,
    SpeakingStyle.FORMAL: 0.94,
    SpeakingStyle.ENERGETIC: 1.12,
    SpeakingStyle.CALM: 0.90,
}

#: The endpoint rejects anything outside this window with a 400.
_MIN_SPEED, _MAX_SPEED = 0.25, 4.0


class OpenAICompatibleProvider(TTSProvider):
    """Speech from any endpoint implementing OpenAI's ``/audio/speech`` route."""

    id = "openai_compatible"
    display_name = "سرویس سازگار با OpenAI"

    def __init__(
        self, api_key: str = "", base_url: str = "", model: str = ""
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = ((base_url or "").strip() or DEFAULT_BASE_URL).rstrip("/")
        self._model = (model or "").strip() or DEFAULT_MODEL
        self._voice_cache: list[VoiceSpec] | None = None

    # -- availability ------------------------------------------------------

    @property
    def _is_local(self) -> bool:
        """A loopback endpoint is a self-hosted server: free, offline, and
        normally happy to be called without any credential at all."""
        lowered = self._base_url.lower()
        return "://localhost" in lowered or "://127.0.0.1" in lowered or "://[::1]" in lowered

    def check_availability(self) -> TTSProviderInfo:
        local = self._is_local
        info = TTSProviderInfo(
            id=self.id,
            display_name=self.display_name,
            offline=local,
            supports_pitch=False,
            supports_styles=True,
            supported_languages=[Language.ENGLISH, Language.PERSIAN],
            pricing="free" if local else "paid",
            requires_api_key=not local,
            api_key_setting=API_KEY_SETTING,
        )

        if not self._api_key and not local:
            info.available = False
            info.unavailable_reason = "کلید API این سرویس وارد نشده است."
            info.hint = (
                "کلید را از «تنظیمات ← صدا» وارد کنید، یا آدرس سرویس را به یک "
                "سرور محلی سازگار با OpenAI تغییر دهید."
            )
            return info

        info.available = True
        info.voice_count = len(self.list_voices())
        return info

    # -- voices ------------------------------------------------------------

    def list_voices(self, language: Language | None = None) -> list[VoiceSpec]:
        if not self._api_key and not self._is_local:
            return []
        if self._voice_cache is None:
            self._voice_cache = self._build_voices()
        if language is None:
            return list(self._voice_cache)
        return [voice for voice in self._voice_cache if voice.language == language]

    def _build_voices(self) -> list[VoiceSpec]:
        names = self._discover_voice_names()
        described = {name: description for name, _, description in _BUILTIN_VOICES}
        genders = {name: gender for name, gender, _ in _BUILTIN_VOICES}

        voices: list[VoiceSpec] = []
        for name in names:
            # Multilingual endpoint, single-language VoiceSpec: the id carries
            # the language, exactly as in the ElevenLabs provider.
            for language in Language:
                voices.append(
                    VoiceSpec(
                        id=_compose_id(name, language),
                        provider=self.id,
                        name=name,
                        language=language,
                        locale=language.value,
                        gender=genders.get(name, VoiceGender.UNKNOWN),
                        age=VoiceAge.ADULT,
                        styles=list(_STYLE_SPEED),
                        supports_pitch=False,
                        supports_rate=True,
                        description=described.get(name, ""),
                    )
                )
        return voices

    def _discover_voice_names(self) -> list[str]:
        """Ask the endpoint what it offers, falling back to OpenAI's own set.

        Never raises: a compatible server that does not implement the listing
        route answers 404, which is a perfectly normal outcome and must leave
        the provider usable with the built-in names rather than reporting
        itself broken.
        """
        try:
            payload = get_json(
                f"{self._base_url}/audio/voices", headers=self._headers(), timeout=10.0
            )
        except TTSError as exc:
            logger.debug("no voice listing at %s: %s", self._base_url, exc.message)
            return [name for name, _, _ in _BUILTIN_VOICES]

        # Servers disagree on the shape: {"voices": [...]} or a bare list, of
        # either strings or objects.
        entries = payload.get("voices") if isinstance(payload, dict) else payload
        if not isinstance(entries, list) or not entries:
            return [name for name, _, _ in _BUILTIN_VOICES]

        names: list[str] = []
        for entry in entries:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("id") or entry.get("name") or entry.get("voice")
                if name:
                    names.append(str(name))
        logger.info("%s offers %d voice(s)", self._base_url, len(names))
        return names or [name for name, _, _ in _BUILTIN_VOICES]

    # -- synthesis ---------------------------------------------------------

    def synthesize(
        self,
        text: str,
        options: SpeechOptions,
        output_path: Path,
        *,
        on_log: LogCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        if not text.strip():
            raise TTSError(
                "refusing to synthesize empty text",
                user_message="متنی برای تبدیل به گفتار وجود ندارد.",
            )
        if cancel_token is not None and cancel_token.cancelled:
            raise ProcessCancelledError("synthesis cancelled before start")

        voice_name, _ = _parse_id(options.voice_id)
        speed = min(
            _MAX_SPEED,
            max(
                _MIN_SPEED,
                options.rate
                * _STYLE_SPEED.get(options.style, _STYLE_SPEED[SpeakingStyle.NEUTRAL]),
            ),
        )

        if on_log:
            on_log(
                "system",
                f"openai-compatible voice={voice_name} model={self._model} "
                f"speed={speed:.2f} chars={len(text)} endpoint={self._base_url}",
            )

        started = time.monotonic()
        audio = post_json_for_audio(
            f"{self._base_url}/audio/speech",
            {
                "model": self._model,
                "input": text,
                "voice": voice_name,
                "speed": round(speed, 2),
                "response_format": options.output_format,
            },
            headers=self._headers(),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                "the speech endpoint produced no audio",
                user_message="سرویس تولید گفتار خروجی صوتی برنگرداند.",
            )

        if on_log:
            on_log(
                "system",
                f"wrote {output_path.name} ({len(audio) / 1024:.0f} KB in "
                f"{time.monotonic() - started:.1f}s)",
            )
        return output_path

    # -- helpers -----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}


def _compose_id(voice_name: str, language: Language) -> str:
    return f"{_ID_PREFIX}{_ID_SEPARATOR}{voice_name}{_ID_SEPARATOR}{language.value}"


def _parse_id(composite: str) -> tuple[str, Language]:
    """Recover the endpoint's own voice name and the chosen language."""
    parts = composite.split(_ID_SEPARATOR)
    if len(parts) == 3 and parts[0] == _ID_PREFIX:
        try:
            return parts[1], Language(parts[2])
        except ValueError:
            return parts[1], Language.ENGLISH
    return composite, Language.ENGLISH
