"""Model recommendation engine.

One place decides which model to use for a task. Everything else - the API,
the job handlers, the UI - asks this engine and then lets the user override the
answer.

Resolution order:

1. **User preference for the task.** Set in Settings, stored under
   ``ai.model_by_task``. Wins outright and is reported back as
   ``from_user_preference`` so the UI can say so.
2. **Explicit endorsement.** Models that list the task in ``good_for`` are
   scored and the best one wins.
3. **Tier fallback.** No endorsement anywhere: pick the best model in the
   task's ``preferred_tier``, then any model at all.

Scoring blends a model's quality and speed ratings using the weights on the
task profile, so a translation task ranks Opus above Haiku while subtitle
segmentation ranks them the other way round.
"""

from __future__ import annotations

from app.ai.models import ModelRegistry
from app.ai.tasks import get_profile
from app.core.errors import ModelNotFoundError
from app.core.logging import get_logger
from app.domain.ai import ModelRecommendation, ModelSpec
from app.domain.enums import AITaskType

logger = get_logger(__name__)


class RecommendationEngine:
    """Ranks models for tasks. Stateless apart from the registry it reads."""

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    # -- scoring -----------------------------------------------------------

    @staticmethod
    def score(spec: ModelSpec, task: AITaskType) -> float:
        """Blend quality and speed by the task's weights, 0.0 - 1.0.

        A model that explicitly declares the task gets a decisive bonus, so an
        endorsed model always outranks an unendorsed one with better raw
        numbers.
        """
        profile = get_profile(task)
        normalised_quality = spec.quality / 5.0
        normalised_speed = spec.speed / 5.0
        base = (
            profile.quality_weight * normalised_quality
            + profile.speed_weight * normalised_speed
        )
        endorsement = 1.0 if task in spec.good_for else 0.0
        tier_match = 0.15 if spec.tier == profile.preferred_tier else 0.0
        return base + endorsement + tier_match

    # -- recommendation ----------------------------------------------------

    def recommend(
        self,
        task: AITaskType,
        *,
        provider: str,
        user_preferences: dict[str, str] | None = None,
    ) -> ModelRecommendation:
        """Return the recommended model plus every alternative for ``task``."""
        candidates = self.registry.list(provider=provider)
        if not candidates:
            raise ModelNotFoundError(
                f"provider {provider!r} has no available models",
                details={"provider": provider},
            )

        ranked = sorted(
            candidates, key=lambda spec: self.score(spec, task), reverse=True
        )

        preferred_id = (user_preferences or {}).get(task.value)
        if preferred_id and self.registry.has(preferred_id):
            preferred = self.registry.get(preferred_id)
            assert preferred is not None
            if preferred.provider == provider and preferred.available:
                return ModelRecommendation(
                    task=task,
                    provider=provider,
                    recommended_model=preferred.id,
                    reason_fa=(
                        f"این مدل را خودتان برای «{get_profile(task).label_fa}» "
                        "به‌عنوان پیش‌فرض انتخاب کرده‌اید."
                    ),
                    alternatives=_reorder(ranked, preferred.id),
                    from_user_preference=True,
                )
            logger.info(
                "ignoring model preference %r for task %s: not available for provider %s",
                preferred_id,
                task.value,
                provider,
            )

        best = ranked[0]
        return ModelRecommendation(
            task=task,
            provider=provider,
            recommended_model=best.id,
            reason_fa=self.explain(best, task),
            alternatives=ranked,
            from_user_preference=False,
        )

    @staticmethod
    def explain(spec: ModelSpec, task: AITaskType) -> str:
        """Persian sentence explaining why ``spec`` suits ``task``.

        Built from the model's own rationale plus a task-specific clause, so
        the text stays correct when the registry is overridden from
        ``config/models.json``.
        """
        profile = get_profile(task)
        if task in spec.good_for:
            lead = f"برای «{profile.label_fa}» گزینه پیشنهادی است."
        elif spec.tier == profile.preferred_tier:
            lead = (
                f"مدل اختصاصی برای «{profile.label_fa}» تعریف نشده است، اما این مدل "
                "در رده مناسبی قرار دارد."
            )
        else:
            lead = f"در حال حاضر مناسب‌ترین گزینه در دسترس برای «{profile.label_fa}» است."

        rationale = spec.rationale_fa.strip()
        return f"{lead} {rationale}".strip() if rationale else lead

    def resolve(
        self,
        task: AITaskType,
        *,
        provider: str,
        requested_model: str | None = None,
        user_preferences: dict[str, str] | None = None,
    ) -> str:
        """Return the model id to actually execute with.

        A user-supplied ``requested_model`` is honoured whenever it exists and
        belongs to the provider; otherwise the recommendation is used. This is
        the function job handlers call - they never rank models themselves.
        """
        if requested_model:
            spec = self.registry.get(requested_model)
            if spec is None:
                raise ModelNotFoundError(
                    f"unknown model {requested_model!r}",
                    details={"model": requested_model},
                )
            if spec.provider != provider:
                raise ModelNotFoundError(
                    f"model {requested_model!r} belongs to provider {spec.provider!r},"
                    f" not {provider!r}",
                    details={"model": requested_model, "provider": provider},
                )
            return spec.id

        return self.recommend(
            task, provider=provider, user_preferences=user_preferences
        ).recommended_model


def _reorder(models: list[ModelSpec], first_id: str) -> list[ModelSpec]:
    """Move ``first_id`` to the head of the list, preserving the rest."""
    head = [spec for spec in models if spec.id == first_id]
    tail = [spec for spec in models if spec.id != first_id]
    return head + tail
