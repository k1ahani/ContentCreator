"""Job handler: audio to text.

Feature 2, and the one place where the platform's honest division of labour is
most visible. This runs in two stages:

1. **Speech recognition** (``app/transcription/``) turns audio into text with
   real, measured timestamps. No language model can do this - and the subtitle
   timeline depends on those timestamps being real.
2. **LLM refinement** (``app/ai/``, ``AITaskType.TRANSCRIPTION_REFINEMENT``)
   optionally cleans up punctuation, spelling and Persian normalisation. This
   is genuine Claude work through the provider architecture, and it is what the
   model selector on the transcription page controls.

Both the raw and the refined transcript are saved as separate documents, so the
user can always see what the engine actually heard. Stage 2 is skipped when the
user turns it off or when no AI provider is available; the raw transcript is
still saved and the job still succeeds.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import AppError, NotFoundError, ProcessCancelledError
from app.core.logging import get_logger
from app.domain.document import DocumentCreate
from app.domain.enums import AITaskType, DocumentType, JobType, Language
from app.domain.transcription import TranscriptionOptions
from app.jobs.context import JobContext
from app.jobs.registry import register_handler
from app.ai.prompts.library import get_builtin

logger = get_logger(__name__)


@register_handler(JobType.TRANSCRIBE)
def handle_transcribe(ctx: JobContext) -> dict:
    """Transcribe an audio asset, then optionally refine it with the LLM.

    Input:  ``asset_id``, optional ``language``, ``model_size``, ``refine``,
            ``ai_model``, ``initial_prompt``
    Output: ``document_id``, ``raw_document_id``, ``text``, segment data
    """
    settings = ctx.services.settings
    asset_id = str(ctx.require("asset_id"))

    asset = ctx.services.assets.get(asset_id)
    if asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found",
            user_message="فایل صوتی انتخاب‌شده در این پروژه پیدا نشد.",
        )

    language = Language(ctx.input.get("language") or settings.get("transcription.language"))
    options = TranscriptionOptions(
        language=language,
        model_size=str(ctx.input.get("model_size") or settings.get("transcription.model_size")),
        auto_detect_language=bool(ctx.input.get("auto_detect_language", False)),
        vad_filter=bool(ctx.input.get("vad_filter", settings.get("transcription.vad_filter"))),
        initial_prompt=ctx.input.get("initial_prompt") or None,
    )

    engine_id = str(ctx.input.get("engine") or settings.get("transcription.engine"))
    engine = ctx.services.transcription.get(engine_id)

    ctx.set_progress(0.0, "در حال آماده‌سازی موتور تبدیل گفتار به متن")
    ctx.system(f"engine={engine_id} model={options.model_size} language={language.value}")

    # -- stage 1: speech recognition ---------------------------------------

    result = engine.transcribe(
        Path(asset.path),
        options,
        on_progress=_scaled_progress(ctx, ceiling=0.75),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )

    if not result.text.strip():
        ctx.system("no speech detected in the audio")
        raise AppError(
            "transcription produced no text",
            user_message="هیچ گفتاری در این فایل صوتی تشخیص داده نشد.",
            hint="بررسی کنید که فایل صوتی واقعاً شامل صحبت باشد.",
        )

    raw_document = ctx.services.documents.create(
        ctx.project_id,
        DocumentCreate(
            type=DocumentType.TRANSCRIPT_RAW,
            title=f"رونوشت خام - {asset.original_filename}",
            content=result.text,
            language=language,
        ),
    )
    ctx.system(
        f"raw transcript saved: {len(result.segments)} segments, "
        f"{result.word_count} words, {result.processing_seconds:.1f}s"
    )

    # Segment timings are what the subtitle timeline is built from later.
    segments_payload = [
        {
            "index": segment.index,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text,
        }
        for segment in result.segments
    ]

    output = {
        "raw_document_id": raw_document.id,
        "document_id": raw_document.id,
        "text": result.text,
        "language": language.value,
        "detected_language": result.detected_language,
        "engine": result.engine,
        "engine_model": result.model,
        "segment_count": len(result.segments),
        "segments": segments_payload,
        "duration_seconds": result.duration_seconds,
        "processing_seconds": round(result.processing_seconds, 2),
        "refined": False,
    }

    # -- stage 2: LLM refinement -------------------------------------------

    should_refine = bool(ctx.input.get("refine", settings.get("transcription.auto_refine")))
    if not should_refine:
        ctx.set_progress(1.0, "تبدیل گفتار به متن کامل شد")
        ctx.services.projects.touch(ctx.project_id)
        return output

    ctx.set_progress(0.78, "در حال بازبینی متن با هوش مصنوعی")

    try:
        refined_text = _refine(ctx, result.text, language)
    except ProcessCancelledError:
        raise
    except AppError as exc:
        # Refinement is a bonus stage: never lose a good transcript because the
        # AI pass failed. Report it and return the raw result.
        logger.warning("refinement failed for job %s: %s", ctx.job.id, exc.message)
        ctx.system(f"refinement skipped: {exc.user_message}")
        ctx.set_progress(1.0, "تبدیل گفتار به متن کامل شد (بدون بازبینی)")
        output["refine_error"] = exc.user_message
        ctx.services.projects.touch(ctx.project_id)
        return output

    refined_document = ctx.services.documents.create(
        ctx.project_id,
        DocumentCreate(
            type=DocumentType.TRANSCRIPT_REFINED,
            title=f"رونوشت بازبینی‌شده - {asset.original_filename}",
            content=refined_text,
            language=language,
            source_document_id=raw_document.id,
        ),
    )

    ctx.services.projects.touch(ctx.project_id)
    ctx.set_progress(1.0, "تبدیل گفتار به متن کامل شد")

    output.update(
        {
            "document_id": refined_document.id,
            "refined_document_id": refined_document.id,
            "text": refined_text,
            "refined": True,
        }
    )
    return output


def _refine(ctx: JobContext, text: str, language: Language) -> str:
    """Run the LLM refinement pass through the provider architecture."""
    template = get_builtin("transcript_refine")
    assert template is not None  # part of the built-in library

    requested_model = ctx.input.get("ai_model") or None
    response = ctx.services.ai.run(
        task=AITaskType.TRANSCRIPTION_REFINEMENT,
        prompt=template.body,
        content=text,
        language=language,
        model=requested_model,
        on_output=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )
    ctx.set_model(response.provider, response.model)
    ctx.system(f"refined with {response.provider}/{response.model} in {response.duration_seconds:.1f}s")
    return response.text


def _scaled_progress(ctx: JobContext, *, ceiling: float):
    """Map an engine's 0-1 progress into 0-``ceiling`` of the job's bar.

    Transcription is most of the work but not all of it, so its progress must
    not reach 100% while the refinement stage is still to come.
    """

    def callback(fraction: float | None, stage: str) -> None:
        ctx.set_progress(None if fraction is None else fraction * ceiling, stage)

    return callback
