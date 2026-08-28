"""Model registry.

**The single source of truth for model metadata.** No other module - and in
particular no UI component - may hardcode a model identifier. The frontend
renders whatever this registry reports.

Model identifiers are deliberately the CLI's *aliases* (``sonnet``, ``opus``,
``haiku``) rather than pinned version strings such as ``claude-sonnet-5``.
Aliases keep resolving to the current release, so the platform does not rot
when a new version ships. A pinned identifier can still be selected by the
user, and the whole registry can be replaced at runtime from
``config/models.json`` without touching code:

.. code-block:: json

    {
      "models": [
        {
          "id": "fable",
          "provider": "claude",
          "display_name": "Claude Fable",
          "tier": "balanced",
          "good_for": ["text_editing"],
          "rationale_fa": "...",
          "speed": 4,
          "quality": 4
        }
      ]
    }

Entries in the file are merged over the built-ins by ``id``; an entry with
``"available": false`` hides a model without deleting the history that
references it.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.core.logging import get_logger
from app.core.paths import PATHS
from app.domain.ai import ModelSpec
from app.domain.enums import AITaskType, ModelTier

logger = get_logger(__name__)

#: Provider id these built-ins belong to.
CLAUDE_PROVIDER_ID = "claude"

#: Built-in Claude models, expressed as CLI aliases.
_BUILTIN_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="sonnet",
        provider=CLAUDE_PROVIDER_ID,
        display_name="Claude Sonnet",
        tier=ModelTier.BALANCED,
        good_for=[
            AITaskType.TEXT_EDITING,
            AITaskType.TRANSCRIPTION_REFINEMENT,
            AITaskType.TRANSLATION,
            AITaskType.SUMMARIZATION,
            AITaskType.GENERAL,
        ],
        rationale_fa=(
            "تعادل مناسبی میان کیفیت و سرعت دارد و برای بیشتر کارهای متنی روزمره "
            "انتخاب مطمئنی است."
        ),
        speed=4,
        quality=4,
        context_note="پنجره متنی بزرگ؛ برای متن‌های طولانی مناسب است.",
    ),
    ModelSpec(
        id="opus",
        provider=CLAUDE_PROVIDER_ID,
        display_name="Claude Opus",
        tier=ModelTier.POWERFUL,
        good_for=[
            AITaskType.TRANSLATION,
            AITaskType.TEXT_ANALYSIS,
            AITaskType.TEXT_EDITING,
        ],
        rationale_fa=(
            "دقیق‌ترین گزینه برای کارهایی که ظرافت زبانی مهم است؛ در ترجمه و تحلیل "
            "متن بهترین نتیجه را می‌دهد، اما کندتر و پرهزینه‌تر است."
        ),
        speed=2,
        quality=5,
        context_note="برای متن‌های حساس یا تخصصی توصیه می‌شود.",
    ),
    ModelSpec(
        id="haiku",
        provider=CLAUDE_PROVIDER_ID,
        display_name="Claude Haiku",
        tier=ModelTier.FAST,
        good_for=[
            AITaskType.SUBTITLE_PROCESSING,
            AITaskType.GENERAL,
        ],
        rationale_fa=(
            "سریع‌ترین و کم‌هزینه‌ترین گزینه؛ برای کارهای ساده و تکراری مانند "
            "قطعه‌بندی زیرنویس کاملاً کافی است."
        ),
        speed=5,
        quality=3,
        context_note="برای کارهای حجیم و ساده مقرون‌به‌صرفه است.",
    ),
    ModelSpec(
        id="fable",
        provider=CLAUDE_PROVIDER_ID,
        display_name="Claude Fable",
        tier=ModelTier.BALANCED,
        # Intentionally not listed as the default pick for any task: it is
        # offered so the user can choose it, but the engine does not claim a
        # strength for it that has not been measured for these workloads.
        good_for=[],
        rationale_fa=(
            "این مدل در دسترس است و می‌توانید آن را دستی انتخاب کنید، اما به‌صورت "
            "پیش‌فرض برای هیچ کاری پیشنهاد نمی‌شود."
        ),
        speed=3,
        quality=4,
        context_note="انتخاب دستی.",
    ),
]


class ModelRegistry:
    """Holds every known model and answers lookups by id, provider and task."""

    def __init__(self, models: Iterable[ModelSpec] | None = None) -> None:
        self._models: dict[str, ModelSpec] = {}
        for spec in models if models is not None else _BUILTIN_MODELS:
            self._models[spec.id] = spec.model_copy(deep=True)

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls) -> "ModelRegistry":
        """Built-ins merged with ``config/models.json`` if that file exists."""
        registry = cls()
        registry.apply_overrides(_read_override_file())
        return registry

    def apply_overrides(self, entries: list[dict[str, Any]]) -> None:
        """Merge override entries by id. Unknown ids are added as new models."""
        for entry in entries:
            model_id = entry.get("id")
            if not model_id:
                logger.warning("ignoring model override without an id: %r", entry)
                continue
            existing = self._models.get(model_id)
            merged = {**existing.model_dump(), **entry} if existing else entry
            merged.setdefault("provider", CLAUDE_PROVIDER_ID)
            merged.setdefault("display_name", model_id)
            try:
                self._models[model_id] = ModelSpec(**merged)
            except Exception:
                logger.exception("invalid model override for %r, keeping previous", model_id)

    # -- lookups -----------------------------------------------------------

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

    def has(self, model_id: str) -> bool:
        return model_id in self._models

    def list(
        self,
        *,
        provider: str | None = None,
        include_unavailable: bool = False,
    ) -> list[ModelSpec]:
        models = [
            spec
            for spec in self._models.values()
            if (include_unavailable or spec.available)
            and (provider is None or spec.provider == provider)
        ]
        # Stable, meaningful order for selectors: strongest first, then name.
        return sorted(models, key=lambda spec: (-spec.quality, -spec.speed, spec.id))

    def for_task(self, task: AITaskType, *, provider: str | None = None) -> list[ModelSpec]:
        """Models that explicitly declare support for ``task``."""
        return [
            spec
            for spec in self.list(provider=provider)
            if task in spec.good_for
        ]

    def default_for_provider(self, provider: str) -> str | None:
        """Fallback model id when nothing better is known."""
        candidates = self.list(provider=provider)
        if not candidates:
            return None
        balanced = [spec for spec in candidates if spec.tier == ModelTier.BALANCED]
        return (balanced or candidates)[0].id


def _read_override_file() -> list[dict[str, Any]]:
    path = PATHS.config_dir / "models.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("could not read %s, using built-in models only", path)
        return []

    entries = data.get("models") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        logger.warning("%s does not contain a 'models' array, ignoring", path)
        return []
    logger.info("loaded %d model override(s) from %s", len(entries), path)
    return entries
