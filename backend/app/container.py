"""Composition root.

The one place where concrete implementations are chosen and wired together.
Everything else receives what it needs rather than constructing it, which is
what makes the provider layers swappable and the whole thing testable: a test
builds a container against a temporary database and gets the real object graph.

Registries and services that depend on user settings are built lazily and
invalidated when those settings change, so editing the Claude CLI path or the
FFmpeg path in the UI takes effect immediately without a restart.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.ai.models import ModelRegistry
from app.ai.registry import ProviderRegistry
from app.ai.service import AIService
from app.core.config import AppConfig, get_config
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.db.connection import Database
from app.db.migrations.runner import migrate
from app.db.repositories import (
    AssetRepository,
    DocumentRepository,
    JobRepository,
    ProjectRepository,
    PromptRepository,
    SettingsRepository,
    SubtitleRepository,
)
from app.jobs.events import EventBus
from app.jobs.queue import JobQueue
from app.jobs.registry import load_handlers
from app.media.ffmpeg.locator import FFmpegTools, clear_cache, find_ffmpeg, require_ffmpeg
from app.services.settings import SettingsService
from app.transcription.registry import TranscriptionRegistry
from app.tts.registry import TTSRegistry

logger = get_logger(__name__)


class ServiceContainer:
    """Owns the application's long-lived objects."""

    def __init__(self, config: AppConfig | None = None, *, database_path: Path | None = None) -> None:
        self.config = config or get_config()
        PATHS.ensure_base_dirs()

        self.db = Database(database_path or self.config.database_path)
        self.events = EventBus()

        self._lock = threading.Lock()
        self._ai: AIService | None = None
        self._providers: ProviderRegistry | None = None
        self._models: ModelRegistry | None = None
        self._transcription: TranscriptionRegistry | None = None
        self._tts: TTSRegistry | None = None

        self.jobs: JobQueue = JobQueue(
            services=self,
            events=self.events,
            worker_count=self.config.job_workers,
        )

    # -- lifecycle ---------------------------------------------------------

    def startup(self) -> None:
        """Migrate, load handlers, and start the worker pool."""
        migrate(self.db)

        # Fail fast if a job type has no handler.
        load_handlers()

        # A crash leaves jobs marked running with nothing behind them.
        orphaned = JobRepository(self.db).requeue_orphans()
        if orphaned:
            logger.info("marked %d interrupted job(s) as failed", orphaned)

        self.jobs.start()
        logger.info("application ready (workers=%d)", self.config.job_workers)

    def shutdown(self) -> None:
        self.jobs.stop()
        self.events.close()
        self.db.close()
        logger.info("application shut down")

    # -- repositories ------------------------------------------------------
    #
    # Repositories are cheap wrappers around the shared Database, which hands
    # out per-thread connections, so constructing one per request is correct
    # and keeps them free of cross-request state.

    @property
    def projects(self) -> ProjectRepository:
        return ProjectRepository(self.db)

    @property
    def assets(self) -> AssetRepository:
        return AssetRepository(self.db)

    @property
    def documents(self) -> DocumentRepository:
        return DocumentRepository(self.db)

    @property
    def subtitles(self) -> SubtitleRepository:
        return SubtitleRepository(self.db)

    @property
    def job_repo(self) -> JobRepository:
        return JobRepository(self.db)

    @property
    def prompts(self) -> PromptRepository:
        return PromptRepository(self.db)

    @property
    def settings(self) -> SettingsService:
        return SettingsService(SettingsRepository(self.db))

    # -- AI ----------------------------------------------------------------

    @property
    def models(self) -> ModelRegistry:
        with self._lock:
            if self._models is None:
                self._models = ModelRegistry.load()
            return self._models

    @property
    def providers(self) -> ProviderRegistry:
        with self._lock:
            if self._providers is None:
                settings = SettingsService(SettingsRepository(self.db))
                self._providers = ProviderRegistry.build(
                    claude_cli_path=settings.claude_cli_path,
                    codex_cli_path=settings.codex_cli_path,
                    timeout=int(settings.get("ai.timeout_seconds")),
                )
            return self._providers

    @property
    def ai(self) -> AIService:
        """The AI facade, rebuilt when relevant settings change."""
        with self._lock:
            cached = self._ai
        if cached is not None:
            return cached

        settings = SettingsService(SettingsRepository(self.db))
        service = AIService(
            providers=self.providers,
            models=self.models,
            default_provider=str(settings.get("ai.provider")),
            model_preferences=settings.model_preferences,
        )
        with self._lock:
            self._ai = service
        return service

    # -- transcription and speech -----------------------------------------

    @property
    def transcription(self) -> TranscriptionRegistry:
        with self._lock:
            if self._transcription is None:
                self._transcription = TranscriptionRegistry.build()
            return self._transcription

    @property
    def tts(self) -> TTSRegistry:
        """Speech providers, configured from the user's voice settings.

        Built outside the lock deliberately: two of the four providers probe a
        network endpoint while constructing their voice catalogue, and holding
        the container's single lock across that would stall every other lazy
        service behind a slow HTTP call. The worst case of the race is two
        registries being built concurrently and one being discarded.
        """
        with self._lock:
            cached = self._tts
        if cached is not None:
            return cached

        registry = TTSRegistry.build(SettingsService(SettingsRepository(self.db)))
        with self._lock:
            if self._tts is None:
                self._tts = registry
            return self._tts

    # -- media -------------------------------------------------------------

    def ffmpeg(self) -> FFmpegTools:
        """Resolved FFmpeg tools, or a Persian dependency error."""
        settings = SettingsService(SettingsRepository(self.db))
        return require_ffmpeg(settings.ffmpeg_path)

    def find_ffmpeg(self) -> FFmpegTools | None:
        """Non-raising variant, for status reporting."""
        settings = SettingsService(SettingsRepository(self.db))
        return find_ffmpeg(settings.ffmpeg_path)

    # -- invalidation ------------------------------------------------------

    def invalidate(self, *, keys: list[str] | None = None) -> None:
        """Drop cached objects affected by a settings change.

        Called by the settings endpoint. Being generous here is cheap - these
        objects are inexpensive to rebuild - and being stingy causes the
        confusing bug where the UI shows a saved path that nothing is using.
        """
        touched = set(keys or [])
        rebuild_ai = not touched or any(key.startswith("ai.") for key in touched)
        rebuild_media = not touched or any(key.startswith("media.") for key in touched)

        with self._lock:
            if rebuild_ai:
                self._ai = None
                self._providers = None
                self._models = None
            if rebuild_media:
                clear_cache()

        if not touched or any(key.startswith("transcription.") for key in touched):
            if self._transcription is not None:
                self._transcription.invalidate()
        if not touched or any(key.startswith("voice.") for key in touched):
            # Dropped, not merely re-probed: an API key or endpoint URL is
            # baked into a provider instance when it is constructed, so a
            # cache clear alone would leave the old credential in use until
            # the next restart.
            with self._lock:
                self._tts = None

        logger.debug("container invalidated for keys=%s", sorted(touched) or "all")
