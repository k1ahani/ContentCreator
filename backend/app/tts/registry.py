"""Text-to-speech provider registry.

Same contract as the AI and transcription registries. Four providers ship, and
they were chosen to span the whole space rather than to pad the list - each one
is the only member of its category:

===================  ========  ========  ===========================================
Provider             Cost      Network   Why it is here
===================  ========  ========  ===========================================
``edge``             free      required  Real neural Persian; the quality default.
``sapi5``            free      none      Works with no internet at all.
``elevenlabs``       freemium  required  Best-in-class English, hosted samples.
``openai_compatible``varies    varies    Any OpenAI-shaped endpoint, hosted or local.
===================  ========  ========  ===========================================

Add a provider by implementing :class:`~app.tts.base.TTSProvider` and appending
it in :meth:`TTSRegistry.build` - one line. Everything downstream (the voice
endpoint, the provider selector, the preview endpoint, the synthesis job) reads
the registry and names no provider, so nothing else has to change.

**Why ``build`` takes settings.** Two of the four providers need a credential
or an endpoint before they can do anything, and settings are user-editable at
runtime. The registry is therefore rebuilt - not merely re-probed - when a
``voice.*`` setting changes (``ServiceContainer.invalidate``), so pasting an
API key takes effect immediately rather than at the next restart.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.errors import ProviderNotFoundError
from app.core.logging import get_logger
from app.domain.enums import Language
from app.domain.tts import VoiceSpec
from app.tts.base import TTSProvider, TTSProviderInfo
from app.tts.providers.edge import EdgeTtsProvider
from app.tts.providers.elevenlabs import ElevenLabsProvider
from app.tts.providers.openai_compatible import OpenAICompatibleProvider
from app.tts.providers.sapi5 import Sapi5Provider

logger = get_logger(__name__)

_AVAILABILITY_TTL_SECONDS = 60.0


class TTSRegistry:
    """Owns TTS providers, their availability and their combined voice list."""

    def __init__(self, providers: list[TTSProvider] | None = None) -> None:
        self._providers: dict[str, TTSProvider] = {}
        self._info_cache: dict[str, tuple[float, TTSProviderInfo]] = {}
        self._lock = threading.Lock()
        for provider in providers or []:
            self.register(provider)

    @classmethod
    def build(cls, settings: Any = None) -> "TTSRegistry":
        """Construct every provider, configured from user settings.

        ``settings`` is optional so a test (or any caller that only wants the
        credential-free providers) can build a registry with no database
        behind it; the API-backed providers then simply report themselves as
        not configured, which is the same state a fresh install is in.
        """

        def value(key: str, fallback: str = "") -> str:
            if settings is None:
                return fallback
            return str(settings.get(key) or fallback)

        # Order matters: it decides the default provider (see default_id) and
        # the order voices appear in. The neural provider is first because it
        # is the one that actually speaks Persian well and costs nothing.
        return cls(
            [
                EdgeTtsProvider(),
                Sapi5Provider(),
                ElevenLabsProvider(
                    api_key=value("voice.elevenlabs_api_key"),
                    model=value("voice.elevenlabs_model"),
                ),
                OpenAICompatibleProvider(
                    api_key=value("voice.openai_api_key"),
                    base_url=value("voice.openai_base_url"),
                    model=value("voice.openai_model"),
                ),
            ]
        )

    def register(self, provider: TTSProvider) -> None:
        if not provider.id:
            raise ValueError(f"{type(provider).__name__} must define a non-empty id")
        if provider.id in self._providers:
            raise ValueError(f"duplicate TTS provider id: {provider.id!r}")
        self._providers[provider.id] = provider
        logger.debug("registered TTS provider %r", provider.id)

    # -- lookup ------------------------------------------------------------

    def get(self, provider_id: str) -> TTSProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderNotFoundError(
                f"unknown TTS provider {provider_id!r}",
                user_message="موتور تولید گفتار انتخاب‌شده شناخته نشد.",
                details={"known": sorted(self._providers)},
            )
        return provider

    @property
    def ids(self) -> list[str]:
        # Registration order is meaningful here, unlike the other registries.
        return list(self._providers)

    def default_id(self, language: Language | None = None) -> str:
        """First available provider that can speak ``language``."""
        for provider_id in self.ids:
            info = self.info(provider_id)
            if not info.available:
                continue
            if language is None or language in info.supported_languages:
                return provider_id
        return self.ids[0] if self.ids else ""

    # -- availability ------------------------------------------------------

    def info(self, provider_id: str, *, refresh: bool = False) -> TTSProviderInfo:
        provider = self.get(provider_id)
        now = time.monotonic()

        with self._lock:
            cached = self._info_cache.get(provider_id)
            if cached and not refresh and now - cached[0] < _AVAILABILITY_TTL_SECONDS:
                return cached[1]

        try:
            info = provider.check_availability()
        except Exception as exc:
            logger.exception("availability probe failed for %r", provider_id)
            info = TTSProviderInfo(
                id=provider.id,
                display_name=provider.display_name,
                available=False,
                unavailable_reason=f"بررسی وضعیت این موتور ممکن نشد: {exc}",
            )

        with self._lock:
            self._info_cache[provider_id] = (now, info)
        return info

    def info_all(self, *, refresh: bool = False) -> list[TTSProviderInfo]:
        return [self.info(pid, refresh=refresh) for pid in self.ids]

    # -- voices ------------------------------------------------------------

    def list_voices(
        self, *, provider_id: str | None = None, language: Language | None = None
    ) -> list[VoiceSpec]:
        """Voices from one provider, or from every available provider."""
        targets = [provider_id] if provider_id else self.ids
        voices: list[VoiceSpec] = []
        for pid in targets:
            if not self.info(pid).available:
                continue
            try:
                voices.extend(self.get(pid).list_voices(language))
            except Exception:
                logger.exception("could not list voices for %r", pid)
        return voices

    def find_voice(self, voice_id: str) -> VoiceSpec | None:
        return next((v for v in self.list_voices() if v.id == voice_id), None)

    def provider_for_voice(self, voice_id: str) -> TTSProvider:
        """Resolve which provider owns a voice id."""
        voice = self.find_voice(voice_id)
        if voice is None:
            raise ProviderNotFoundError(
                f"no provider offers voice {voice_id!r}",
                user_message="صدای انتخاب‌شده در دسترس نیست.",
                hint="صدای دیگری از فهرست انتخاب کنید.",
            )
        return self.get(voice.provider)

    def invalidate(self) -> None:
        with self._lock:
            self._info_cache.clear()
