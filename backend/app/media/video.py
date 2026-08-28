"""Video rendering: burning subtitles into a new MP4.

The source video is opened read-only and a **new** file is always written, so
the original can never be damaged by a render.

The awkward part of this module is the ``subtitles`` filter's argument
escaping. The filtergraph is one string, and inside it FFmpeg treats ``:`` as
an option separator, ``,`` as a filter separator and ``\\`` as an escape - so a
Windows path like ``E:\\LoyalAxis\\...\\track.ass`` is a minefield. The fix used
here is to sidestep it entirely: the subtitle script is copied to a
short ASCII-named temporary file, FFmpeg is run with that file's *directory* as
its working directory, and the filter references the bare filename. No drive
letter, no backslashes, no Persian characters in the filtergraph.

Fonts are supplied through ``fontsdir`` pointing at ``bin/fonts`` when the
project ships one, so a render does not depend on what happens to be installed
system-wide.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.core.errors import MediaError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.core.security import unique_path
from app.domain.subtitle import SubtitleCue, SubtitleStyle
from app.media.ffmpeg.locator import FFmpegTools
from app.media.ffmpeg.probe import probe_media
from app.media.ffmpeg.runner import LogCallback, ProgressCallback, run_ffmpeg
from app.media.subtitles.formats import to_ass
from app.process import CancelToken

logger = get_logger(__name__)

#: Directory of bundled fonts, if scripts/setup.ps1 installed any.
FONTS_DIR = PATHS.bin_dir / "fonts"


@dataclass(frozen=True, slots=True)
class RenderQuality:
    """An x264 quality preset."""

    id: str
    label_fa: str
    crf: int
    preset: str
    description_fa: str


RENDER_QUALITIES: dict[str, RenderQuality] = {
    "high": RenderQuality(
        id="high",
        label_fa="کیفیت بالا",
        crf=18,
        preset="slow",
        description_fa="بهترین کیفیت تصویر، حجم بیشتر و رندر کندتر.",
    ),
    "balanced": RenderQuality(
        id="balanced",
        label_fa="متعادل (پیشنهادی)",
        crf=21,
        preset="medium",
        description_fa="تعادل مناسب میان کیفیت، حجم و سرعت رندر.",
    ),
    "fast": RenderQuality(
        id="fast",
        label_fa="سریع",
        crf=24,
        preset="veryfast",
        description_fa="رندر سریع با حجم کمتر؛ افت کیفیت محسوس‌تر است.",
    ),
}

DEFAULT_QUALITY = "balanced"


@dataclass(slots=True)
class RenderResult:
    output_path: Path
    output_size_bytes: int
    processing_seconds: float
    duration_seconds: float
    quality: str


def render_subtitles(
    tools: FFmpegTools,
    *,
    source: Path,
    cues: Sequence[SubtitleCue],
    style: SubtitleStyle,
    output_dir: Path,
    temp_dir: Path,
    quality_id: str | None = None,
    output_stem: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> RenderResult:
    """Burn ``cues`` into ``source`` and write a new MP4."""
    if not source.is_file():
        raise MediaError(
            f"source video does not exist: {source}",
            user_message="فایل ویدئویی پیدا نشد.",
        )
    if not cues:
        raise MediaError(
            "no cues to render",
            user_message="این زیرنویس هیچ قطعه‌ای ندارد.",
            hint="ابتدا زیرنویس بسازید یا حداقل یک قطعه اضافه کنید.",
        )

    probe = probe_media(tools, source)
    if not probe.has_video:
        raise MediaError(
            f"{source} has no video stream",
            user_message="این فایل شاخه تصویری ندارد و نمی‌توان روی آن زیرنویس رندر کرد.",
        )

    quality = RENDER_QUALITIES.get(quality_id or DEFAULT_QUALITY, RENDER_QUALITIES[DEFAULT_QUALITY])
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Author the ASS against the real frame size so font sizes and margins mean
    # what the preview showed.
    script = to_ass(
        cues,
        style,
        play_res_x=probe.width or 1920,
        play_res_y=probe.height or 1080,
    )

    # Short, ASCII-only name: this is what goes inside the filtergraph.
    ass_name = f"sub_{new_id()}.ass"
    ass_path = temp_dir / ass_name
    ass_path.write_text(script, encoding="utf-8", newline="\n")

    output_path = unique_path(output_dir, f"{output_stem or source.stem}-subtitled.mp4")

    subtitles_filter = f"subtitles=filename={ass_name}"
    if FONTS_DIR.is_dir() and any(FONTS_DIR.iterdir()):
        # Copy fonts next to the script so this argument is also relative.
        local_fonts = temp_dir / "fonts"
        local_fonts.mkdir(exist_ok=True)
        for font in FONTS_DIR.glob("*.ttf"):
            shutil.copy2(font, local_fonts / font.name)
        for font in FONTS_DIR.glob("*.otf"):
            shutil.copy2(font, local_fonts / font.name)
        subtitles_filter += ":fontsdir=fonts"

    args = [
        "-i",
        str(source),
        "-vf",
        subtitles_filter,
        "-c:v",
        "libx264",
        "-crf",
        str(quality.crf),
        "-preset",
        quality.preset,
        "-pix_fmt",
        "yuv420p",
        # Copy audio untouched: re-encoding it would lose quality for nothing.
        "-c:a",
        "copy",
        # Let the player start before the whole file is buffered.
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    logger.info(
        "rendering subtitles: %s (%d cues, quality=%s) -> %s",
        source.name,
        len(cues),
        quality.id,
        output_path.name,
    )

    try:
        run = _run_with_audio_fallback(
            tools,
            args,
            duration=probe.duration_seconds,
            output_path=output_path,
            temp_dir=temp_dir,
            on_progress=on_progress,
            on_log=on_log,
            cancel_token=cancel_token,
        )
    finally:
        ass_path.unlink(missing_ok=True)

    size = output_path.stat().st_size if output_path.is_file() else 0
    if size == 0:
        output_path.unlink(missing_ok=True)
        raise MediaError(
            "render produced an empty file",
            user_message="فایل خروجی خالی بود.",
        )

    return RenderResult(
        output_path=output_path,
        output_size_bytes=size,
        processing_seconds=run.duration_seconds,
        duration_seconds=probe.duration_seconds or 0.0,
        quality=quality.id,
    )


def _run_with_audio_fallback(
    tools: FFmpegTools,
    args: list[str],
    *,
    duration: float | None,
    output_path: Path,
    temp_dir: Path,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    cancel_token: CancelToken | None,
):
    """Run the render, retrying with AAC if the source audio cannot be copied.

    ``-c:a copy`` fails when the source codec is not legal in MP4 - Vorbis or
    Opus in a WebM source, for instance. Re-encoding only in that case keeps
    the common path lossless.
    """
    try:
        return run_ffmpeg(
            tools,
            args,
            total_duration=duration,
            output_path=output_path,
            on_progress=on_progress,
            on_log=on_log,
            cancel_token=cancel_token,
            # Run from the temp dir so the relative .ass filename in the
            # filtergraph resolves without any path escaping.
            cwd=temp_dir,
        )
    except MediaError as exc:
        stderr = str(exc.details.get("stderr_tail", "")).lower()
        incompatible = (
            "could not find tag for codec" in stderr
            or "incompatible with output" in stderr
            or "codec not currently supported in container" in stderr
        )
        if not incompatible:
            raise

        logger.info("audio stream cannot be copied into MP4, re-encoding to AAC")
        if on_log:
            on_log("system", "audio stream is not MP4-compatible, re-encoding to AAC")

        retry = list(args)
        index = retry.index("-c:a")
        retry[index + 1] = "aac"
        retry.insert(index + 2, "-b:a")
        retry.insert(index + 3, "192k")
        output_path.unlink(missing_ok=True)

        return run_ffmpeg(
            tools,
            retry,
            total_duration=duration,
            output_path=output_path,
            on_progress=on_progress,
            on_log=on_log,
            cancel_token=cancel_token,
            cwd=temp_dir,
        )
