"""Assembling a speech script into a single audio file.

A :class:`~app.domain.tts.SpeechScript` is an ordered list of text and pause
segments. This module renders it:

1. every text segment goes to the provider, one file each;
2. every pause segment becomes a generated silence file of exactly the
   requested length;
3. all parts are normalised to one intermediate PCM format;
4. FFmpeg's concat demuxer joins them and encodes the final output.

Step 3 is the one that is easy to skip and then regret. The concat *demuxer*
requires every input to share a codec, sample rate and channel layout - joining
an MP3 from the neural provider with a WAV from SAPI5 without normalising
produces either an error or silently corrupted audio. Converting each part to
24 kHz mono PCM first makes the join exact.

Pauses are rendered as real silence rather than passed to the provider as SSML
``<break>`` tags. That keeps pause behaviour identical across providers,
including one that has no SSML support at all, and makes the duration exact
rather than advisory.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.errors import TTSError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.security import unique_path
from app.domain.enums import SpeechSegmentKind
from app.domain.tts import SpeechScript
from app.media.ffmpeg.locator import FFmpegTools
from app.media.ffmpeg.probe import probe_media
from app.media.ffmpeg.runner import run_ffmpeg
from app.process import CancelToken
from app.tts.base import LogCallback, TTSProvider

logger = get_logger(__name__)

#: Intermediate format every part is converted to before concatenation.
_INTERMEDIATE_RATE = 24_000
_INTERMEDIATE_ARGS = ("-ac", "1", "-ar", str(_INTERMEDIATE_RATE), "-c:a", "pcm_s16le")

#: Final encoding per requested container.
_OUTPUT_ARGS: dict[str, tuple[str, ...]] = {
    "mp3": ("-c:a", "libmp3lame", "-b:a", "128k"),
    "wav": ("-c:a", "pcm_s16le", "-ar", "24000"),
}

ProgressCallback = Callable[[float | None, str], None]


@dataclass(slots=True)
class SynthesisResult:
    output_path: Path
    duration_seconds: float
    size_bytes: int
    segment_count: int
    pause_count: int
    voice_id: str
    provider: str


def assemble_speech(
    script: SpeechScript,
    *,
    provider: TTSProvider,
    tools: FFmpegTools,
    output_dir: Path,
    temp_root: Path,
    output_stem: str = "voice",
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> SynthesisResult:
    """Render ``script`` to a single audio file and return where it landed."""
    segments = [
        segment
        for segment in script.segments
        if segment.kind == SpeechSegmentKind.PAUSE
        or (segment.kind == SpeechSegmentKind.TEXT and segment.text.strip())
    ]
    if not segments:
        raise TTSError(
            "speech script has no renderable segments",
            user_message="متنی برای تبدیل به گفتار وجود ندارد.",
        )

    fmt = script.options.output_format
    if fmt not in _OUTPUT_ARGS:
        raise TTSError(
            f"unsupported output format: {fmt!r}",
            user_message="قالب خروجی انتخاب‌شده پشتیبانی نمی‌شود.",
        )

    work_dir = temp_root / f"tts_{new_id()}"
    work_dir.mkdir(parents=True, exist_ok=True)

    text_count = sum(1 for s in segments if s.kind == SpeechSegmentKind.TEXT)
    pause_count = len(segments) - text_count

    try:
        parts = _render_parts(
            segments,
            provider=provider,
            tools=tools,
            work_dir=work_dir,
            script=script,
            text_count=text_count,
            on_progress=on_progress,
            on_log=on_log,
            cancel_token=cancel_token,
        )

        if on_progress:
            on_progress(0.9, "در حال ترکیب بخش‌ها")

        output_path = unique_path(output_dir, f"{output_stem}.{fmt}")
        _concatenate(parts, tools, work_dir, output_path, fmt, on_log, cancel_token)

        probe = probe_media(tools, output_path)
        if on_progress:
            on_progress(1.0, "تولید گفتار کامل شد")

        return SynthesisResult(
            output_path=output_path,
            duration_seconds=probe.duration_seconds or 0.0,
            size_bytes=output_path.stat().st_size,
            segment_count=text_count,
            pause_count=pause_count,
            voice_id=script.options.voice_id,
            provider=provider.id,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _render_parts(
    segments,
    *,
    provider: TTSProvider,
    tools: FFmpegTools,
    work_dir: Path,
    script: SpeechScript,
    text_count: int,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    cancel_token: CancelToken | None,
) -> list[Path]:
    """Produce one normalised PCM file per segment, in script order."""
    parts: list[Path] = []
    rendered_text = 0

    for index, segment in enumerate(segments):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

        # Short ASCII names: these end up inside the concat list file.
        normalised = work_dir / f"part_{index:04d}.wav"

        if segment.kind == SpeechSegmentKind.PAUSE:
            _generate_silence(tools, segment.seconds, normalised, cancel_token)
            if on_log:
                on_log("system", f"part {index:04d}: silence {segment.seconds:g}s")
        else:
            raw = work_dir / f"raw_{index:04d}"
            produced = provider.synthesize(
                segment.text.strip(),
                script.options,
                raw,
                on_log=on_log,
                cancel_token=cancel_token,
            )
            _normalise(tools, produced, normalised, cancel_token)
            produced.unlink(missing_ok=True)

            rendered_text += 1
            if on_progress and text_count:
                # Reserve the last 10% for concatenation and encoding.
                on_progress(
                    0.9 * (rendered_text / text_count),
                    f"در حال تولید گفتار ({rendered_text} از {text_count})",
                )

        parts.append(normalised)

    return parts


def _generate_silence(
    tools: FFmpegTools, seconds: float, output: Path, cancel_token: CancelToken | None
) -> None:
    """Create an exact-length silent PCM file."""
    run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate={_INTERMEDIATE_RATE}",
            "-t",
            f"{seconds:.3f}",
            *_INTERMEDIATE_ARGS,
            str(output),
        ],
        output_path=output,
        cancel_token=cancel_token,
    )


def _normalise(
    tools: FFmpegTools, source: Path, output: Path, cancel_token: CancelToken | None
) -> None:
    """Convert a provider's output to the shared intermediate format."""
    run_ffmpeg(
        tools,
        ["-i", str(source), *_INTERMEDIATE_ARGS, str(output)],
        output_path=output,
        cancel_token=cancel_token,
    )


def _concatenate(
    parts: list[Path],
    tools: FFmpegTools,
    work_dir: Path,
    output_path: Path,
    fmt: str,
    on_log: LogCallback | None,
    cancel_token: CancelToken | None,
) -> None:
    """Join the parts and encode the final file."""
    if not parts:
        raise TTSError(
            "nothing to concatenate",
            user_message="هیچ بخشی برای ترکیب تولید نشد.",
        )

    # Relative names only; ffmpeg runs with work_dir as its cwd so no Windows
    # path escaping is needed inside the list file.
    listing = "\n".join(f"file '{part.name}'" for part in parts) + "\n"
    list_file = work_dir / "concat.txt"
    list_file.write_text(listing, encoding="utf-8", newline="\n")

    if on_log:
        on_log("system", f"concatenating {len(parts)} parts into {output_path.name}")

    run_ffmpeg(
        tools,
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_file.name,
            *_OUTPUT_ARGS[fmt],
            str(output_path),
        ],
        output_path=output_path,
        cwd=work_dir,
        cancel_token=cancel_token,
    )

    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise TTSError(
            "concatenation produced an empty file",
            user_message="فایل صوتی تولیدشده خالی بود.",
        )
