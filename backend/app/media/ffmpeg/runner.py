"""FFmpeg execution with real progress reporting.

Progress is read from ``-progress pipe:1``, which makes FFmpeg emit a stream of
``key=value`` lines on **stdout**, rather than by scraping the human-readable
status line it writes to stderr. The stderr format is not stable across builds
and interleaves with warnings; the progress stream is machine-readable and
documented.

A run therefore produces two things at once: a clean numeric progress fraction
for the job's progress bar, and the raw stderr lines for the CLI console.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from app.core.errors import MediaError, ProcessError
from app.core.logging import get_logger
from app.media.ffmpeg.locator import FFmpegTools
from app.process import CancelToken, ProcessSpec, run_process

logger = get_logger(__name__)

#: ``(fraction_0_to_1, seconds_processed)``
ProgressCallback = Callable[[float | None, float], None]
LogCallback = Callable[[str, str], None]

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)")


@dataclass(slots=True)
class FFmpegRun:
    """Result of one FFmpeg invocation."""

    exit_code: int
    duration_seconds: float
    stderr: str
    output_path: Path | None = None


def _parse_progress_line(line: str) -> tuple[str, str] | None:
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    return key.strip(), value.strip()


def run_ffmpeg(
    tools: FFmpegTools,
    args: Sequence[str],
    *,
    total_duration: float | None = None,
    output_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    cancel_token: CancelToken | None = None,
    timeout_seconds: int | None = None,
    cwd: Path | None = None,
) -> FFmpegRun:
    """Run FFmpeg with progress reporting.

    ``args`` must **not** include the executable, ``-progress``, ``-nostats``,
    ``-hide_banner`` or ``-y``; those are added here so every call behaves the
    same way.

    ``cwd`` matters for the ``subtitles`` filter: the renderer runs FFmpeg from
    the directory holding the subtitle script so the filtergraph can reference
    it by a bare filename, avoiding Windows path escaping entirely.
    """
    argv = [
        str(tools.ffmpeg),
        "-hide_banner",
        # Overwrite the *output* we chose, which is always a fresh path in the
        # project workspace. Source files are never passed as an output.
        "-y",
        "-nostdin",
        "-progress",
        "pipe:1",
        "-nostats",
        *[str(part) for part in args],
    ]

    detected_duration = total_duration
    last_fraction = -1.0

    def handle_stdout(line: str) -> None:
        nonlocal last_fraction
        parsed = _parse_progress_line(line)
        if parsed is None:
            return
        key, value = parsed

        if key == "out_time_us" and value not in ("N/A", ""):
            try:
                seconds = int(value) / 1_000_000
            except ValueError:
                return
            fraction: float | None = None
            if detected_duration and detected_duration > 0:
                fraction = min(seconds / detected_duration, 1.0)
                # Avoid flooding the event bus with sub-percent updates.
                if fraction - last_fraction < 0.005 and fraction < 1.0:
                    return
                last_fraction = fraction
            if on_progress:
                on_progress(fraction, seconds)

        elif key == "progress" and value == "end" and on_progress:
            on_progress(1.0, detected_duration or 0.0)

    def handle_stderr(line: str) -> None:
        nonlocal detected_duration
        if detected_duration is None:
            match = _DURATION_RE.search(line)
            if match:
                hours, minutes, seconds, centis = match.groups()
                detected_duration = (
                    int(hours) * 3600
                    + int(minutes) * 60
                    + int(seconds)
                    + int(centis.ljust(2, "0")[:2]) / 100
                )
                logger.debug("detected input duration: %.2fs", detected_duration)
        if on_log:
            on_log("stderr", line)

    if on_log:
        on_log("system", f"$ ffmpeg {' '.join(str(a) for a in args)}")

    try:
        result = run_process(
            ProcessSpec(argv=argv, timeout_seconds=timeout_seconds, cwd=cwd),
            on_stdout=handle_stdout,
            on_stderr=handle_stderr,
            cancel_token=cancel_token,
            check=False,
        )
    except ProcessError as exc:
        raise MediaError(
            f"could not start ffmpeg: {exc.message}",
            user_message="اجرای FFmpeg ممکن نشد.",
            hint="مسیر FFmpeg را در «تنظیمات ← رسانه» بررسی کنید.",
        ) from exc

    if result.exit_code != 0:
        raise MediaError(
            f"ffmpeg exited with {result.exit_code}",
            user_message=_explain_ffmpeg_failure(result.stderr),
            hint="جزئیات کامل در کنسول این وظیفه در دسترس است.",
            details={"exit_code": result.exit_code, "stderr_tail": result.stderr[-1500:]},
        )

    if output_path is not None and not output_path.is_file():
        raise MediaError(
            f"ffmpeg reported success but {output_path} does not exist",
            user_message="پردازش کامل شد اما فایل خروجی ساخته نشد.",
        )

    return FFmpegRun(
        exit_code=result.exit_code,
        duration_seconds=result.duration_seconds,
        stderr=result.stderr,
        output_path=output_path,
    )


def _explain_ffmpeg_failure(stderr: str) -> str:
    """Turn a known FFmpeg error into a Persian sentence a user can act on."""
    lowered = (stderr or "").lower()
    if "no such file or directory" in lowered:
        return "فایل ورودی پیدا نشد."
    if "permission denied" in lowered:
        return "دسترسی به فایل ورودی یا پوشه خروجی وجود ندارد."
    if "invalid data found" in lowered or "moov atom not found" in lowered:
        return "فایل ورودی خراب است یا فرمت آن پشتیبانی نمی‌شود."
    if "does not contain any stream" in lowered or "no audio" in lowered:
        return "این فایل هیچ شاخه صوتی قابل استخراج ندارد."
    if "unknown encoder" in lowered or "encoder not found" in lowered:
        return "کدک انتخاب‌شده در این نسخه FFmpeg پشتیبانی نمی‌شود."
    if "no space left" in lowered:
        return "فضای کافی روی دیسک وجود ندارد."
    if "fontconfig" in lowered or "cannot load" in lowered and "font" in lowered:
        return "فونت انتخاب‌شده برای زیرنویس پیدا نشد."
    return "پردازش رسانه با خطا مواجه شد."
