"""Job handler: build a subtitle track from a transcript.

Feature 5. Produces structured cues, never a blob of text.

Two sources of timing, in order of preference:

1. **Transcription segments** carried in the transcribe job's output. These
   have timings measured from the audio, so cues land on real speech
   boundaries. This is the path the UI uses when a transcript came from the
   platform's own transcription step.
2. **Plain document text plus a duration.** No measured timings exist, so time
   is distributed by character count. Clearly worse, and reported as such in
   the job output (``timing_source``) so the UI can tell the user the timeline
   needs review.
"""

from __future__ import annotations

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.enums import AssetType, JobType, Language
from app.domain.subtitle import TrackCreate
from app.domain.transcription import TranscriptSegment
from app.jobs.context import JobContext
from app.jobs.registry import register_handler
from app.media.subtitles.segmentation import (
    SegmentationRules,
    cues_from_segments,
    cues_from_text,
)

logger = get_logger(__name__)


@register_handler(JobType.SUBTITLE_GENERATE)
def handle_subtitle_generate(ctx: JobContext) -> dict:
    """Create a subtitle track and its cues.

    Input:  ``document_id`` or ``text``; optional ``segments``, ``job_id``
            (a transcribe job to take segments from), ``language``, ``name``,
            ``duration_seconds``, ``track_id`` (regenerate into an existing track)
    Output: ``track_id``, ``cue_count``, ``timing_source``
    """
    settings = ctx.services.settings
    rules = _rules_from_settings(ctx)

    language = Language(
        ctx.input.get("language") or settings.get("transcription.language")
    )

    segments = _resolve_segments(ctx)
    text, source_document_id = _resolve_text(ctx)

    ctx.set_progress(0.1, "در حال ساخت قطعه‌های زیرنویس")

    if segments:
        cues = cues_from_segments(segments, rules=rules)
        timing_source = "asr_segments"
        ctx.system(f"building cues from {len(segments)} measured segments")
    else:
        duration = float(ctx.input.get("duration_seconds") or 0.0) or _guess_duration(ctx)
        if not text.strip():
            raise ValidationError(
                "no transcript text to build subtitles from",
                user_message="متنی برای ساخت زیرنویس وجود ندارد.",
                hint="ابتدا صدا را به متن تبدیل کنید.",
            )
        cues = cues_from_text(text, duration, rules=rules)
        timing_source = "estimated"
        ctx.system(
            f"no measured timings available: distributing {len(text)} characters "
            f"across {duration:.1f}s"
        )

    if not cues:
        raise ValidationError(
            "segmentation produced no cues",
            user_message="هیچ قطعه زیرنویسی ساخته نشد.",
        )

    ctx.set_progress(0.7, "در حال ذخیره زیرنویس")

    track_id = ctx.input.get("track_id")
    if track_id:
        track = ctx.services.subtitles.get_track(str(track_id), with_cues=False)
        if track is None:
            raise NotFoundError(
                f"subtitle track {track_id!r} not found",
                user_message="زیرنویس انتخاب‌شده پیدا نشد.",
            )
    else:
        track = ctx.services.subtitles.create_track(
            ctx.project_id,
            TrackCreate(
                name=str(ctx.input.get("name") or f"زیرنویس {language.native_name}"),
                language=language,
                style=settings.subtitle_style,
                source_document_id=source_document_id,
            ),
        )

    saved = ctx.services.subtitles.replace_cues(track.id, cues)
    ctx.services.projects.touch(ctx.project_id)

    total = max((cue.end for cue in saved), default=0.0)
    ctx.system(f"created {len(saved)} cues spanning {total:.1f}s")
    ctx.set_progress(1.0, "ساخت زیرنویس کامل شد")

    return {
        "track_id": track.id,
        "cue_count": len(saved),
        "timing_source": timing_source,
        "language": language.value,
        "duration_seconds": round(total, 3),
        "source_document_id": source_document_id,
    }


# --------------------------------------------------------------------------
# Input resolution
# --------------------------------------------------------------------------


def _rules_from_settings(ctx: JobContext) -> SegmentationRules:
    settings = ctx.services.settings
    return SegmentationRules(
        max_chars=int(ctx.input.get("max_chars") or settings.get("subtitle.max_chars")),
        target_chars=int(settings.get("subtitle.target_chars")),
        min_duration=float(settings.get("subtitle.min_duration")),
        max_duration=float(settings.get("subtitle.max_duration")),
    )


def _resolve_segments(ctx: JobContext) -> list[TranscriptSegment]:
    """Find measured timings, either passed inline or from a transcribe job."""
    raw = ctx.input.get("segments")

    if not raw and ctx.input.get("job_id"):
        source_job = ctx.services.job_repo.get(str(ctx.input["job_id"]))
        if source_job is not None:
            raw = source_job.output.get("segments")

    if not raw:
        return []

    segments: list[TranscriptSegment] = []
    for index, entry in enumerate(raw):
        try:
            segments.append(
                TranscriptSegment(
                    index=int(entry.get("index", index)),
                    start=float(entry["start"]),
                    end=float(entry["end"]),
                    text=str(entry.get("text") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("skipping malformed segment at position %d", index)
    return [segment for segment in segments if segment.text.strip()]


def _resolve_text(ctx: JobContext) -> tuple[str, str | None]:
    document_id = ctx.input.get("document_id")
    if document_id:
        document = ctx.services.documents.get(str(document_id))
        if document is None:
            raise NotFoundError(
                f"document {document_id!r} not found",
                user_message="سند انتخاب‌شده پیدا نشد.",
            )
        return document.content, document.id
    return str(ctx.input.get("text") or ""), None


def _guess_duration(ctx: JobContext) -> float:
    """Fall back to the project's most recent audio or video duration."""
    for asset_type in (AssetType.AUDIO, AssetType.VIDEO):
        asset = ctx.services.assets.latest(ctx.project_id, asset_type)
        if asset and asset.duration_seconds:
            return float(asset.duration_seconds)
    raise ValidationError(
        "cannot determine media duration for subtitle timing",
        user_message="مدت زمان رسانه مشخص نیست.",
        hint="ابتدا فایل ویدئویی یا صوتی را به پروژه اضافه کنید.",
    )
