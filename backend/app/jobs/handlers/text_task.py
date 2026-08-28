"""Job handler: AI text processing (editing, translation, analysis, custom).

Features 3 and 4. One handler serves every text transformation because they
differ only in task type and prompt - which is exactly what the task profile and
prompt library exist to express. Adding "summarise" or "generate a title" later
needs no new handler.

The critical guarantee, and the reason this returns a *new* document rather than
mutating one: **the AI never overwrites the user's text**. The result is stored
as a new document that points back at its source, and the UI shows both side by
side. Applying the result is a separate, explicit action.
"""

from __future__ import annotations

from app.ai.prompts.library import (
    generic_translation_instruction,
    translation_prompt,
)
from app.ai.prompts.renderer import render_template
from app.ai.tasks import get_profile
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.document import DocumentCreate
from app.domain.enums import AITaskType, DocumentType, JobType, Language
from app.jobs.context import JobContext
from app.jobs.registry import register_handler

logger = get_logger(__name__)

#: Which document type a completed task produces.
_RESULT_TYPE: dict[AITaskType, DocumentType] = {
    AITaskType.TRANSLATION: DocumentType.TRANSLATION,
    AITaskType.TEXT_EDITING: DocumentType.EDITED,
    AITaskType.TRANSCRIPTION_REFINEMENT: DocumentType.TRANSCRIPT_REFINED,
    AITaskType.SUMMARIZATION: DocumentType.NOTE,
    AITaskType.TEXT_ANALYSIS: DocumentType.NOTE,
    AITaskType.SUBTITLE_PROCESSING: DocumentType.NOTE,
    AITaskType.GENERAL: DocumentType.EDITED,
}


@register_handler(JobType.TEXT_TASK)
def handle_text_task(ctx: JobContext) -> dict:
    """Run one AI text task and save the result as a new document.

    Input:  ``task``, plus either ``document_id`` or ``content``;
            optional ``prompt``, ``model``, ``provider``,
            ``source_language``, ``target_language``, ``save`` (default true)
    Output: ``result``, ``document_id``, provider/model actually used
    """
    task = _parse_task(ctx.input.get("task"))
    profile = get_profile(task)

    content, source_document_id = _resolve_content(ctx)
    if not content.strip():
        raise ValidationError(
            "no content supplied for text task",
            user_message="متنی برای پردازش وجود ندارد.",
        )

    source_language = _parse_language(
        ctx.input.get("source_language"), ctx.services.settings.get("ai.default_language")
    )
    target_language = _parse_language(ctx.input.get("target_language"), source_language.value)

    instruction = _build_instruction(ctx, task, source_language, target_language)

    ctx.set_progress(0.05, f"در حال آماده‌سازی «{profile.label_fa}»")
    ctx.system(f"task={task.value} chars={len(content)}")

    ctx.set_progress(0.15, "در حال اجرای هوش مصنوعی")
    response = ctx.services.ai.run(
        task=task,
        prompt=instruction,
        content=content,
        language=target_language if task is AITaskType.TRANSLATION else source_language,
        provider=ctx.input.get("provider") or None,
        model=ctx.input.get("model") or None,
        on_output=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )
    ctx.set_model(response.provider, response.model)

    ctx.set_progress(0.9, "در حال ذخیره نتیجه")

    result_language = target_language if task is AITaskType.TRANSLATION else source_language
    document_id: str | None = None

    # The caller can ask for a preview only; the text editor does this so a
    # rejected suggestion never leaves a document behind.
    if bool(ctx.input.get("save", True)):
        document = ctx.services.documents.create(
            ctx.project_id,
            DocumentCreate(
                type=_RESULT_TYPE.get(task, DocumentType.EDITED),
                title=_title_for(task, source_language, target_language),
                content=response.text,
                language=result_language,
                source_document_id=source_document_id,
            ),
        )
        document_id = document.id
        ctx.services.projects.touch(ctx.project_id)

    ctx.system(
        f"completed with {response.provider}/{response.model} "
        f"in {response.duration_seconds:.1f}s ({len(response.text)} chars)"
    )
    ctx.set_progress(1.0, f"«{profile.label_fa}» کامل شد")

    return {
        "task": task.value,
        "result": response.text,
        "document_id": document_id,
        "source_document_id": source_document_id,
        "provider": response.provider,
        "model": response.model,
        "language": result_language.value,
        "input_chars": len(content),
        "output_chars": len(response.text),
        "duration_seconds": round(response.duration_seconds, 2),
    }


# --------------------------------------------------------------------------
# Input resolution
# --------------------------------------------------------------------------


def _parse_task(value) -> AITaskType:
    try:
        return AITaskType(str(value))
    except ValueError as exc:
        raise ValidationError(
            f"unknown AI task: {value!r}",
            user_message="نوع پردازش انتخاب‌شده معتبر نیست.",
            details={"valid": [task.value for task in AITaskType]},
        ) from exc


def _parse_language(value, fallback: str) -> Language:
    try:
        return Language(str(value or fallback))
    except ValueError as exc:
        raise ValidationError(
            f"unsupported language: {value!r}",
            user_message="زبان انتخاب‌شده پشتیبانی نمی‌شود.",
            details={"supported": [lang.value for lang in Language]},
        ) from exc


def _resolve_content(ctx: JobContext) -> tuple[str, str | None]:
    """Return ``(content, source_document_id)`` from either input form."""
    document_id = ctx.input.get("document_id")
    if document_id:
        document = ctx.services.documents.get(str(document_id))
        if document is None:
            raise NotFoundError(
                f"document {document_id!r} not found",
                user_message="سند انتخاب‌شده پیدا نشد.",
            )
        return document.content, document.id
    return str(ctx.input.get("content") or ""), None


def _build_instruction(
    ctx: JobContext,
    task: AITaskType,
    source_language: Language,
    target_language: Language,
) -> str:
    """Pick the prompt: the user's own, else the right built-in template."""
    custom = (ctx.input.get("prompt") or "").strip()
    if custom:
        variables = ctx.input.get("variables") or {}
        return render_template(custom, variables) if variables else custom

    if task is AITaskType.TRANSLATION:
        if source_language == target_language:
            raise ValidationError(
                "source and target languages are the same",
                user_message="زبان مبدأ و مقصد یکسان است.",
                hint="یک زبان مقصد متفاوت انتخاب کنید.",
            )
        template = translation_prompt(source_language, target_language)
        if template is not None:
            return template.body
        # A pair with no dedicated template still works.
        return generic_translation_instruction(source_language, target_language)

    from app.ai.prompts.library import list_builtins  # local import: avoids cycle

    candidates = list_builtins(task)
    if candidates:
        return candidates[0].body

    raise ValidationError(
        f"no prompt available for task {task.value!r}",
        user_message="برای این نوع پردازش دستوری تعریف نشده است.",
        hint="یک دستور دلخواه بنویسید.",
    )


def _title_for(task: AITaskType, source: Language, target: Language) -> str:
    if task is AITaskType.TRANSLATION:
        return f"ترجمه ({source.native_name} به {target.native_name})"
    return get_profile(task).label_fa
