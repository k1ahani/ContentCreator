# Audio Processing (Feature 1: Video → Audio)

## Purpose

`app/media/audio.py::extract_audio` — pull a speech-optimised audio track out
of a video, for the transcription stage that follows it. Read
`docs/MEDIA_PROCESSING.md` first for the shared FFmpeg plumbing this builds on.

## Design goal

Not maximum audio fidelity — **the smallest file that still transcribes
well**. Three decisions follow directly:

**Mono.** Speech recognition collapses channels internally anyway;
downmixing before encoding halves the data for free.

**16 kHz sample rate, where the codec allows it.** Whisper-family models
resample to 16 kHz internally regardless of input rate, so anything higher is
wasted bytes. 16 kHz retains everything up to 8 kHz, which covers the full
intelligibility range of speech.

**Opus is the exception, and this was verified empirically, not assumed.**
The Ogg Opus mapping always declares a 48 kHz decode rate — `-ar 16000` is
silently ignored for the `libopus` encoder. This was confirmed by encoding the
same source three ways (`-ar` before the codec args, after them, and via an
explicit `aformat` filter) and diffing the output: byte-identical in all three
cases, always 48 kHz. So the `opus` preset does not request a rate it cannot
get — `AudioPreset.sample_rate = None` for that preset specifically, and
`extract_audio` only appends `-ar` when a preset actually has one. This costs
nothing: Opus encodes the actual speech bandwidth internally regardless of the
container's declared rate.

## Presets

| id | codec | rate | ~size/hour | when to use |
|---|---|---|---|---|
| `opus` (default) | libopus, 24 kbps, VOIP mode | 48 kHz (fixed) | ~15 MB | best size/quality ratio for speech |
| `mp3` | libmp3lame, 64 kbps | 16 kHz | ~29 MB | when a downstream tool can't read Opus |
| `wav` | pcm_s16le | 16 kHz | ~110 MB | difficult/noisy source audio, highest fidelity |

All three are mono; only the codec (and therefore achievable rate) differs.
Configurable per-call and via the `media.audio_preset` setting. See
`app/media/audio.py::AUDIO_PRESETS` for the exact FFmpeg arguments.

## Guarantees

- **The source video is opened read-only and never modified.** The output
  always goes to a freshly allocated path via
  `app/core/security.py::unique_path` inside `storage/projects/<id>/audio/`.
- **A file with no audio stream is rejected before FFmpeg runs**
  (`probe.has_audio` check), with a Persian message rather than a cryptic
  FFmpeg error about a missing stream.
- **An empty output is treated as failure**, not success — `extract_audio`
  checks the output file size and raises `MediaError` if FFmpeg somehow
  produced nothing.

## Flow

`app/jobs/handlers/audio_extract.py` (the `JobType.AUDIO_EXTRACT` handler):

1. Look up the source asset, resolve the preset (explicit input, else the
   `media.audio_preset` setting).
2. Call `extract_audio`, streaming progress and FFmpeg log lines into the job
   context (feeds the live CLI console).
3. Register the output as a new `media_assets` row of type `audio`, with
   metadata including the compression ratio, sample rate and preset used.
4. Return a summary (`input_size_bytes`, `output_size_bytes`,
   `compression_ratio`, `duration_seconds`, `processing_seconds`) as the job's
   output — this is exactly what the "استخراج فایل صوتی" page renders as its
   result stats.

## Adding a preset

Add an `AudioPreset` entry to `AUDIO_PRESETS` in `app/media/audio.py` with its
own `codec_args` and `sample_rate` (or `None` if the codec fixes its own
rate — verify this empirically the same way Opus was, don't assume). It
appears automatically in `GET /api/system/media` and therefore in the preset
picker on the audio extraction page — no frontend change needed.

## Common mistakes

- **Assuming every codec honours `-ar`.** Verify empirically (encode + probe
  the actual output) before trusting a codec's rate behaviour, the way Opus's
  was verified here.
- **Extracting more than one audio stream.** `extract_audio` explicitly maps
  `0:a:0` — only the first audio stream — since a video can have multiple
  audio tracks (commentary, alternate languages) and picking the first is the
  sane default rather than an accident of FFmpeg's own stream selection.

## Testing

`backend/tests/integration/test_media_pipeline.py::TestAudioExtraction`
extracts real audio with every preset from a generated test video and asserts
on the actual output: channel count, playable duration, size reduction versus
source, and that the source file's byte size is unchanged afterward.
