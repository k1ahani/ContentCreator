"""Audio extraction, optimised for speech recognition.

The goal is not fidelity, it is *the smallest file that still transcribes
well*. Three decisions follow from that:

**Mono.** Speech recognition collapses channels anyway. Downmixing halves the
data before encoding.

**16 kHz sample rate, where the codec allows it.** Whisper-family models
resample their input to 16 kHz internally, so anything above it is discarded
work and wasted bytes. 16 kHz retains everything up to 8 kHz, which covers the
whole intelligibility range of speech. Opus is the exception: the Ogg Opus
mapping always declares a 48 kHz decode rate, so ``-ar`` is ignored there. That
costs nothing - the encoder codes speech bandwidth internally and the output
was measured byte-for-byte identical either way - so the preset simply does not
ask for a rate it cannot get.

**Opus by default.** At 24 kbps mono, Opus is transparent for speech - it was
designed for exactly this. The numbers for one hour of audio:

===========  ==========  ========  ============================================
Preset       Size/hour   Rate      Notes
===========  ==========  ========  ============================================
``opus``     ~15 MB      48 kHz    Default. Best size/quality ratio for speech.
``mp3``      ~29 MB      16 kHz    Use when a tool downstream cannot read Opus.
``wav``      ~110 MB     16 kHz    Uncompressed PCM, for difficult audio.
===========  ==========  ========  ============================================

All three are mono. The preset is configurable in Settings, so a user with
unusually noisy source material can trade size for accuracy without touching
code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.core.errors import MediaError
from app.core.logging import get_logger
from app.core.security import unique_path
from app.domain.asset import MediaProbe
from app.media.ffmpeg.locator import FFmpegTools
from app.media.ffmpeg.probe import probe_media
from app.media.ffmpeg.runner import LogCallback, ProgressCallback, run_ffmpeg
from app.process import CancelToken

logger = get_logger(__name__)

#: Sample rate presets target when the codec honours it. Matches the ASR
#: engine's internal rate.
SPEECH_SAMPLE_RATE: Final = 16_000


@dataclass(frozen=True, slots=True)
class AudioPreset:
    """One extraction configuration."""

    id: str
    label_fa: str
    extension: str
    codec_args: tuple[str, ...]
    approx_mb_per_hour: float
    description_fa: str
    #: Target sample rate, or ``None`` when the codec dictates its own. Opus
    #: always decodes at 48 kHz, so asking for 16 kHz would be a silent no-op.
    sample_rate: int | None = SPEECH_SAMPLE_RATE


AUDIO_PRESETS: Final[dict[str, AudioPreset]] = {
    "opus": AudioPreset(
        id="opus",
        label_fa="اوپوس (پیشنهادی)",
        extension=".ogg",
        # libopus at 24k mono; VOIP mode is tuned for speech intelligibility.
        codec_args=("-c:a", "libopus", "-b:a", "24k", "-application", "voip"),
        sample_rate=None,
        approx_mb_per_hour=15.0,
        description_fa="کمترین حجم با کیفیت کاملاً کافی برای تبدیل گفتار به متن.",
    ),
    "mp3": AudioPreset(
        id="mp3",
        label_fa="ام‌پی‌تری (سازگاری بیشتر)",
        extension=".mp3",
        codec_args=("-c:a", "libmp3lame", "-b:a", "64k"),
        approx_mb_per_hour=29.0,
        description_fa="حجم بیشتر، اما با تمام ابزارها و پخش‌کننده‌ها سازگار است.",
    ),
    "wav": AudioPreset(
        id="wav",
        label_fa="WAV بدون فشرده‌سازی",
        extension=".wav",
        codec_args=("-c:a", "pcm_s16le"),
        approx_mb_per_hour=110.0,
        description_fa="بیشترین دقت برای صداهای نویزی یا ضبط‌های ضعیف؛ حجم بسیار زیاد.",
    ),
}

DEFAULT_PRESET: Final = "opus"


def get_preset(preset_id: str | None) -> AudioPreset:
    """Look up a preset, falling back to the default for an unknown id."""
    if preset_id and preset_id in AUDIO_PRESETS:
        return AUDIO_PRESETS[preset_id]
    if preset_id:
        logger.warning("unknown audio preset %r, using %r", preset_id, DEFAULT_PRESET)
    return AUDIO_PRESETS[DEFAULT_PRESET]


@dataclass(slots=True)
class ExtractionResult:
    """What the audio-extraction job reports back to the UI."""

    output_path: Path
    preset: str
    input_size_bytes: int
    output_size_bytes: int
    duration_seconds: float
    processing_seconds: float
    source_probe: MediaProbe

    @property
    def compression_ratio(self) -> float:
        if self.output_size_bytes <= 0:
            return 0.0
        return self.input_size_bytes / self.output_size_bytes


def extract_audio(
    tools: FFmpegTools,
    *,
    source: Path,
    output_dir: Path,
    preset_id: str | None = None,
    output_stem: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    cancel_token: CancelToken | None = None,
) -> ExtractionResult:
    """Extract a speech-optimised audio track from a video or audio file.

    The source is opened read-only and never written to: the output always goes
    to a freshly allocated, non-colliding path inside the project workspace.
    """
    if not source.is_file():
        raise MediaError(
            f"source does not exist: {source}",
            user_message="فایل ویدئویی انتخاب‌شده پیدا نشد.",
        )

    probe = probe_media(tools, source)
    if not probe.has_audio:
        raise MediaError(
            f"{source} has no audio stream",
            user_message="این فایل هیچ شاخه صوتی ندارد و صدایی از آن قابل استخراج نیست.",
        )

    preset = get_preset(preset_id)
    stem = output_stem or source.stem
    output_path = unique_path(output_dir, f"{stem}{preset.extension}")

    args = [
        "-i",
        str(source),
        # Drop video, subtitle and data streams; keep only the first audio one.
        "-vn",
        "-sn",
        "-dn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        *(("-ar", str(preset.sample_rate)) if preset.sample_rate else ()),
        *preset.codec_args,
        str(output_path),
    ]

    logger.info(
        "extracting audio: %s -> %s (preset=%s, duration=%.1fs)",
        source.name,
        output_path.name,
        preset.id,
        probe.duration_seconds or 0.0,
    )

    run = run_ffmpeg(
        tools,
        args,
        total_duration=probe.duration_seconds,
        output_path=output_path,
        on_progress=on_progress,
        on_log=on_log,
        cancel_token=cancel_token,
    )

    output_size = output_path.stat().st_size
    if output_size == 0:
        output_path.unlink(missing_ok=True)
        raise MediaError(
            "ffmpeg produced an empty audio file",
            user_message="فایل صوتی تولیدشده خالی بود.",
        )

    return ExtractionResult(
        output_path=output_path,
        preset=preset.id,
        input_size_bytes=source.stat().st_size,
        output_size_bytes=output_size,
        duration_seconds=probe.duration_seconds or 0.0,
        processing_seconds=run.duration_seconds,
        source_probe=probe,
    )
