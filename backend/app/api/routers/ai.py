"""AI discovery endpoints.

Everything the UI needs to render provider and model selectors comes from here,
so no model identifier or provider name is ever hardcoded in the frontend. This
is the API surface that makes requirement "centralise model information" real.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.ai.prompts.library import list_builtins
from app.ai.tasks import all_profiles, get_profile
from app.api.deps import Container
from app.api.schemas.responses import ListResponse, PromptInfo, TaskInfo
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.domain.ai import ModelRecommendation, ModelSpec, ProviderInfo
from app.domain.enums import AITaskType, Language
from app.domain.tts import VoiceSpec
from app.transcription.base import TranscriptionProviderInfo
from app.tts.base import TTSProviderInfo
from app.tts.preview import build_voice_preview

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


# --------------------------------------------------------------------------
# Providers and models
# --------------------------------------------------------------------------


@router.get("/providers", response_model=ListResponse[ProviderInfo])
def list_providers(
    container: Container,
    refresh: Annotated[bool, Query()] = False,
) -> ListResponse[ProviderInfo]:
    """Text providers and whether each can run right now.

    Version 1 returns Claude only. A provider that is registered but whose tool
    is missing appears with ``available=false`` and a Persian reason, rather
    than being hidden - the user needs to know *why* it cannot be used.
    """
    providers = container.ai.list_providers(refresh=refresh)
    return ListResponse(items=providers, total=len(providers))


@router.get("/models", response_model=ListResponse[ModelSpec])
def list_models(
    container: Container,
    provider: Annotated[str | None, Query()] = None,
    task: Annotated[AITaskType | None, Query()] = None,
) -> ListResponse[ModelSpec]:
    """Available models, optionally filtered by provider or suited task."""
    registry = container.models
    models = (
        registry.for_task(task, provider=provider)
        if task is not None
        else registry.list(provider=provider)
    )
    return ListResponse(items=models, total=len(models))


@router.get("/recommend", response_model=ModelRecommendation)
def recommend_model(
    container: Container,
    task: Annotated[AITaskType, Query()],
    provider: Annotated[str | None, Query()] = None,
) -> ModelRecommendation:
    """The recommended model for a task, with its Persian rationale.

    This is what the "مدل پیشنهادی" panel renders. ``alternatives`` is the full
    override list, recommended first, and ``from_user_preference`` tells the UI
    whether the choice came from the user's own saved setting.
    """
    return container.ai.recommend(task, provider=provider)


@router.get("/tasks", response_model=ListResponse[TaskInfo])
def list_tasks() -> ListResponse[TaskInfo]:
    """AI task types with their Persian labels and input limits."""
    items = [
        TaskInfo(
            id=profile.task.value,
            label_fa=profile.label_fa,
            description_fa=profile.description_fa,
            preferred_tier=profile.preferred_tier.value,
            max_input_chars=profile.max_input_chars,
        )
        for profile in all_profiles()
    ]
    return ListResponse(items=items, total=len(items))


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


@router.get("/prompts", response_model=ListResponse[PromptInfo])
def list_prompts(
    container: Container,
    task: Annotated[AITaskType | None, Query()] = None,
) -> ListResponse[PromptInfo]:
    """Built-in prompt templates plus any the user has saved."""
    items = [
        PromptInfo(
            id=template.id,
            name_fa=template.name_fa,
            task=template.task.value,
            category=template.category,
            description_fa=template.description_fa,
            body=template.body,
            variables=list(template.declared_variables()),
            is_builtin=True,
        )
        for template in list_builtins(task)
    ]

    for stored in container.prompts.list(task=task):
        items.append(
            PromptInfo(
                id=stored["id"],
                name_fa=stored["name"],
                task=stored["task"],
                category=stored["category"],
                description_fa="",
                body=stored["body"],
                variables=stored["variables"],
                is_builtin=stored["is_builtin"],
            )
        )

    return ListResponse(items=items, total=len(items))


# --------------------------------------------------------------------------
# Transcription engines
# --------------------------------------------------------------------------


@router.get("/transcription/engines", response_model=ListResponse[TranscriptionProviderInfo])
def list_transcription_engines(
    container: Container,
    refresh: Annotated[bool, Query()] = False,
) -> ListResponse[TranscriptionProviderInfo]:
    """Speech-recognition engines, their models and whether weights are present.

    Kept under ``/api/ai`` because it is one page in the UI, but note these are
    a separate provider layer - see docs/AI_SYSTEM.md for why.
    """
    engines = container.transcription.info_all(refresh=refresh)
    return ListResponse(items=engines, total=len(engines))


# --------------------------------------------------------------------------
# Speech synthesis
# --------------------------------------------------------------------------


@router.get("/tts/providers", response_model=ListResponse[TTSProviderInfo])
def list_tts_providers(
    container: Container,
    refresh: Annotated[bool, Query()] = False,
) -> ListResponse[TTSProviderInfo]:
    providers = container.tts.info_all(refresh=refresh)
    return ListResponse(items=providers, total=len(providers))


@router.get("/tts/voices", response_model=ListResponse[VoiceSpec])
def list_voices(
    container: Container,
    provider: Annotated[str | None, Query()] = None,
    language: Annotated[Language | None, Query()] = None,
) -> ListResponse[VoiceSpec]:
    """Voices from every available provider, optionally filtered."""
    voices = container.tts.list_voices(provider_id=provider, language=language)
    return ListResponse(items=voices, total=len(voices))


@router.get(
    "/tts/voices/{voice_id:path}/preview",
    responses={200: {"content": {"audio/mpeg": {}}, "description": "A short spoken sample"}},
)
def preview_voice(
    voice_id: str,
    container: Container,
    text: Annotated[str | None, Query(max_length=300)] = None,
) -> Response:
    """A short audio sample of one voice, so it can be auditioned before use.

    Choosing between forty voices by reading their descriptions is guesswork;
    this is what makes the choice actual listening. Two sources, in order:

    1. **A sample the provider already hosts** (``VoiceSpec.preview_url``).
       Free, instant, and spends none of the user's paid quota - which is why
       it is preferred whenever a provider publishes one.
    2. **A real synthesis of one short sentence**, for every provider that
       does not. The result is cached on disk keyed by voice and text, so
       clicking the same voice twice costs one synthesis, not two.

    ``voice_id`` is declared as a path parameter so ids containing a slash or
    colon (the API-backed providers compose ids - see
    ``app/tts/providers/elevenlabs.py``) survive routing intact.
    """
    voice = container.tts.find_voice(voice_id)
    if voice is None:
        raise NotFoundError(
            f"no provider offers voice {voice_id!r}",
            user_message="صدای انتخاب‌شده در دسترس نیست.",
            hint="صدای دیگری از فهرست انتخاب کنید.",
        )

    settings = container.settings
    sample_text = (text or "").strip() or str(
        settings.get(f"voice.preview_text_{voice.language.value}") or ""
    ).strip()
    if not sample_text:
        raise ValidationError(
            f"no preview text configured for language {voice.language.value!r}",
            user_message="متنی برای نمونه صدا تنظیم نشده است.",
            hint="متن نمونه را از «تنظیمات ← صدا» وارد کنید.",
        )

    audio, media_type = build_voice_preview(
        container.tts, voice, sample_text, cache_dir=PATHS.storage / ".tts-temp" / "previews"
    )
    return Response(
        content=audio,
        media_type=media_type,
        # The sample for a given voice and text never changes, and the voice
        # selector re-requests it every time the user clicks play.
        headers={"Cache-Control": "private, max-age=86400"},
    )
