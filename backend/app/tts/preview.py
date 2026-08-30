"""Short audio samples of a voice, for auditioning it before using it.

Picking a voice from a list of forty names and one-line descriptions is
guesswork. This module is what turns that into listening, and it does so
without ever making the user pay twice for the same sample.

Two sources, preferred in this order:

1. **A sample the provider already publishes.** ElevenLabs ships a
   ``preview_url`` with every voice in its catalogue. Using it costs the user
   nothing - no quota, no characters billed - which is exactly why a hosted
   sample always wins over synthesising our own.
2. **A real synthesis of one short sentence**, for the providers that publish
   nothing (Edge, SAPI5, most OpenAI-compatible endpoints). This is genuine
   output from the same code path the actual job uses, so what the user hears
   is what they will get.

Either way the bytes are cached on disk under ``storage/.tts-temp/previews``,
keyed by voice *and* sample text. Auditioning ten voices, changing your mind
and going back costs ten syntheses, not twenty, and a paid provider is never
billed for a sample the platform already has.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.errors import TTSError
from app.core.logging import get_logger
from app.domain.tts import SpeechOptions, VoiceSpec
from app.tts.http import download
from app.tts.registry import TTSRegistry

logger = get_logger(__name__)

#: Samples are tiny (a few tens of KB) but the cache is unbounded in principle,
#: so it lives under the scratch tree that is safe to delete at any time.
_MEDIA_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}
_DEFAULT_MEDIA_TYPE = "audio/mpeg"


def build_voice_preview(
    registry: TTSRegistry,
    voice: VoiceSpec,
    text: str,
    *,
    cache_dir: Path,
) -> tuple[bytes, str]:
    """Return ``(audio_bytes, media_type)`` for one voice speaking ``text``."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = _cache_stem(voice, text)

    cached = _find_cached(cache_dir, stem)
    if cached is not None:
        logger.debug("serving cached preview for %s", voice.id)
        return cached.read_bytes(), _media_type(cached)

    if voice.preview_url:
        audio = download(voice.preview_url)
        if audio:
            path = cache_dir / f"{stem}.mp3"
            path.write_bytes(audio)
            return audio, _DEFAULT_MEDIA_TYPE
        # An empty or unreachable hosted sample is not fatal: fall through and
        # synthesise one, which is strictly better than an error the user can
        # do nothing about.
        logger.info("hosted preview for %s was empty; synthesising instead", voice.id)

    provider = registry.get(voice.provider)
    info = registry.info(voice.provider)
    if not info.available:
        raise TTSError(
            f"TTS provider {voice.provider!r} is unavailable",
            user_message=info.unavailable_reason or "این موتور تولید گفتار در دسترس نیست.",
            hint=info.hint,
        )

    target = cache_dir / f"{stem}.mp3"
    # Providers may rewrite the suffix to whatever they can actually write -
    # SAPI5 produces WAV only - so the returned path is authoritative, not the
    # one passed in.
    written = provider.synthesize(
        text,
        SpeechOptions(voice_id=voice.id, language=voice.language, output_format="mp3"),
        target,
    )
    return written.read_bytes(), _media_type(written)


def _cache_stem(voice: VoiceSpec, text: str) -> str:
    """A filesystem-safe key covering everything that changes the audio.

    The voice id alone is not enough: the sample sentence is user-editable
    (``voice.preview_text_*``), so keying on the voice would keep serving the
    old sentence after the user changed it.
    """
    digest = hashlib.sha256(f"{voice.provider}\x00{voice.id}\x00{text}".encode()).hexdigest()
    return digest[:32]


def _find_cached(cache_dir: Path, stem: str) -> Path | None:
    for suffix in _MEDIA_TYPES:
        candidate = cache_dir / f"{stem}{suffix}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), _DEFAULT_MEDIA_TYPE)
