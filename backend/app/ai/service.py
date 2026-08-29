"""AI service facade.

The single entry point for AI work. Job handlers and API routers call this;
they never construct a provider, never rank models, and never build a prompt by
hand. That is what let adding OpenAI Codex alongside Claude be a change
confined to `app/ai/providers/codex/` plus one line in `registry.py` - see
docs/AI_PROVIDERS.md.

Responsibilities:

* choose the provider (explicit, else the configured default, else the first
  available one);
* resolve the model through the recommendation engine, honouring an explicit
  request and the user's per-task preference;
* build the system prompt for the task;
* execute and return a normalised :class:`~app.domain.ai.AIResponse`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.ai.base import AIProvider
from app.ai.models import ModelRegistry
from app.ai.prompts.library import build_system_prompt
from app.ai.recommendation import RecommendationEngine
from app.ai.registry import ProviderRegistry
from app.ai.tasks import get_profile
from app.core.errors import AIError, DependencyError, TaskNotSupportedError
from app.core.logging import get_logger
from app.domain.ai import AIRequest, AIResponse, ModelRecommendation, ProviderInfo
from app.domain.enums import AITaskType, Language
from app.process import CancelToken

logger = get_logger(__name__)

OutputCallback = Callable[[str, str], None]


class AIService:
    """Facade over the provider registry, model registry and prompt system."""

    def __init__(
        self,
        *,
        providers: ProviderRegistry,
        models: ModelRegistry,
        default_provider: str = "claude",
        model_preferences: dict[str, str] | None = None,
    ) -> None:
        self.providers = providers
        self.models = models
        self.engine = RecommendationEngine(models)
        self.default_provider = default_provider
        self.model_preferences = model_preferences or {}

    # -- discovery ---------------------------------------------------------

    def list_providers(self, *, refresh: bool = False) -> list[ProviderInfo]:
        return self.providers.info_all(refresh=refresh)

    def resolve_provider_id(self, requested: str | None = None) -> str:
        """Pick a provider id, preferring one that can actually run."""
        if requested:
            if not self.providers.has(requested):
                from app.core.errors import ProviderNotFoundError

                raise ProviderNotFoundError(f"unknown provider {requested!r}")
            return requested

        if self.providers.has(self.default_provider):
            return self.default_provider

        available = self.providers.first_available()
        if available:
            return available
        return self.providers.ids[0] if self.providers.ids else self.default_provider

    def recommend(
        self, task: AITaskType, *, provider: str | None = None
    ) -> ModelRecommendation:
        """What the UI shows under "مدل پیشنهادی"."""
        provider_id = self.resolve_provider_id(provider)
        return self.engine.recommend(
            task, provider=provider_id, user_preferences=self.model_preferences
        )

    # -- execution ---------------------------------------------------------

    def run(
        self,
        *,
        task: AITaskType,
        prompt: str,
        content: str | None = None,
        language: Language | None = None,
        provider: str | None = None,
        model: str | None = None,
        extra_system_rules: list[str] | None = None,
        attachments: list[Path] | None = None,
        timeout_seconds: int | None = None,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> AIResponse:
        """Run one AI task.

        ``prompt`` is the instruction; ``content`` is the material to operate
        on. They are kept separate and joined with an explicit delimiter so a
        transcript containing something that looks like an instruction cannot be
        mistaken for one.
        """
        provider_id = self.resolve_provider_id(provider)
        provider_impl = self.providers.get(provider_id)

        info = self.providers.info(provider_id)
        if not info.available:
            raise DependencyError(
                f"provider {provider_id!r} is not available: {info.unavailable_reason}",
                user_message=info.unavailable_reason
                or "ارائه‌دهنده هوش مصنوعی در دسترس نیست.",
            )

        if task not in provider_impl.supported_tasks:
            raise TaskNotSupportedError(
                f"provider {provider_id!r} does not support task {task.value!r}",
                details={"task": task.value, "provider": provider_id},
            )

        resolved_model = self.engine.resolve(
            task,
            provider=provider_id,
            requested_model=model,
            user_preferences=self.model_preferences,
        )

        profile = get_profile(task)
        full_prompt = _compose(prompt, content)
        self._guard_length(full_prompt, profile.max_input_chars)

        request = AIRequest(
            task=task,
            prompt=full_prompt,
            system_prompt=build_system_prompt(
                task, language=language, extra_rules=extra_system_rules
            ),
            model=resolved_model,
            attachments=attachments or [],
            timeout_seconds=timeout_seconds,
        )

        logger.info(
            "AI task=%s provider=%s model=%s chars=%d",
            task.value,
            provider_id,
            resolved_model,
            len(full_prompt),
        )

        response = self._execute(
            provider_impl, request, on_output=on_output, cancel_token=cancel_token
        )
        if profile.expects_raw_text:
            response.text = strip_conversational_framing(response.text)
        return response

    @staticmethod
    def _execute(
        provider: AIProvider,
        request: AIRequest,
        *,
        on_output: OutputCallback | None,
        cancel_token: CancelToken | None,
    ) -> AIResponse:
        return provider.generate(
            request, on_output=on_output, cancel_token=cancel_token
        )

    @staticmethod
    def _guard_length(text: str, limit: int) -> None:
        if len(text) > limit:
            raise AIError(
                f"input is {len(text)} characters, task limit is {limit}",
                user_message="متن ورودی برای این عملیات بیش از حد بلند است.",
                hint="متن را به بخش‌های کوچک‌تر تقسیم کنید و هر بخش را جداگانه پردازش کنید.",
                details={"length": len(text), "limit": limit},
            )


# --------------------------------------------------------------------------
# Prompt assembly and output cleanup
# --------------------------------------------------------------------------

#: Delimiter separating the instruction from the material. Explicit boundaries
#: are what stop a transcript's own words from reading as an instruction.
_CONTENT_OPEN = "<<<TEXT_START>>>"
_CONTENT_CLOSE = "<<<TEXT_END>>>"


def _compose(instruction: str, content: str | None) -> str:
    instruction = instruction.strip()
    if not content or not content.strip():
        return instruction
    return (
        f"{instruction}\n\n"
        f"{_CONTENT_OPEN}\n{content.strip()}\n{_CONTENT_CLOSE}\n\n"
        "Return only the transformed text, without the delimiter lines."
    )


#: Openers a chat-tuned model reaches for despite the system prompt.
_FRAMING_PREFIXES = (
    "here is the",
    "here's the",
    "sure,",
    "sure!",
    "certainly,",
    "of course,",
    "بفرمایید",
    "در ادامه",
    "متن اصلاح‌شده",
    "متن ویرایش‌شده",
    "ترجمه متن",
    "این هم",
)


def strip_conversational_framing(text: str) -> str:
    """Remove leftover chat framing and stray delimiters from a raw-text result.

    Conservative on purpose: a preamble is only dropped when it is a short
    first line that ends with a colon, so a genuine first sentence is never
    eaten.
    """
    cleaned = text.strip()
    if not cleaned:
        return cleaned

    cleaned = cleaned.replace(_CONTENT_OPEN, "").replace(_CONTENT_CLOSE, "").strip()

    lines = cleaned.splitlines()
    if len(lines) > 1:
        first = lines[0].strip()
        lowered = first.lower()
        looks_like_preamble = (
            len(first) <= 80
            and first.endswith(":")
            and any(lowered.startswith(prefix) for prefix in _FRAMING_PREFIXES)
        )
        if looks_like_preamble:
            cleaned = "\n".join(lines[1:]).strip()

    # A model that fenced the whole answer: unwrap a single outer fence.
    if cleaned.startswith("```") and cleaned.endswith("```"):
        inner = cleaned[3:-3]
        newline = inner.find("\n")
        if newline != -1 and len(inner[:newline].strip()) < 20:
            inner = inner[newline + 1 :]
        cleaned = inner.strip()

    return cleaned
