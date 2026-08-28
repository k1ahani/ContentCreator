"""Media inspection via ffprobe.

Returns a normalised :class:`~app.domain.asset.MediaProbe` so the rest of the
platform never has to understand ffprobe's JSON shape. Used to show duration
and size before extraction, to size the progress bar, and to decide whether a
file actually contains audio before offering to extract it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.errors import MediaError
from app.core.logging import get_logger
from app.domain.asset import MediaProbe
from app.media.ffmpeg.locator import FFmpegTools
from app.process import ProcessSpec, run_process

logger = get_logger(__name__)


def probe_media(tools: FFmpegTools, path: Path, *, timeout: int = 60) -> MediaProbe:
    """Inspect a media file. Raises :class:`MediaError` if it cannot be read."""
    if not tools.has_ffprobe:
        raise MediaError(
            "ffprobe is not available beside ffmpeg",
            user_message="ابزار ffprobe در کنار FFmpeg پیدا نشد.",
            hint="اسکریپت scripts/setup.ps1 را دوباره اجرا کنید.",
        )
    if not path.is_file():
        raise MediaError(
            f"file does not exist: {path}",
            user_message="فایل انتخاب‌شده پیدا نشد.",
        )

    argv = [
        str(tools.ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    result = run_process(ProcessSpec(argv=argv, timeout_seconds=timeout), check=False)
    if result.exit_code != 0:
        raise MediaError(
            f"ffprobe failed with {result.exit_code}: {result.stderr[:400]}",
            user_message="اطلاعات این فایل خوانده نشد. ممکن است فایل خراب باشد.",
            details={"exit_code": result.exit_code},
        )

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError(
            f"ffprobe returned unparsable JSON: {exc}",
            user_message="اطلاعات این فایل قابل خواندن نبود.",
        ) from exc

    return _to_probe(payload, path)


def _to_probe(payload: dict[str, Any], path: Path) -> MediaProbe:
    fmt = payload.get("format") or {}
    streams = payload.get("streams") or []

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    # Some containers report duration only on the stream, others only on the
    # format block; prefer the format value and fall back to the stream.
    duration = _as_float(fmt.get("duration"))
    if duration is None and audio:
        duration = _as_float(audio.get("duration"))
    if duration is None and video:
        duration = _as_float(video.get("duration"))

    size = _as_int(fmt.get("size")) or (path.stat().st_size if path.is_file() else 0)

    return MediaProbe(
        duration_seconds=duration,
        format_name=str(fmt.get("format_name") or ""),
        size_bytes=size,
        bit_rate=_as_int(fmt.get("bit_rate")),
        has_video=video is not None,
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name")) if video else None,
        audio_codec=str(audio.get("codec_name")) if audio else None,
        width=_as_int(video.get("width")) if video else None,
        height=_as_int(video.get("height")) if video else None,
        fps=_parse_fps(video.get("avg_frame_rate")) if video else None,
        sample_rate=_as_int(audio.get("sample_rate")) if audio else None,
        channels=_as_int(audio.get("channels")) if audio else None,
    )


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_fps(value: Any) -> float | None:
    """ffprobe reports frame rate as the rational string ``"30000/1001"``."""
    if not isinstance(value, str) or "/" not in value:
        return _as_float(value)
    numerator, _, denominator = value.partition("/")
    try:
        den = float(denominator)
        if den == 0:
            return None
        return round(float(numerator) / den, 3)
    except ValueError:
        return None
