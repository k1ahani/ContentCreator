"""Provider registry.

Holds the provider instances the application knows about and answers "which
providers exist and can they run right now?".

**Adding a provider is a two-line change here.** Import it and add it to
``build``. Everything else - the selector in the UI, the model list, task
routing - follows from the interface. A provider whose tool is not installed,
or not logged in, still appears in the registry; it reports
``available=False`` with a Persian reason so the UI can grey it out instead of
failing at execution time.

Two providers ship: Claude and OpenAI Codex, both driven through their local
CLIs (see ``docs/AI_PROVIDERS.md`` and ``docs/CLI_INTEGRATION.md``). Which one
executes a given task is never hardcoded here - see
``app/services/settings.py``'s ``ai.provider`` default and
``AIService.resolve_provider_id``.
"""

from __future__ import annotations

import threading
import time

from app.ai.base import AIProvider
from app.ai.providers.claude import ClaudeProvider
from app.ai.providers.codex import CodexProvider
from app.core.errors import ProviderNotFoundError
from app.core.logging import get_logger
from app.domain.ai import ProviderInfo

logger = get_logger(__name__)

#: Availability probes shell out to the CLI, so results are cached briefly.
_AVAILABILITY_TTL_SECONDS = 60.0


class ProviderRegistry:
    """Owns provider instances and caches their availability."""

    def __init__(self, providers: list[AIProvider] | None = None) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._info_cache: dict[str, tuple[float, ProviderInfo]] = {}
        self._lock = threading.Lock()
        for provider in providers or []:
            self.register(provider)

    # -- construction ------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        claude_cli_path: str | None = None,
        codex_cli_path: str | None = None,
        timeout: int = 900,
    ) -> "ProviderRegistry":
        """Create the registry for this application.

        When adding a provider, construct it here alongside the existing ones.
        """
        return cls(
            [
                ClaudeProvider(configured_path=claude_cli_path, timeout=timeout),
                CodexProvider(configured_path=codex_cli_path, timeout=timeout),
            ]
        )

    def register(self, provider: AIProvider) -> None:
        if not provider.id:
            raise ValueError(f"{type(provider).__name__} must define a non-empty id")
        if provider.id in self._providers:
            raise ValueError(f"duplicate provider id: {provider.id!r}")
        self._providers[provider.id] = provider
        logger.debug("registered AI provider %r", provider.id)

    # -- lookup ------------------------------------------------------------

    def get(self, provider_id: str) -> AIProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderNotFoundError(
                f"unknown AI provider {provider_id!r}",
                details={"known": sorted(self._providers)},
            )
        return provider

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers

    @property
    def ids(self) -> list[str]:
        return sorted(self._providers)

    def all(self) -> list[AIProvider]:
        return [self._providers[key] for key in sorted(self._providers)]

    # -- availability ------------------------------------------------------

    def info(self, provider_id: str, *, refresh: bool = False) -> ProviderInfo:
        """Availability of one provider, cached for a minute."""
        provider = self.get(provider_id)
        now = time.monotonic()

        with self._lock:
            cached = self._info_cache.get(provider_id)
            if cached and not refresh and now - cached[0] < _AVAILABILITY_TTL_SECONDS:
                return cached[1]

        try:
            info = provider.check_availability()
        except Exception as exc:  # a broken probe must not break the page
            logger.exception("availability probe failed for %r", provider_id)
            info = ProviderInfo(
                id=provider.id,
                display_name=provider.display_name,
                available=False,
                unavailable_reason=f"بررسی وضعیت این ارائه‌دهنده ممکن نشد: {exc}",
            )

        with self._lock:
            self._info_cache[provider_id] = (now, info)
        return info

    def info_all(self, *, refresh: bool = False) -> list[ProviderInfo]:
        return [self.info(provider_id, refresh=refresh) for provider_id in self.ids]

    def first_available(self) -> str | None:
        for provider_id in self.ids:
            if self.info(provider_id).available:
                return provider_id
        return None

    def invalidate(self, provider_id: str | None = None) -> None:
        """Drop cached availability, e.g. after the CLI path setting changes."""
        with self._lock:
            if provider_id is None:
                self._info_cache.clear()
            else:
                self._info_cache.pop(provider_id, None)
