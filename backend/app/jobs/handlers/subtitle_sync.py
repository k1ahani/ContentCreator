"""Job handler: synchronise an existing subtitle track with the video's audio.

Feature 5, the repair path. Subtitle *generation* builds cues and timings
together from a transcript; this handler is for a track whose text is already
correct but whose timings are not - most often a raw subtitle file that came
out of the video-production step and was imported as plain text, where cue
times were distributed by character count over the whole file
(``timing_source: "estimated"``) and drift steadily away from the speech.

What it does, in one sentence: re-extract the audio from the video, measure
where the words really are, and move the existing cues onto those measurements
without touching a single character of their text.

The measurement is real. It reuses the same speech-recognition layer the
transcription feature uses (``app/transcription/``), because word timings are
something only an engine listening to the waveform can produce - the
"synchronise" button is not a heuristic dressed up as analysis. The matching
of cue text against those measured words, and the fallback for when the two
cannot be matched at all, both live in ``app/media/subtitles/sync.py``.

The source video is never modified: audio is extracted to the project's
``temp/`` directory and deleted when the job ends, whatever its outcome.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import AppError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.enums import AssetType, JobType, Language, SubtitleTimingSource
from app.domain.subtitle import TimingRules
from app.domain.transcription import TranscriptionOptions
from app.jobs.context import JobContext
from app.jobs.handlers.transcribe import DEFAULT_PERSIAN_SEED_PROMPT
from app.jobs.registry import register_handler
from app.media.audio import extract_audio
from app.media.subtitles.sync import (
    TimedText,
    TimingAdjustments,
    align_to_words,
    build_report,
    distribute_over_speech,
    words_from_segments,
)

logger = get_logger(__name__)

#: Audio preset used for the re-extraction. Always WAV rather than the user's
#: configured preset: this file exists for exactly one ASR pass and is deleted
#: immediately afterwards, so the smallest-file trade-off that governs
#: ``media.audio_preset`` (docs/AUDIO_PROCESSING.md) does not apply, and
#: uncompressed PCM gives the engine the cleanest word boundaries to measure -
#: which is the entire output of this job.
SYNC_AUDIO_PRESET = "wav"


@register_handler(JobType.SUBTITLE_SYNC)
def handle_subtitle_sync(ctx: JobContext) -> dict:
    """Re-time a subtitle track against the audio of a media asset.

    Input:  ``track_id``, ``asset_id`` (video or audio), optional ``engine``,
            ``model_size``, ``language``, ``strategy``
            (``auto``/``align``/``distribute``), ``min_duration``,
            ``max_duration``, ``gap``
    Output: ``track_id``, ``timing_source``, ``coverage``, the retime report
    """
    track_id = str(ctx.require("track_id"))
    asset_id = str(ctx.require("asset_id"))
    strategy = str(ctx.input.get("strategy") or "auto")

    track = ctx.services.subtitles.get_track(track_id)
    if track is None or track.project_id != ctx.project_id:
        raise NotFoundError(
            f"subtitle track {track_id!r} not found in project {ctx.project_id!r}",
            user_message="زیرنویس انتخاب‌شده پیدا نشد.",
        )
    if not track.cues:
        raise ValidationError(
            f"track {track_id!r} has no cues to synchronise",
            user_message="این زیرنویس هیچ قطعه‌ای برای همگام‌سازی ندارد.",
            hint="ابتدا زیرنویس بسازید یا قطعه‌ای اضافه کنید.",
        )

    asset = ctx.services.assets.get(asset_id)
    if asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found",
            user_message="فایل ویدئویی یا صوتی انتخاب‌شده پیدا نشد.",
        )

    items = [
        TimedText(key=cue.id, text=cue.text, start=cue.start, end=cue.end)
        for cue in track.cues
    ]
    rules = _rules_from_input(ctx, asset.duration_seconds)

    ctx.set_progress(0.0, "در حال آماده‌سازی همگام‌سازی")
    ctx.system(f"track: {len(items)} cues, source={Path(asset.path).name}")
    ctx.system(f"strategy: {strategy}")

    audio_path, temporary = _resolve_audio(ctx, asset)
    try:
        segments, language = _measure(ctx, audio_path)
    finally:
        if temporary:
            audio_path.unlink(missing_ok=True)
            ctx.system(f"removed temporary audio {audio_path.name}")

    if not segments:
        raise AppError(
            "speech recognition found no speech to synchronise against",
            user_message="هیچ گفتاری در صدای این فایل تشخیص داده نشد.",
            hint="بررسی کنید که ویدیو واقعاً شامل صحبت باشد.",
        )

    ctx.set_progress(0.88, "در حال تطبیق متن زیرنویس با گفتار")

    adjustments = TimingAdjustments()
    timed, timing_source, coverage = _place_cues(
        ctx, items, segments, rules, strategy, adjustments
    )

    ctx.set_progress(0.94, "در حال ذخیره زمان‌بندی جدید")

    saved = ctx.services.subtitles.retime_cues(
        track_id, {item.key: (item.start, item.end) for item in timed}
    )
    ctx.services.projects.touch(ctx.project_id)

    report = build_report(timing_source.value, items, timed, adjustments)
    ctx.system(
        f"synchronised {report.changed_count} of {report.cue_count} cues "
        f"(largest move {report.max_shift_seconds:.2f}s, "
        f"track now {report.first_start:.2f}s-{report.last_end:.2f}s)"
    )
    ctx.set_progress(1.0, "همگام‌سازی زیرنویس کامل شد")

    return {
        "track_id": track_id,
        "asset_id": asset_id,
        "timing_source": timing_source.value,
        "coverage": round(coverage, 3),
        "language": language.value,
        "segment_count": len(segments),
        "cue_count": len(saved),
        **report.model_dump(),
    }


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


def _resolve_audio(ctx: JobContext, asset) -> tuple[Path, bool]:
    """Give the engine something to listen to, and say whether to delete it.

    An audio asset is used as it is. Anything else is re-extracted from the
    source into ``temp/`` - the "reprocess the video's audio" step - which also
    guarantees the engine gets mono PCM at the rate it wants regardless of what
    the container held.
    """
    source = Path(asset.path)
    if not source.is_file():
        raise NotFoundError(
            f"asset file is missing on disk: {source}",
            user_message="فایل انتخاب‌شده روی دیسک پیدا نشد.",
        )

    if asset.type == AssetType.AUDIO:
        ctx.system("using the existing audio asset directly")
        return source, False

    ctx.set_progress(0.02, "در حال استخراج دوباره صدای ویدیو")
    result = extract_audio(
        ctx.services.ffmpeg(),
        source=source,
        output_dir=ctx.project_dir("temp"),
        preset_id=SYNC_AUDIO_PRESET,
        output_stem=f"sync-{asset.id}",
        on_progress=_scaled_progress(ctx, floor=0.02, ceiling=0.15),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )
    ctx.system(
        f"extracted {result.output_path.name} "
        f"({result.output_size_bytes / 1024 / 1024:.1f} MB, {result.duration_seconds:.1f}s)"
    )
    return result.output_path, True


def _measure(ctx: JobContext, audio_path: Path):
    """Run speech recognition and return its segments plus the language used."""
    settings = ctx.services.settings
    language = Language(
        ctx.input.get("language") or settings.get("transcription.language")
    )

    # The same decoder seed the transcription feature uses. This is not a
    # copied detail - it is a correctness requirement here. Whisper's output
    # is conditioned on its initial prompt, so running it with a different
    # prompt than the transcription step yields a *differently worded*
    # transcript of identical audio. Since alignment works by matching cue
    # text against that transcript, a track generated from the platform's own
    # transcription would then fail to match the platform's own re-listening,
    # and fall back to distribution for no reason other than an inconsistency
    # between two of our own calls. See transcribe.py for why the seed exists.
    initial_prompt = ctx.input.get("initial_prompt") or None
    if not initial_prompt and language == Language.PERSIAN:
        initial_prompt = DEFAULT_PERSIAN_SEED_PROMPT

    options = TranscriptionOptions(
        language=language,
        model_size=str(
            ctx.input.get("model_size") or settings.get("transcription.model_size")
        ),
        auto_detect_language=bool(ctx.input.get("auto_detect_language", False)),
        vad_filter=bool(settings.get("transcription.vad_filter")),
        initial_prompt=initial_prompt,
    )

    engine_id = str(ctx.input.get("engine") or settings.get("transcription.engine"))
    engine = ctx.services.transcription.get(engine_id)

    ctx.set_progress(0.16, "در حال تحلیل صدا برای یافتن زمان کلمات")
    ctx.system(f"engine={engine_id} model={options.model_size} language={language.value}")

    result = engine.transcribe(
        audio_path,
        options,
        on_progress=_scaled_progress(ctx, floor=0.16, ceiling=0.86, staged=True),
        on_log=ctx.log_callback(),
        cancel_token=ctx.cancel_token,
    )
    measured_words = sum(len(segment.words) for segment in result.segments)
    ctx.system(
        f"measured {len(result.segments)} speech segment(s), {measured_words} word timing(s)"
    )
    return result.segments, language


def _place_cues(
    ctx: JobContext,
    items: list[TimedText],
    segments,
    rules: TimingRules,
    strategy: str,
    adjustments: TimingAdjustments,
) -> tuple[list[TimedText], SubtitleTimingSource, float]:
    """Choose and run a placement strategy, reporting which one actually ran.

    ``auto`` tries text alignment first and falls back on its own; the explicit
    strategies exist for the two cases the user knows better than the matcher
    does - a translated track (``distribute``), or a track they know matches
    the audio and want aligned even if the engine heard it poorly (``align``).
    """
    if strategy != "distribute":
        words = words_from_segments(segments)
        aligned = align_to_words(items, words, rules, adjustments)
        if aligned is not None:
            timed, stats = aligned
            ctx.system(
                f"aligned by text: {stats.matched_words}/{stats.total_words} words matched "
                f"({stats.coverage:.0%}), {stats.anchored_cues} cues anchored to measured "
                f"audio, {stats.interpolated_cues} interpolated"
            )
            return timed, SubtitleTimingSource.AUDIO_ALIGNED, stats.coverage

        if strategy == "align":
            raise ValidationError(
                "cue text could not be matched against the transcribed audio",
                user_message="متن زیرنویس با گفتار این فایل مطابقت ندارد.",
                hint=(
                    "اگر زیرنویس ترجمه‌شده است، حالت «توزیع روی بازه‌های گفتار» "
                    "را انتخاب کنید."
                ),
            )
        ctx.system(
            "text did not match the audio closely enough to align "
            "(a translated or heavily rewritten track); "
            "falling back to distribution over measured speech regions"
        )

    timed = distribute_over_speech(items, segments, rules, adjustments)
    ctx.system(f"distributed {len(timed)} cues across the measured speech regions")
    return timed, SubtitleTimingSource.SPEECH_DISTRIBUTED, 0.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _rules_from_input(ctx: JobContext, media_duration: float | None) -> TimingRules:
    settings = ctx.services.settings
    return TimingRules(
        min_duration=float(
            ctx.input.get("min_duration") or settings.get("subtitle.min_duration")
        ),
        max_duration=float(
            ctx.input.get("max_duration") or settings.get("subtitle.max_duration")
        ),
        gap=float(ctx.input.get("gap", 0.04)),
        media_duration=media_duration or None,
    )


def _scaled_progress(ctx: JobContext, *, floor: float, ceiling: float, staged: bool = False):
    """Map a sub-operation's 0-1 progress into a slice of the job's own bar."""

    def callback(fraction: float | None, label) -> None:
        if fraction is None:
            ctx.set_progress(None, label if staged else None)
            return
        ctx.set_progress(floor + (ceiling - floor) * fraction, label if staged else None)

    return callback
