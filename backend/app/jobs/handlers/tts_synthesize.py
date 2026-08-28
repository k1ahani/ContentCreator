"""Job handler: text to speech.

Feature 6. Accepts a structured speech script - alternating text and pause
segments - and produces a single audio asset. Pauses are real silence of the
exact requested length; see ``app/tts/assembler.py``.
"""

from __future__ import annotations

from app.core.errors import NotFoundError, ValidationError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.timecode import format_clock
from app.domain.enums import AssetType, JobType, Language, SpeakingStyle, SpeechSegmentKind
from app.domain.tts import (
    PauseSegment,
    SpeechOptions,
    SpeechScript,
    TextSegment,
)
from app.jobs.context import JobContext
from app.jobs.registry import register_handler
from app.tts.assembler import assemble_speech

logger = get_logger(__name__)


@register_handler(JobType.TTS_SYNTHESIZE)
def handle_tts_synthesize(ctx: JobContext) -> dict:
    """Synthesise a speech script into an audio asset.

    Input:  ``segments`` (list of ``{kind, text|seconds}``) or ``document_id``
            / ``text``; optional ``voice_id``, ``language``, ``style``,
            ``rate``, ``pitch``, ``output_format``
    Output: ``asset_id``, ``path``, duration and size
    """
    settings = ctx.services.settings

    options = _build_options(ctx)
    segments = _build_segments(ctx)

    try:
        script = SpeechScript(segments=segments, options=options)
    except Exception as exc:
        raise ValidationError(
            f"invalid speech script: {exc}",
            user_message="متنی برای تبدیل به گفتار وجود ندارد.",
        ) from exc

    provider = ctx.services.tts.provider_for_voice(options.voice_id)
    info = ctx.services.tts.info(provider.id)
    if not info.available:
        raise ValidationError(
            f"TTS provider {provider.id!r} is unavailable",
            user_message=info.unavailable_reason or "موتور تولید گفتار در دسترس نیست.",
            hint=info.hint,
        )

    text_count = sum(1 for s in segments if s.kind == SpeechSegmentKind.TEXT)
    pause_count = len(segments) - text_count

    ctx.set_progress(0.0, "در حال آماده‌سازی تولید گفتار")
    ctx.system(
        f"provider={provider.id} voice={options.voice_id} style={options.style.value} "
        f"rate={options.rate} segments={text_count} pauses={pause_count}"
    )
    ctx.set_model(provider.id, options.voice_id)

    tools = ctx.services.ffmpeg()

    result = assemble_speech(
        script,
        provider=provider,
        tools=tools,
        output_dir=ctx.project_dir("voice"),
        temp_root=ctx.project_dir("temp"),
        output_stem=str(ctx.input.get("name") or f"voice-{new_id()[:8]}"),
        on_progress=ctx.staged_progress_callback(),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )

    asset = ctx.services.assets.create(
        project_id=ctx.project_id,
        type=AssetType.VOICE,
        path=result.output_path,
        original_filename=result.output_path.name,
        size_bytes=result.size_bytes,
        format=options.output_format,
        duration_seconds=result.duration_seconds,
        metadata={
            "provider": provider.id,
            "voice_id": options.voice_id,
            "language": options.language.value,
            "style": options.style.value,
            "rate": options.rate,
            "pitch": options.pitch,
            "segment_count": result.segment_count,
            "pause_count": result.pause_count,
        },
    )
    ctx.services.projects.touch(ctx.project_id)

    ctx.system(
        f"done: {result.duration_seconds:.1f}s audio, "
        f"{result.size_bytes / 1024:.0f} KB"
    )
    ctx.set_progress(1.0, "تولید گفتار کامل شد")

    return {
        "asset_id": asset.id,
        "path": str(result.output_path),
        "filename": result.output_path.name,
        "duration_seconds": result.duration_seconds,
        "duration_display": format_clock(result.duration_seconds),
        "size_bytes": result.size_bytes,
        "provider": provider.id,
        "voice_id": options.voice_id,
        "segment_count": result.segment_count,
        "pause_count": result.pause_count,
    }


# --------------------------------------------------------------------------
# Input resolution
# --------------------------------------------------------------------------


def _build_options(ctx: JobContext) -> SpeechOptions:
    settings = ctx.services.settings
    try:
        return SpeechOptions(
            voice_id=str(ctx.input.get("voice_id") or settings.get("voice.voice_id")),
            language=Language(ctx.input.get("language") or settings.get("voice.language")),
            style=SpeakingStyle(ctx.input.get("style") or settings.get("voice.style")),
            rate=float(ctx.input.get("rate", settings.get("voice.rate"))),
            pitch=float(ctx.input.get("pitch", settings.get("voice.pitch"))),
            output_format=str(
                ctx.input.get("output_format") or settings.get("voice.output_format")
            ),
        )
    except Exception as exc:
        raise ValidationError(
            f"invalid speech options: {exc}",
            user_message="تنظیمات صدا معتبر نیست.",
        ) from exc


def _build_segments(ctx: JobContext) -> list:
    """Build the segment list from structured input or from plain text."""
    raw = ctx.input.get("segments")

    if raw:
        segments = []
        for index, entry in enumerate(raw):
            kind = str(entry.get("kind") or SpeechSegmentKind.TEXT.value)
            entry_id = str(entry.get("id") or f"seg{index}")
            if kind == SpeechSegmentKind.PAUSE.value:
                try:
                    segments.append(
                        PauseSegment(id=entry_id, seconds=float(entry.get("seconds", 1.0)))
                    )
                except Exception as exc:
                    raise ValidationError(
                        f"invalid pause at position {index}: {exc}",
                        user_message="مدت یکی از مکث‌ها معتبر نیست.",
                    ) from exc
            else:
                text = str(entry.get("text") or "").strip()
                if text:
                    segments.append(TextSegment(id=entry_id, text=text))
        return segments

    # Plain text: one text segment.
    document_id = ctx.input.get("document_id")
    if document_id:
        document = ctx.services.documents.get(str(document_id))
        if document is None:
            raise NotFoundError(
                f"document {document_id!r} not found",
                user_message="سند انتخاب‌شده پیدا نشد.",
            )
        return [TextSegment(id="seg0", text=document.content)]

    text = str(ctx.input.get("text") or "").strip()
    if not text:
        raise ValidationError(
            "no text supplied for synthesis",
            user_message="متنی برای تبدیل به گفتار وارد نشده است.",
        )
    return [TextSegment(id="seg0", text=text)]
