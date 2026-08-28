"""AI request/response contracts.

These are provider-neutral on purpose: a request describes *what* is wanted,
never *how* a particular CLI expresses it. Everything provider-specific lives
behind :class:`app.ai.base.AIProvider`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import AITaskType, ModelTier, ProviderCapability


class ModelSpec(BaseModel):
    """One model offered by one provider.

    Model *identifiers* are configuration, not constants: the CLI accepts
    aliases such as ``sonnet`` that keep working as the underlying versions
    change, and the registry can be overridden from ``config/models.json``.
    """

    id: str
    provider: str
    display_name: str
    tier: ModelTier = ModelTier.BALANCED
    #: Tasks this model is a good fit for, best first.
    good_for: list[AITaskType] = Field(default_factory=list)
    #: Persian sentence explaining why the engine would pick this model.
    rationale_fa: str = ""
    #: Relative speed/cost hints, 1 (slowest/most expensive) to 5.
    speed: int = Field(default=3, ge=1, le=5)
    quality: int = Field(default=3, ge=1, le=5)
    context_note: str = ""
    #: Set false to hide a retired model without deleting its history.
    available: bool = True


class ModelRecommendation(BaseModel):
    """What the recommendation engine returns for a task."""

    task: AITaskType
    provider: str
    recommended_model: str
    #: Persian explanation shown under the selector.
    reason_fa: str
    #: Every model the user may switch to for this task, recommended first.
    alternatives: list[ModelSpec] = Field(default_factory=list)
    #: True when the value came from the user's saved per-task preference
    #: rather than from the engine's own ranking.
    from_user_preference: bool = False


class AIRequest(BaseModel):
    """Provider-neutral description of one AI call."""

    task: AITaskType
    prompt: str
    system_prompt: str | None = None
    model: str | None = None
    #: Files to attach. Providers that cannot take files raise
    #: TaskNotSupportedError rather than silently dropping them.
    attachments: list[Path] = Field(default_factory=list)
    #: Working directory for the provider process. Defaults to the project dir.
    working_dir: Path | None = None
    timeout_seconds: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


class AIResponse(BaseModel):
    """Normalised result of one AI call."""

    text: str
    model: str
    provider: str
    duration_seconds: float = 0.0
    exit_code: int | None = None
    #: Raw stderr, kept for the job log. Never shown as an error message.
    stderr: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderInfo(BaseModel):
    """What the UI needs to render a provider in the selector."""

    id: str
    display_name: str
    #: False when the underlying tool is not installed. The UI greys it out and
    #: shows ``unavailable_reason`` instead of failing at execution time.
    available: bool = False
    unavailable_reason: str | None = None
    version: str | None = None
    executable_path: str | None = None
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    supported_tasks: list[AITaskType] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
