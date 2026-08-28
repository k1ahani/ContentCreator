"""Text-to-speech provider registry.

Same contract as the AI and transcription registries. Version 1 registers two
providers, which is what keeps the abstraction honest: the neural provider for
quality and real Persian, the SAPI5 provider for fully offline operation.

Add a provider by importing it and appending it in :meth:`TTSRegistry.build`.
"""

from __future__ import annotations

import threading
import time

from app.core.errors import ProviderNotFoundError
from app.core.logging import get_logger
from app.domain.enums import Language
from app.domain.tts import VoiceSpec
from app.tts.base import TTSProvider, TTSProviderInfo
from app.tts.providers.edge import EdgeTtsProvider
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
    def build(cls) -> "TTSRegistry":
        # Order matters: the neural provider is listed first because it is the
        # one that actually speaks Persian.
        return cls([EdgeTtsProvider(), Sapi5Provider()])

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
