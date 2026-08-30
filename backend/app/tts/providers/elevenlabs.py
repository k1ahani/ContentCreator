"""ElevenLabs neural voices.

The premium end of the provider list: the most natural-sounding English on
offer here, a large catalogue of distinct voices, and a published sample for
every one of them (``preview_url``) so the voice selector can play a real
sample without spending any of the user's quota.

Three things make this provider structurally different from the Edge and
SAPI5 ones, and all three are handled here rather than leaking into the
shared layer:

**It needs a credential.** Nothing works until an API key is set in
Settings -> Voice. That is a *configuration* state, not a failure, and
:meth:`check_availability` reports it as one - ``requires_api_key`` plus a
Persian hint naming the exact setting - so the UI can tell "you have not set
this up yet" apart from "this is broken".

**Its voices are multilingual, and the platform's are not.** One ElevenLabs
voice can read any language its model supports, while
:class:`~app.domain.tts.VoiceSpec` names exactly one. Rather than pick a
language for the user or list the same voice twice under one id, the voice id
this provider advertises carries the language with it (see
:func:`_compose_id`), which keeps ids unique and keeps ``list_voices(fa)``
honest about what it is offering.

**Persian is model-dependent, and the default model does not officially cover
it.** ``eleven_multilingual_v2`` - the sensible default for quality - lists 29
languages, and Persian is not among them; the newer expanded-language models
do. Rather than quietly produce mangled Persian, the availability hint says so
and points at the Microsoft neural provider, which has genuine Persian voices.
The model is a setting (``voice.elevenlabs_model``) so a user on a
Persian-capable model is not blocked by this file's default.
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

API_ROOT = "https://api.elevenlabs.io/v1"

#: Default synthesis model. Chosen for quality over latency: this platform
#: renders files, it does not stream a live conversation, so the faster
#: "turbo" models trade away quality for a latency nobody here is waiting on.
DEFAULT_MODEL = "eleven_multilingual_v2"

#: Settings key holding the credential, named here so the provider can point
#: the user at the exact field instead of describing where to look.
API_KEY_SETTING = "voice.elevenlabs_api_key"

#: Separator for the composite voice id. A colon cannot appear in an
#: ElevenLabs voice id (they are 20-character alphanumeric strings), so
#: splitting on it is unambiguous.
_ID_SEPARATOR = ":"
_ID_PREFIX = "eleven"

#: The service exposes expressiveness as a ``style`` weight and a
#: ``stability`` weight rather than named styles, so the platform's speaking
#: styles map onto that pair. Lower stability means more variation between
#: sentences; higher style means more exaggerated delivery. These are the
#: service's own knobs, honestly mapped - not invented labels.
_STYLE_SETTINGS: dict[SpeakingStyle, tuple[float, float]] = {
    SpeakingStyle.NEUTRAL: (0.50, 0.00),
    SpeakingStyle.FRIENDLY: (0.40, 0.35),
    SpeakingStyle.CASUAL: (0.35, 0.30),
    SpeakingStyle.PROFESSIONAL: (0.65, 0.10),
    SpeakingStyle.FORMAL: (0.75, 0.05),
    SpeakingStyle.ENERGETIC: (0.30, 0.60),
    SpeakingStyle.CALM: (0.80, 0.00),
}

#: The service clamps playback speed to this window; sending anything outside
#: it is rejected with a 422 rather than clipped, so the platform's wider
#: 0.5-2.0 rate range is squeezed into it here.
_MIN_SPEED, _MAX_SPEED = 0.7, 1.2

_GENDER_MAP = {"male": VoiceGender.MALE, "female": VoiceGender.FEMALE}
_AGE_MAP = {
    "young": VoiceAge.YOUNG,
    "middle_aged": VoiceAge.ADULT,
    "middle aged": VoiceAge.ADULT,
    "old": VoiceAge.MATURE,
}


class ElevenLabsProvider(TTSProvider):
    """Voices from the ElevenLabs API. Requires a key and an internet connection."""

    id = "elevenlabs"
    display_name = "ElevenLabs"

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip() or DEFAULT_MODEL
        #: Voice catalogue, fetched once per provider instance. The container
        #: rebuilds the registry when a voice setting changes, so a new key
        #: produces a new instance and therefore a fresh catalogue.
        self._voice_cache: list[VoiceSpec] | None = None

    # -- availability ------------------------------------------------------

    def check_availability(self) -> TTSProviderInfo:
        info = TTSProviderInfo(
            id=self.id,
            display_name=self.display_name,
            offline=False,
            supports_pitch=False,
            supports_styles=True,
            supported_languages=[Language.ENGLISH, Language.PERSIAN],
            pricing="freemium",
            requires_api_key=True,
            api_key_setting=API_KEY_SETTING,
        )

        if not self._api_key:
            info.available = False
            info.unavailable_reason = "کلید API این سرویس وارد نشده است."
            info.hint = "کلید را از «تنظیمات ← صدا» وارد کنید."
            return info

        try:
            voices = self.list_voices()
        except TTSError as exc:
            info.available = False
            info.unavailable_reason = exc.user_message
            info.hint = exc.hint
            return info

        info.available = True
        info.voice_count = len(voices)
        if not _model_covers_persian(self._model):
            info.hint = (
                f"مدل «{self._model}» فارسی را رسمی پشتیبانی نمی‌کند. برای فارسی "
                "از موتور «صداهای عصبی مایکروسافت» استفاده کنید یا مدل را در "
                "تنظیمات تغییر دهید."
            )
        return info

    # -- voices ------------------------------------------------------------

    def list_voices(self, language: Language | None = None) -> list[VoiceSpec]:
        if not self._api_key:
            return []
        if self._voice_cache is None:
            self._voice_cache = self._fetch_voices()
        if language is None:
            return list(self._voice_cache)
        return [voice for voice in self._voice_cache if voice.language == language]

    def _fetch_voices(self) -> list[VoiceSpec]:
        payload = get_json(f"{API_ROOT}/voices", headers=self._headers())
        entries = payload.get("voices") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise TTSError(
                "ElevenLabs voice listing had an unexpected shape",
                user_message="فهرست صداهای این سرویس خوانده نشد.",
            )

        voices: list[VoiceSpec] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            voice_id = str(entry.get("voice_id") or "")
            if not voice_id:
                continue
            labels = entry.get("labels") if isinstance(entry.get("labels"), dict) else {}
            accent = str(labels.get("accent") or "")
            base_name = str(entry.get("name") or voice_id)

            # One catalogue entry becomes one VoiceSpec per language the
            # platform models, because the underlying voice really can read
            # both - see the module docstring.
            for language in Language:
                voices.append(
                    VoiceSpec(
                        id=_compose_id(voice_id, language),
                        provider=self.id,
                        name=f"{base_name} ({accent})" if accent else base_name,
                        language=language,
                        locale=language.value,
                        gender=_GENDER_MAP.get(
                            str(labels.get("gender") or "").lower(), VoiceGender.UNKNOWN
                        ),
                        age=_AGE_MAP.get(
                            str(labels.get("age") or "").lower(), VoiceAge.UNKNOWN
                        ),
                        styles=list(_STYLE_SETTINGS),
                        supports_pitch=False,
                        supports_rate=True,
                        description=str(
                            entry.get("description") or labels.get("description") or ""
                        ),
                        preview_url=str(entry.get("preview_url") or "") or None,
                    )
                )

        logger.info("ElevenLabs offers %d voice(s)", len(entries))
        return voices

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
        if not self._api_key:
            raise TTSError(
                "ElevenLabs API key is not configured",
                user_message="کلید API سرویس ElevenLabs وارد نشده است.",
                hint="کلید را از «تنظیمات ← صدا» وارد کنید.",
            )
        if cancel_token is not None and cancel_token.cancelled:
            raise ProcessCancelledError("synthesis cancelled before start")

        voice_id, _ = _parse_id(options.voice_id)
        stability, style = _STYLE_SETTINGS.get(
            options.style, _STYLE_SETTINGS[SpeakingStyle.NEUTRAL]
        )
        speed = min(_MAX_SPEED, max(_MIN_SPEED, options.rate))

        if on_log:
            on_log(
                "system",
                f"elevenlabs voice={voice_id} model={self._model} speed={speed:.2f} "
                f"stability={stability} style={style} chars={len(text)}",
            )

        started = time.monotonic()
        audio = post_json_for_audio(
            f"{API_ROOT}/text-to-speech/{voice_id}",
            {
                "text": text,
                "model_id": self._model,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": 0.75,
                    "style": style,
                    "use_speaker_boost": True,
                    "speed": speed,
                },
            },
            headers=self._headers(),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                "ElevenLabs produced no audio",
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
        return {"xi-api-key": self._api_key, "Accept": "audio/mpeg"}


def _compose_id(voice_id: str, language: Language) -> str:
    """Build the platform-facing voice id: ``eleven:<voice>:<language>``."""
    return f"{_ID_PREFIX}{_ID_SEPARATOR}{voice_id}{_ID_SEPARATOR}{language.value}"


def _parse_id(composite: str) -> tuple[str, Language]:
    """Recover the service's own voice id and the chosen language.

    Tolerates a bare service id (no prefix) so a voice id copied straight from
    the ElevenLabs dashboard into settings still works.
    """
    parts = composite.split(_ID_SEPARATOR)
    if len(parts) == 3 and parts[0] == _ID_PREFIX:
        try:
            return parts[1], Language(parts[2])
        except ValueError:
            return parts[1], Language.ENGLISH
    return composite, Language.ENGLISH


def _model_covers_persian(model: str) -> bool:
    """Whether the configured model officially lists Persian.

    ``eleven_multilingual_v2`` and the turbo models cover 29-32 languages
    without Persian; the v3 generation covers 70+ and includes it. Matching on
    the family name rather than an exhaustive list keeps this honest as new
    point releases appear.
    """
    return "v3" in model.lower()
