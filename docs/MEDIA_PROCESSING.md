# Media Processing

## Purpose

The shared FFmpeg integration every media feature builds on:
discovery, execution with real progress, and inspection. Read this first,
then `docs/AUDIO_PROCESSING.md` (Feature 1) or `docs/VIDEO_RENDERING.md` +
`docs/SUBTITLE_SYSTEM.md` (Feature 5) for the feature-specific pieces.

## Architecture

```
app/media/
├── ffmpeg/
│   ├── locator.py    find a working ffmpeg/ffprobe pair
│   ├── runner.py      run ffmpeg with real progress + live log lines
│   └── probe.py        ffprobe -> normalised MediaProbe
├── audio.py            Feature 1: video -> speech-optimised audio
├── video.py             Feature 5: subtitle burn-in rendering
└── subtitles/
    ├── formats.py       SRT/VTT/ASS serialisation and SRT parsing
    ├── style.py          SubtitleStyle -> ASS style line
    └── segmentation.py   transcript -> readable subtitle cues
```

Every function here takes an already-resolved `FFmpegTools` (never calls
`find_ffmpeg` itself) so callers control exactly which FFmpeg is used and
tests can pass a specific one without patching global state.

## Discovery

`app/media/ffmpeg/locator.py::find_ffmpeg`, resolution order: `media.ffmpeg_path`
setting → `FFMPEG_PATH` env var → **bundled** `bin/ffmpeg/` → `PATH`.

The bundled copy is preferred over `PATH` deliberately: it's version-pinned
with the project (`scripts/setup.ps1` downloads a specific gyan.dev
essentials build), so a system-wide FFmpeg upgrade elsewhere on the machine
can't silently change extraction or rendering behaviour. `ffprobe` is always
resolved from the same directory as `ffmpeg` — a mismatched pair is a
confusing failure mode worth avoiding entirely.

`require_ffmpeg()` raises `FFmpegNotFoundError` (Persian message, actionable
hint) when nothing works; `find_ffmpeg()` returns `None` for status-reporting
call sites (the dashboard's dependency doctor, `GET /api/system/status`) that
need to render an "unavailable" state rather than fail the whole page.

## Execution with real progress

`app/media/ffmpeg/runner.py::run_ffmpeg`. The key decision: progress comes
from `-progress pipe:1`, which makes FFmpeg emit machine-readable `key=value`
lines on **stdout**, not from scraping the human-readable status line on
stderr. The stderr format is not stable across FFmpeg builds and interleaves
with warnings; the progress stream is documented and reliable.

Every call gets `-hide_banner -y -nostdin -progress pipe:1 -nostats` added
automatically — callers pass only the operation-specific arguments. `-y`
is safe here because the output path is *always* a freshly allocated,
non-colliding path inside the project workspace (see
`app/core/security.py::unique_path`); a source file is never passed as an
output.

Duration is read from the FFmpeg banner's `Duration:` line as a fallback when
the caller didn't already know it from a probe, so progress fractions are
available even without a prior `probe_media` call.

## Inspection

`app/media/ffmpeg/probe.py::probe_media` runs `ffprobe -show_format
-show_streams` and normalises the JSON into `MediaProbe` (duration, codecs,
resolution, sample rate, channels, has_video/has_audio). Every other module
in this layer uses this rather than parsing ffprobe output itself.

## Cancellation

Every long-running FFmpeg call accepts a `CancelToken`
(`app/process/runner.py`). Cancelling kills the whole process tree via
`taskkill /F /T`, not just the direct child — verified in
`backend/tests/integration/test_jobs_pipeline.py::TestJobCancellation`, which
starts a 60-second render and confirms it stops within seconds of cancellation.

## Common mistakes

- **Calling `subprocess` or a different FFmpeg wrapper directly.** Everything
  goes through `run_ffmpeg`, which is what guarantees consistent flags,
  progress reporting, and cancellation.
- **Writing output over the input path.** Every extraction/render function
  allocates a fresh output path with `unique_path`; never pass the source path
  as `-y <source>`.
- **Forgetting `cwd` for filtergraphs that reference local files** (subtitle
  rendering). See `docs/VIDEO_RENDERING.md` for why this matters specifically
  for the `subtitles` filter on Windows.

## Testing

`backend/tests/integration/test_media_pipeline.py` builds real test video with
`ffmpeg -f lavfi` and asserts on real output: mono channel count, size
reduction, playable duration, and — for rendering — that a frame extracted
after the burn-in differs byte-for-byte from the same frame in the source
(proof subtitles were actually drawn, not just that the process exited 0).
