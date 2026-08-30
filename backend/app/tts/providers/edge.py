"""Microsoft Edge neural voices via the ``edge-tts`` package.

This is the provider that makes Persian text-to-speech actually usable:
``fa-IR-DilaraNeural`` (female) and ``fa-IR-FaridNeural`` (male) are genuine
neural Persian voices, and the service supports rate, pitch and volume.

It needs an internet connection, which is why the offline SAPI5 provider ships
alongside it rather than being replaced by it.

The ``edge_tts`` API is async, but the job system runs handlers on worker
threads. Rather than infecting the whole call chain with async, each synthesis
runs its coroutine in a dedicated event loop via :func:`asyncio.run`. That is
correct here because the worker thread has no running loop of its own.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.core.errors import ProcessCancelledError, TTSError
from app.core.logging import get_logger
from app.domain.enums import Language, SpeakingStyle, VoiceAge, VoiceGender
from app.domain.tts import SpeechOptions, VoiceSpec
from app.process import CancelToken
from app.tts.base import LogCallback, TTSProvider, TTSProviderInfo

logger = get_logger(__name__)

#: Voices exposed by this provider, curated by hand.
#:
#: The service offers well over four hundred voices across a hundred-odd
#: locales; these are every neural voice it has for the two languages the
#: platform supports (:class:`~app.domain.enums.Language`), which is what "as
#: many as possible" means here - listing its Japanese voices would only give
#: the user hundreds of entries they cannot use, since a voice speaking a
#: language the rest of the pipeline does not model produces gibberish.
#:
#: Persian has exactly two neural voices in the service and both are here.
#: English is deliberately broad *across accents* - en-US, en-GB, en-AU, en-CA,
#: en-IE, en-IN, en-NZ, en-ZA, en-HK, en-KE, en-NG, en-PH, en-SG, en-TZ -
#: because the real choice a user makes is which accent narrates the video, and
#: that choice should be visible rather than implied.
#:
#: The list is static rather than fetched from the service on every call: the
#: voice selector has to render instantly and still work with no network (an
#: offline machine should see the catalogue with a clear "needs internet" note,
#: not an empty page), and Microsoft's catalogue for these two languages
#: changes roughly once a year. Run ``python -m edge_tts --list-voices`` to
#: check it against the live service.
_VOICES: tuple[dict, ...] = (
    # -- Persian ---------------------------------------------------------
    {
        "id": "fa-IR-DilaraNeural",
        "name": "دلارا (زن)",
        "language": Language.PERSIAN,
        "locale": "fa-IR",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "صدای زنانه طبیعی فارسی، مناسب روایت و آموزش.",
    },
    {
        "id": "fa-IR-FaridNeural",
        "name": "فرید (مرد)",
        "language": Language.PERSIAN,
        "locale": "fa-IR",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "صدای مردانه طبیعی فارسی، مناسب روایت و پادکست.",
    },
    # -- English (United States) -----------------------------------------
    #
    # The four "Multilingual" voices are the service's newest generation and
    # are noticeably more natural than the older US set below them; they are
    # listed first so the default pick is the best one available.
    {
        "id": "en-US-AvaMultilingualNeural",
        "name": "Ava (female, multilingual)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Expressive American English; the most natural of the US set.",
    },
    {
        "id": "en-US-AndrewMultilingualNeural",
        "name": "Andrew (male, multilingual)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Warm, confident American English; strong for narration.",
    },
    {
        "id": "en-US-EmmaMultilingualNeural",
        "name": "Emma (female, multilingual)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "Light, friendly American English; good for explainers.",
    },
    {
        "id": "en-US-BrianMultilingualNeural",
        "name": "Brian (male, multilingual)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Relaxed conversational American English.",
    },
    {
        "id": "en-US-AriaNeural",
        "name": "Aria (female)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Natural American English, versatile for narration.",
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Jenny (female)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "Friendly American English, good for casual delivery.",
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy (male)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Natural American English, warm and conversational.",
    },
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (male)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.MATURE,
        "description": "Deeper American English; authoritative documentary tone.",
    },
    {
        "id": "en-US-EricNeural",
        "name": "Eric (male)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Even, measured American English for long-form reading.",
    },
    {
        "id": "en-US-RogerNeural",
        "name": "Roger (male)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.MATURE,
        "description": "Mature American English with a news-reader cadence.",
    },
    {
        "id": "en-US-SteffanNeural",
        "name": "Steffan (male)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Clear American English suited to instructional content.",
    },
    {
        "id": "en-US-MichelleNeural",
        "name": "Michelle (female)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Calm American English; pleasant over a long narration.",
    },
    {
        "id": "en-US-AnaNeural",
        "name": "Ana (female, child)",
        "language": Language.ENGLISH,
        "locale": "en-US",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "Child-like American English, for playful content.",
    },
    # -- English (United Kingdom) ----------------------------------------
    {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia (female, British)",
        "language": Language.ENGLISH,
        "locale": "en-GB",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "British English, crisp and professional.",
    },
    {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (male, British)",
        "language": Language.ENGLISH,
        "locale": "en-GB",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "British English, measured and professional.",
    },
    {
        "id": "en-GB-LibbyNeural",
        "name": "Libby (female, British)",
        "language": Language.ENGLISH,
        "locale": "en-GB",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "Younger British English; bright and approachable.",
    },
    {
        "id": "en-GB-ThomasNeural",
        "name": "Thomas (male, British)",
        "language": Language.ENGLISH,
        "locale": "en-GB",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "British English with a softer, documentary delivery.",
    },
    {
        "id": "en-GB-MaisieNeural",
        "name": "Maisie (female, British child)",
        "language": Language.ENGLISH,
        "locale": "en-GB",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.YOUNG,
        "description": "Child-like British English.",
    },
    # -- English (rest of the world) -------------------------------------
    {
        "id": "en-AU-NatashaNeural",
        "name": "Natasha (female, Australian)",
        "language": Language.ENGLISH,
        "locale": "en-AU",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Australian English, relaxed and clear.",
    },
    {
        "id": "en-AU-WilliamNeural",
        "name": "William (male, Australian)",
        "language": Language.ENGLISH,
        "locale": "en-AU",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Australian English, steady narration voice.",
    },
    {
        "id": "en-CA-ClaraNeural",
        "name": "Clara (female, Canadian)",
        "language": Language.ENGLISH,
        "locale": "en-CA",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Canadian English, neutral and friendly.",
    },
    {
        "id": "en-CA-LiamNeural",
        "name": "Liam (male, Canadian)",
        "language": Language.ENGLISH,
        "locale": "en-CA",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Canadian English, easy conversational tone.",
    },
    {
        "id": "en-IE-EmilyNeural",
        "name": "Emily (female, Irish)",
        "language": Language.ENGLISH,
        "locale": "en-IE",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Irish English, warm and lyrical.",
    },
    {
        "id": "en-IE-ConnorNeural",
        "name": "Connor (male, Irish)",
        "language": Language.ENGLISH,
        "locale": "en-IE",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Irish English, casual and personable.",
    },
    {
        "id": "en-IN-NeerjaNeural",
        "name": "Neerja (female, Indian)",
        "language": Language.ENGLISH,
        "locale": "en-IN",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Indian English, clear and articulate.",
    },
    {
        "id": "en-IN-PrabhatNeural",
        "name": "Prabhat (male, Indian)",
        "language": Language.ENGLISH,
        "locale": "en-IN",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "Indian English, steady and professional.",
    },
    {
        "id": "en-NZ-MollyNeural",
        "name": "Molly (female, New Zealand)",
        "language": Language.ENGLISH,
        "locale": "en-NZ",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "New Zealand English, bright and natural.",
    },
    {
        "id": "en-NZ-MitchellNeural",
        "name": "Mitchell (male, New Zealand)",
        "language": Language.ENGLISH,
        "locale": "en-NZ",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "New Zealand English, unhurried narration.",
    },
    {
        "id": "en-ZA-LeahNeural",
        "name": "Leah (female, South African)",
        "language": Language.ENGLISH,
        "locale": "en-ZA",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "South African English, calm and precise.",
    },
    {
        "id": "en-ZA-LukeNeural",
        "name": "Luke (male, South African)",
        "language": Language.ENGLISH,
        "locale": "en-ZA",
        "gender": VoiceGender.MALE,
        "age": VoiceAge.ADULT,
        "description": "South African English, grounded delivery.",
    },
    {
        "id": "en-HK-YanNeural",
        "name": "Yan (female, Hong Kong)",
        "language": Language.ENGLISH,
        "locale": "en-HK",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Hong Kong English, neutral and clear.",
    },
    {
        "id": "en-KE-AsiliaNeural",
        "name": "Asilia (female, Kenyan)",
        "language": Language.ENGLISH,
        "locale": "en-KE",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Kenyan English, warm and even.",
    },
    {
        "id": "en-NG-EzinneNeural",
        "name": "Ezinne (female, Nigerian)",
        "language": Language.ENGLISH,
        "locale": "en-NG",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Nigerian English, expressive and clear.",
    },
    {
        "id": "en-PH-RosaNeural",
        "name": "Rosa (female, Filipino)",
        "language": Language.ENGLISH,
        "locale": "en-PH",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Philippine English, friendly and light.",
    },
    {
        "id": "en-SG-LunaNeural",
        "name": "Luna (female, Singaporean)",
        "language": Language.ENGLISH,
        "locale": "en-SG",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Singapore English, crisp and neutral.",
    },
    {
        "id": "en-TZ-ImaniNeural",
        "name": "Imani (female, Tanzanian)",
        "language": Language.ENGLISH,
        "locale": "en-TZ",
        "gender": VoiceGender.FEMALE,
        "age": VoiceAge.ADULT,
        "description": "Tanzanian English, measured and calm.",
    },
)

#: Every listed voice supports these through rate/pitch shaping.
_STYLES = [
    SpeakingStyle.NEUTRAL,
    SpeakingStyle.FRIENDLY,
    SpeakingStyle.CASUAL,
    SpeakingStyle.PROFESSIONAL,
    SpeakingStyle.FORMAL,
    SpeakingStyle.ENERGETIC,
    SpeakingStyle.CALM,
]

#: How a speaking style maps onto rate and pitch multipliers. The service's
#: style tags are not available for these voices, so style is expressed through
#: prosody - which is honest about what it actually does.
_STYLE_PROSODY: dict[SpeakingStyle, tuple[float, float]] = {
    SpeakingStyle.NEUTRAL: (1.0, 0.0),
    SpeakingStyle.FRIENDLY: (1.03, 1.0),
    SpeakingStyle.CASUAL: (1.05, 0.5),
    SpeakingStyle.PROFESSIONAL: (0.98, -0.5),
    SpeakingStyle.FORMAL: (0.94, -1.0),
    SpeakingStyle.ENERGETIC: (1.12, 2.0),
    SpeakingStyle.CALM: (0.90, -1.5),
}


class EdgeTtsProvider(TTSProvider):
    """Neural voices from the Microsoft Edge read-aloud service."""

    id = "edge"
    display_name = "صداهای عصبی مایکروسافت"

    # -- availability ------------------------------------------------------

    def check_availability(self) -> TTSProviderInfo:
        info = TTSProviderInfo(
            id=self.id,
            display_name=self.display_name,
            offline=False,
            supports_pitch=True,
            supports_styles=True,
            supported_languages=[Language.PERSIAN, Language.ENGLISH],
            voice_count=len(_VOICES),
            pricing="free",
        )
        try:
            import edge_tts  # noqa: F401, PLC0415
        except ImportError as exc:
            info.available = False
            info.unavailable_reason = "بسته edge-tts نصب نشده است."
            info.hint = "اسکریپت scripts/setup.ps1 را اجرا کنید."
            logger.info("edge-tts unavailable: %s", exc)
            return info

        info.available = True
        return info

    # -- voices ------------------------------------------------------------

    def list_voices(self, language: Language | None = None) -> list[VoiceSpec]:
        specs = [
            VoiceSpec(
                id=voice["id"],
                provider=self.id,
                name=voice["name"],
                language=voice["language"],
                locale=voice["locale"],
                gender=voice["gender"],
                age=voice["age"],
                styles=list(_STYLES),
                supports_pitch=True,
                supports_rate=True,
                description=voice["description"],
            )
            for voice in _VOICES
        ]
        if language is not None:
            specs = [spec for spec in specs if spec.language == language]
        return specs

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

        try:
            import edge_tts  # noqa: PLC0415
        except ImportError as exc:
            raise TTSError(
                f"edge-tts is not installed: {exc}",
                user_message="بسته edge-tts نصب نشده است.",
                hint="اسکریپت scripts/setup.ps1 را اجرا کنید.",
            ) from exc

        rate_pct, pitch_hz = self._prosody(options)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if on_log:
            on_log(
                "system",
                f"edge-tts voice={options.voice_id} rate={rate_pct} pitch={pitch_hz} "
                f"chars={len(text)}",
            )

        started = time.monotonic()
        try:
            asyncio.run(
                self._synthesize_async(
                    edge_tts, text, options.voice_id, rate_pct, pitch_hz, output_path
                )
            )
        except ProcessCancelledError:
            raise
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                f"edge-tts synthesis failed: {exc}",
                user_message="تولید گفتار با خطا مواجه شد.",
                hint=_hint_for(exc),
            ) from exc

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                "edge-tts produced no audio",
                user_message="سرویس تولید گفتار خروجی صوتی برنگرداند.",
                hint="اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.",
            )

        if on_log:
            on_log(
                "system",
                f"wrote {output_path.name} "
                f"({output_path.stat().st_size / 1024:.0f} KB in {time.monotonic() - started:.1f}s)",
            )
        return output_path

    @staticmethod
    async def _synthesize_async(
        edge_tts,
        text: str,
        voice: str,
        rate: str,
        pitch: str,
        output_path: Path,
    ) -> None:
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, pitch=pitch
        )
        await communicate.save(str(output_path))

    @staticmethod
    def _prosody(options: SpeechOptions) -> tuple[str, str]:
        """Combine the user's rate/pitch with the style's prosody shaping.

        edge-tts wants signed percentage and Hertz strings, e.g. ``+10%`` and
        ``-2Hz``.
        """
        style_rate, style_pitch = _STYLE_PROSODY.get(
            options.style, _STYLE_PROSODY[SpeakingStyle.NEUTRAL]
        )
        combined_rate = options.rate * style_rate
        # The service accepts roughly -50%..+100%; clamp to stay inside it.
        percent = max(-50, min(100, round((combined_rate - 1.0) * 100)))
        semitones = max(-12.0, min(12.0, options.pitch + style_pitch))
        # Approximate semitones as Hertz around a typical speech fundamental.
        hertz = round(semitones * 8)
        return f"{percent:+d}%", f"{hertz:+d}Hz"


def _hint_for(exc: Exception) -> str:
    text = str(exc).lower()
    if "connect" in text or "network" in text or "timeout" in text or "resolve" in text:
        return "این سرویس به اینترنت نیاز دارد. اتصال شبکه را بررسی کنید."
    if "403" in text or "401" in text:
        return "سرویس درخواست را رد کرد. کمی بعد دوباره تلاش کنید."
    if "no audio" in text or "invalid" in text:
        return "صدای انتخاب‌شده معتبر نیست. صدای دیگری انتخاب کنید."
    return "جزئیات فنی در کنسول این وظیفه در دسترس است."
