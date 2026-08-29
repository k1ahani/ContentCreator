# Text-to-Speech System (Feature 6)

## Purpose

How text becomes natural speech, including structured pauses. Two real
providers ship in v1 — this is what proves the provider abstraction is
genuine rather than aspirational (requirement: build the architecture around
abstractions even when v1 has few implementations).

## Provider interface

`app/tts/base.py::TTSProvider` — same shape as `AIProvider` and
`TranscriptionProvider` (see `docs/AI_SYSTEM.md`): `check_availability` never
raises, `list_voices` returns voices with rich metadata
(`app/domain/tts.py::VoiceSpec`: language, gender, age, supported styles,
pitch/rate support), `synthesize` renders **one continuous span of text** to
a file.

## Why pauses are not part of the provider interface

This is the key architectural decision in this layer, and it's what makes
requirement 23 ("pause control... not relying only on textual syntax")
actually work rather than being a thin wrapper around SSML `<break>` tags.

A `SpeechScript` (`app/domain/tts.py`) is an ordered list of `TextSegment` and
`PauseSegment` — pauses are structured elements the user can add, remove, and
reorder in the frontend's segment editor
(`frontend/src/components/tts/SpeechSegmentEditor.tsx`), never markers
embedded inside prose text. A `TTSProvider` only ever sees plain text for one
segment at a time — it has no pause concept at all. Assembly is a separate
module, `app/tts/assembler.py`, which:

1. Synthesizes each text segment through the provider, one file per segment.
2. Generates each pause as **real silence** of the exact requested duration
   via FFmpeg's `anullsrc` — not an SSML hint a provider might round or
   ignore.
3. Normalises every part (provider output and generated silence alike) to a
   shared intermediate format — 24 kHz mono PCM — before joining.
4. Concatenates with FFmpeg's `concat` demuxer and encodes the final output.

This design means pause behaviour is **identical across every provider,
including one with no SSML support at all**, and pause duration is exact
rather than advisory. It also means adding a third TTS provider never needs
to touch pause logic — that's entirely `assembler.py`'s job.

### Why normalise before concatenating

FFmpeg's `concat` *demuxer* (as opposed to the `concat` filter) requires
every input to share codec, sample rate and channel layout. Joining an MP3
from the neural provider directly with a WAV from SAPI5 without normalising
first produces either an outright error or silently corrupted audio at the
join points. Converting every part to the same intermediate PCM format first
makes the join sample-exact.

## Providers

### Edge (`app/tts/providers/edge.py`) — neural, online

Uses the `edge-tts` package against Microsoft's Edge read-aloud service.
**This is the provider that makes Persian actually usable**:
`fa-IR-DilaraNeural` (female) and `fa-IR-FaridNeural` (male) are genuine
neural Persian voices. Requires internet.

Style is expressed through **prosody shaping**, not the service's own style
tags (which aren't available for these voices) — `_STYLE_PROSODY` maps each
`SpeakingStyle` to a `(rate_multiplier, pitch_offset)` pair combined with the
user's own rate/pitch before being sent as edge-tts's signed
percentage/Hertz strings. This is an honest choice: the docstring says
explicitly that style here is real prosody manipulation, not a native
"friendly" mode the service doesn't actually expose for these voices.

Synthesis is async (the `edge_tts` API), run via `asyncio.run()` inside the
synchronous provider interface — correct because job handlers execute on
worker threads with no event loop of their own already running.

**Version pin matters.** `edge-tts==7.0.2` (the initially pinned version) was
found to fail with a `403 WSServerHandshakeError` against Microsoft's current
endpoint during real verification of this feature; `edge-tts==7.2.8` works.
If Persian synthesis starts failing with a 403/handshake error again, the
package version is the first thing to check — `pip install --upgrade
edge-tts` and re-pin in `backend/requirements.txt` and `pyproject.toml`.

### SAPI5 (`app/tts/providers/sapi5.py`) — offline

Drives Windows `System.Speech.Synthesis` through PowerShell (not a `pywin32`
COM binding, to avoid that dependency for one narrow feature). Fully offline,
zero external dependencies — but voices are whatever the machine has
installed, and a stock Windows install typically has **no Persian voice at
all**. `check_availability` reports this honestly via a Persian hint pointing
at the Edge provider instead of pretending SAPI5 covers Persian.

Text is passed to the PowerShell script via a temporary UTF-8-BOM file, not
inline in the command, specifically so Persian text with apostrophes or other
PowerShell-special characters can never break the script's quoting.

## Guarantees

- **Empty text is rejected before any provider call** (`TTSError`), in both
  the provider layer and `assembler.py`.
- **Pause duration is exact**, generated with `-t <seconds>` on `anullsrc`,
  not approximated.
- **A provider that produces no output file, or an empty one, is treated as
  failure** — checked explicitly after every synthesis call, never assumed
  from a zero exit code alone.

## Adding a TTS provider

Implement `TTSProvider` in `app/tts/providers/<name>.py`, register it in
`TTSRegistry.build()` (`app/tts/registry.py`) — append one line. It appears
automatically in `GET /api/ai/tts/providers` and `GET /api/ai/tts/voices`;
the frontend voice selector renders whatever the registry reports, with no
provider name ever hardcoded in `frontend/src/pages/project/SpeechPage.tsx`.

## Common mistakes

- **Embedding pause syntax in text sent to a provider.** Pauses are always
  separate `PauseSegment` entries; never encode `[pause:1.5s]` or similar into
  a text string passed to `synthesize()`.
- **Concatenating provider outputs without normalising first.** Always go
  through `assembler.py`; never call FFmpeg's concat demuxer directly on raw
  provider outputs of mixed formats.
- **Assuming a provider supports pitch.** Check `VoiceSpec.supports_pitch`
  before sending a non-zero pitch value — SAPI5 has no pitch control through
  this API surface, and the setting is honestly reported as unsupported
  rather than silently dropped.

## Testing

`backend/tests/integration/test_jobs_pipeline.py::TestTtsJob` runs a real
Persian synthesis with two structured pauses and asserts the total duration
exceeds the requested pause time (proof the pauses are actually in the audio,
not just requested) — it skips cleanly if the network is unavailable rather
than failing the whole suite.
