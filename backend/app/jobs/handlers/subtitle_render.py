"""Job handler: burn a subtitle track into a new video file.

Feature 5, final step. The source video is never modified; a new MP4 is always
written into the project's ``rendered/`` directory.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.timecode import format_clock
from app.domain.enums import AssetType, JobType
from app.jobs.context import JobContext
from app.jobs.registry import register_handler
from app.media.subtitles.formats import write_subtitle_file
from app.media.video import RENDER_QUALITIES, render_subtitles

logger = get_logger(__name__)


@register_handler(JobType.SUBTITLE_RENDER)
def handle_subtitle_render(ctx: JobContext) -> dict:
    """Render a subtitle track onto a video.

    Input:  ``track_id``, ``asset_id`` (the source video),
            optional ``quality``, ``export_subtitle`` (also save an .srt)
    Output: ``asset_id``, ``path``, size and timing information
    """
    settings = ctx.services.settings
    track_id = str(ctx.require("track_id"))
    asset_id = str(ctx.require("asset_id"))

    track = ctx.services.subtitles.get_track(track_id)
    if track is None:
        raise NotFoundError(
            f"subtitle track {track_id!r} not found",
            user_message="زیرنویس انتخاب‌شده پیدا نشد.",
        )
    if not track.cues:
        raise ValidationError(
            f"track {track_id!r} has no cues",
            user_message="این زیرنویس هیچ قطعه‌ای ندارد.",
            hint="ابتدا زیرنویس بسازید یا قطعه‌ای اضافه کنید.",
        )

    video_asset = ctx.services.assets.get(asset_id)
    if video_asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found",
            user_message="فایل ویدئویی انتخاب‌شده پیدا نشد.",
        )

    quality_id = str(ctx.input.get("quality") or settings.get("media.render_quality"))
    quality = RENDER_QUALITIES.get(quality_id)

    ctx.set_progress(0.0, "در حال آماده‌سازی رندر")
    ctx.system(f"video: {Path(video_asset.path).name}")
    ctx.system(f"subtitle: {len(track.cues)} cues, style={track.style.font_family} {track.style.font_size}px")
    ctx.system(f"quality: {quality.id if quality else quality_id}")

    tools = ctx.services.ffmpeg()
    ctx.set_progress(0.02, "در حال رندر ویدیو")

    result = render_subtitles(
        tools,
        source=Path(video_asset.path),
        cues=track.cues,
        style=track.style,
        output_dir=ctx.project_dir("rendered"),
        temp_dir=ctx.project_dir("temp"),
        quality_id=quality_id,
        on_progress=ctx.progress_callback(),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )

    ctx.set_progress(0.96, "در حال ثبت فایل خروجی")

    rendered_asset = ctx.services.assets.create(
        project_id=ctx.project_id,
        type=AssetType.RENDERED_VIDEO,
        path=result.output_path,
        original_filename=result.output_path.name,
        size_bytes=result.output_size_bytes,
        format="mp4",
        duration_seconds=result.duration_seconds,
        metadata={
            "source_asset_id": asset_id,
            "track_id": track_id,
            "quality": result.quality,
            "cue_count": len(track.cues),
        },
    )

    # Also export a sidecar subtitle file: useful for uploading alongside the
    # video, and free to produce now that the cues are in hand.
    subtitle_asset_id: str | None = None
    if bool(ctx.input.get("export_subtitle", True)):
        fmt = str(settings.get("subtitle.export_format") or "srt")
        subtitle_path = write_subtitle_file(
            ctx.project_dir("subtitles") / f"{result.output_path.stem}.{fmt}",
            track.cues,
            track.style,
        )
        subtitle_asset = ctx.services.assets.create(
            project_id=ctx.project_id,
            type=AssetType.SUBTITLE,
            path=subtitle_path,
            original_filename=subtitle_path.name,
            size_bytes=subtitle_path.stat().st_size,
            format=fmt,
            metadata={"track_id": track_id, "cue_count": len(track.cues)},
        )
        subtitle_asset_id = subtitle_asset.id
        ctx.system(f"exported {subtitle_path.name}")

    ctx.services.projects.touch(ctx.project_id)

    ctx.system(
        f"done: {result.output_size_bytes / 1024 / 1024:.1f} MB "
        f"in {result.processing_seconds:.1f}s"
    )
    ctx.set_progress(1.0, "رندر ویدیو کامل شد")

    return {
        "asset_id": rendered_asset.id,
        "subtitle_asset_id": subtitle_asset_id,
        "path": str(result.output_path),
        "filename": result.output_path.name,
        "output_size_bytes": result.output_size_bytes,
        "duration_seconds": result.duration_seconds,
        "duration_display": format_clock(result.duration_seconds),
        "processing_seconds": round(result.processing_seconds, 2),
        "quality": result.quality,
        "cue_count": len(track.cues),
    }
