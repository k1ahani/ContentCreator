"""Transcription provider registry.

Mirrors ``app/ai/registry.py`` on purpose: same shape, same caching, same
"a missing engine is a reportable state, not an exception" rule.

Version 1 registers the local Whisper engine only. Add an engine by importing
it and appending it in :meth:`TranscriptionRegistry.build`.
"""

from __future__ import annotations

import threading
import time

from app.core.errors import ProviderNotFoundError
from app.core.logging import get_logger
from app.transcription.base import TranscriptionProvider, TranscriptionProviderInfo
from app.transcription.providers.faster_whisper_provider import FasterWhisperProvider

logger = get_logger(__name__)

_AVAILABILITY_TTL_SECONDS = 30.0


class TranscriptionRegistry:
    """Owns transcription engines and caches their availability."""

    def __init__(self, providers: list[TranscriptionProvider] | None = None) -> None:
        self._providers: dict[str, TranscriptionProvider] = {}
        self._info_cache: dict[str, tuple[float, TranscriptionProviderInfo]] = {}
        self._lock = threading.Lock()
        for provider in providers or []:
            self.register(provider)

    @classmethod
    def build(cls) -> "TranscriptionRegistry":
        return cls([FasterWhisperProvider()])

    def register(self, provider: TranscriptionProvider) -> None:
        if not provider.id:
            raise ValueError(f"{type(provider).__name__} must define a non-empty id")
        if provider.id in self._providers:
            raise ValueError(f"duplicate transcription provider id: {provider.id!r}")
        self._providers[provider.id] = provider
        logger.debug("registered transcription provider %r", provider.id)

    # -- lookup ------------------------------------------------------------

    def get(self, provider_id: str) -> TranscriptionProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderNotFoundError(
                f"unknown transcription provider {provider_id!r}",
                user_message="موتور تبدیل گفتار به متن انتخاب‌شده شناخته نشد.",
                details={"known": sorted(self._providers)},
            )
        return provider

    @property
    def ids(self) -> list[str]:
        return sorted(self._providers)

    def default_id(self) -> str:
        """First available engine, else the first registered one."""
        for provider_id in self.ids:
            if self.info(provider_id).available:
                return provider_id
        return self.ids[0] if self.ids else ""

    # -- availability ------------------------------------------------------

    def info(self, provider_id: str, *, refresh: bool = False) -> TranscriptionProviderInfo:
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
            info = TranscriptionProviderInfo(
                id=provider.id,
                display_name=provider.display_name,
                available=False,
                unavailable_reason=f"بررسی وضعیت این موتور ممکن نشد: {exc}",
            )

        with self._lock:
            self._info_cache[provider_id] = (now, info)
        return info

    def info_all(self, *, refresh: bool = False) -> list[TranscriptionProviderInfo]:
        return [self.info(pid, refresh=refresh) for pid in self.ids]

    def invalidate(self) -> None:
        with self._lock:
            self._info_cache.clear()
