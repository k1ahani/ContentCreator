"""Job handler: extract speech-optimised audio from a video.

Feature 1. Input is a source asset already registered in the project; output is
a new audio asset. The source file is never modified or moved.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.timecode import format_clock
from app.domain.enums import AssetType, JobType
from app.jobs.context import JobContext
from app.jobs.registry import register_handler
from app.media.audio import extract_audio, get_preset

logger = get_logger(__name__)


@register_handler(JobType.AUDIO_EXTRACT)
def handle_audio_extract(ctx: JobContext) -> dict:
    """Extract audio from the job's source asset.

    Input:  ``asset_id``, optional ``preset``
    Output: ``asset_id``, ``path``, sizes, durations
    """
    asset_id = str(ctx.require("asset_id"))
    preset_id = ctx.input.get("preset") or ctx.services.settings.get("media.audio_preset")

    source_asset = ctx.services.assets.get(asset_id)
    if source_asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found",
            user_message="فایل ویدئویی انتخاب‌شده در این پروژه پیدا نشد.",
        )

    source = Path(source_asset.path)
    preset = get_preset(preset_id)

    ctx.set_progress(0.0, "در حال آماده‌سازی")
    ctx.system(f"source: {source.name}")
    ctx.system(f"preset: {preset.id} ({preset.extension})")

    tools = ctx.services.ffmpeg()
    ctx.set_progress(0.0, "در حال استخراج صدا")

    result = extract_audio(
        tools,
        source=source,
        output_dir=ctx.project_dir("audio"),
        preset_id=preset.id,
        on_progress=ctx.progress_callback(),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )

    ctx.set_progress(0.97, "در حال ثبت فایل خروجی")

    asset = ctx.services.assets.create(
        project_id=ctx.project_id,
        type=AssetType.AUDIO,
        path=result.output_path,
        original_filename=result.output_path.name,
        size_bytes=result.output_size_bytes,
        format=preset.extension.lstrip("."),
        duration_seconds=result.duration_seconds,
        metadata={
            "preset": result.preset,
            "source_asset_id": asset_id,
            "sample_rate": preset.sample_rate,
            "channels": 1,
            "compression_ratio": round(result.compression_ratio, 2),
        },
    )
    ctx.services.projects.touch(ctx.project_id)

    ctx.system(
        f"done: {result.input_size_bytes / 1024 / 1024:.1f} MB -> "
        f"{result.output_size_bytes / 1024 / 1024:.1f} MB "
        f"({result.compression_ratio:.1f}x smaller) in {result.processing_seconds:.1f}s"
    )
    ctx.set_progress(1.0, "استخراج صدا کامل شد")

    return {
        "asset_id": asset.id,
        "path": str(result.output_path),
        "filename": result.output_path.name,
        "preset": result.preset,
        "input_size_bytes": result.input_size_bytes,
        "output_size_bytes": result.output_size_bytes,
        "compression_ratio": round(result.compression_ratio, 2),
        "duration_seconds": result.duration_seconds,
        "duration_display": format_clock(result.duration_seconds),
        "processing_seconds": round(result.processing_seconds, 2),
    }
