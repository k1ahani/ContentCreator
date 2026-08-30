# Changelog

Format: newest first. Each entry names what changed, why (when non-obvious),
and which docs were updated alongside it. Keep this current — it's the
fastest way for a future agent to see what's actually shipped versus what the
original requirements document merely asked for.

## 1.3.0 — Subtitle synchronisation, voice providers + previews, manual text workflow (2026-08-30)

### Subtitle synchronisation (two methods, as required)

- **Automatic, from the video's audio.** New `JobType.SUBTITLE_SYNC`
  (`app/jobs/handlers/subtitle_sync.py`, `POST .../subtitles/sync`): re-extracts
  the audio to `temp/`, runs the existing speech-recognition layer, and moves
  the *existing* cues onto the measured word timings. Cue text is never
  touched. Alignment matches cue text to the ASR word stream with
  `difflib.SequenceMatcher` (`timing_source: audio_aligned`) and falls back to
  distributing cues over the measured speech regions when the text does not
  match — a translated track, say (`speech_distributed`). Both are reported
  honestly rather than presented as equally good.
- **Manual/batch.** `POST .../subtitles/{track}/retime` with four modes:
  `shift`, `reading_speed` (the "subtitle display speed" control — each cue's
  duration derived from its own text length at a target characters-per-second),
  `scale` and `stretch`. Applies to every cue as a group. Answers inline rather
  than as a job: it reads no media, so a progress bar would be theatre.
- **Render artefacts.** Every timing write now ends in
  `sync.py::sanitize`, and the render handler additionally runs
  `prepare_for_render`, which drops blank cues (with the default opaque-box
  style they render as an empty black bar over the picture) and separates
  overlapping cues with at least the one-centisecond resolution of an ASS
  timecode (libass draws every cue covering a frame, so overlaps stack). The
  sidecar `.srt` uses the same corrected cues, so it can never disagree with
  the burned-in video.
- **Bug found by real verification.** The sync job originally ran Whisper
  without the Persian seed prompt the transcribe handler uses. Whisper
  conditions its output on that prompt, so the same audio came back worded
  differently and a track built from the platform's own transcript failed to
  match the platform's own re-listening — silently degrading every such sync to
  the fallback path. Both calls were individually correct, so no unit test could
  see it; only running the two in sequence against real audio did. Guarded by
  `TestSubtitleSyncJob::test_aligns_a_track_built_from_this_video_s_own_transcript`.
- Migration `0002_subtitle_sync_job.sql` widens the `jobs.type` CHECK. It
  rebuilds both `jobs` and `job_logs` in a specific order, because dropping
  `jobs` with foreign keys on would cascade and erase the console-log history.

### Speech: two more providers, many more voices, audible previews

- **38 Microsoft neural voices** (was 6): both Persian voices plus English
  across fourteen locales. `VoiceSpec.locale` carries the BCP-47 tag, because
  with this many English voices the accent *is* the choice being made and
  `Language` cannot express it.
- **ElevenLabs** (`freemium`, API key) and **any OpenAI-compatible endpoint**
  (`app/tts/providers/openai_compatible.py`). The latter is written against the
  protocol rather than a vendor, so the same code path drives OpenAI's paid
  endpoint and a free self-hosted server — point `voice.openai_base_url` at
  `http://localhost:8880/v1` and synthesis is free and fully offline.
- **Voice previews**: `GET /api/ai/tts/voices/{id}/preview` plays a hosted
  sample when the provider publishes one (free, spends no quota) and otherwise
  synthesises one short sentence, cached on disk per voice and sample text. The
  new `VoicePicker` component gives every voice a play button.
- `TTSProviderInfo` gained `pricing`, `requires_api_key` and `api_key_setting`
  so the UI distinguishes "not set up yet" from "broken", and the settings page
  lists live provider status next to the credential fields.
- `ServiceContainer.invalidate` now *rebuilds* the TTS registry on a `voice.*`
  change instead of clearing its availability cache — a credential is baked in
  at construction, so the cache clear alone left the old key in use.

### Text editing without the AI

- The AI Result box is a real textarea: paste, edit, or write a translation by
  hand and Apply or save it exactly as if the model had produced it, so the page
  stays usable on a network where the AI CLIs are blocked. "ذخیره به‌عنوان سند"
  turns it into a new `TextDocument` continuing the source's version chain.
- A **دستور دلخواه** chip sits alongside the built-in prompts in every mode. The
  instruction persists in `ai.custom_prompt` and is pre-filled in future
  projects — a setting rather than a `prompts` row because it is one global
  "what I was last doing" value, not a named template in a curated library.

Docs updated: `SUBTITLE_SYSTEM.md`, `TTS_SYSTEM.md`, `TEXT_PROCESSING.md`,
`API.md`, `DATABASE.md`, `JOB_SYSTEM.md`, `SETTINGS.md`.

## 1.2.0 — Subtitle segmentation modes + editor layout fix (2026-08-29)

- `SubtitleEditorPage.tsx`: fixed the video preview overflowing the page and
  the style panel dropping below the video on large screens. Root cause was
  CSS Grid's `min-width: auto` default — the timeline's own wide, fixed-pixel
  track div was setting the intrinsic minimum width of its whole grid column,
  which both defeated the timeline's existing `overflow-x-auto` (nothing to
  scroll if the column never shrinks) and inflated the video preview sized off
  that same column. Fix was `min-w-0` on both grid-item columns, keeping the
  `xl:grid-cols-[1fr_320px]` template so the style panel stays side-by-side on
  large screens.
- New `SubtitleSegmentationMode` (`sentence` / `automatic` / `short` /
  `normal` / `custom`) controls how generated cue boundaries are chosen from a
  transcript — a request-level choice (`GenerateSubtitleRequest.segmentation_mode`,
  `words_per_cue` for `custom`), independent of the timed-vs-untimed timing
  source. `automatic` is the pre-existing character-length cascade and stays
  the default; the other four bypass it entirely (`short`=3 words/cue,
  `normal`=6 words/cue, `custom`=user-chosen 1–20 words/cue, `sentence`=one
  cue per complete sentence). `_merge_tiny` (re-combining implausibly short
  cues) now only runs for `automatic`, since a short cue in any other mode is
  the user's deliberate choice, not a defect. See `docs/SUBTITLE_SYSTEM.md`
  for the full behaviour table.
- "ساخت زیرنویس از رونوشت" dialog (`SubtitlesPage.tsx`) gained a mode picker
  and a conditional word-count field for `custom`.
- 10 new tests (284 → 294), covering all five modes against both timed
  segments and untimed text, plus overlap/ordering and never-splits-mid-word
  checks for the fixed-word-count modes.

## 1.1.0 — Second AI provider: OpenAI Codex (2026-08-29)

Proves the provider abstraction from 1.0.0 was real rather than aspirational:
a second text-generation provider, driven through OpenAI's official Codex CLI
(`npm install -g @openai/codex`), registered alongside Claude with zero
changes to `AIService`, the job handlers, or the recommendation engine.

- `app/ai/providers/codex/` - detection, CLI wrapper, provider implementation,
  following the exact same shape as the Claude integration. Verified against
  a real install (`codex-cli 0.150.1`) during development; see
  `docs/CLI_INTEGRATION.md` for what was confirmed directly versus what could
  not be (no valid Codex credentials were available - the design routes
  around that gap rather than assuming past it, most notably by reading the
  answer from `-o/--output-last-message` instead of an unverified JSONL
  success-event schema).
- Availability checking uses `codex login status` (fast, local, confirmed
  ~0.2s) rather than a live call - an unauthenticated `codex exec` was
  measured taking ~35-40 seconds to fail, which would have made the provider
  selector feel broken.
- Settings -> AI gained a real provider picker (segmented control, live
  availability per provider, both CLI-path fields always visible) instead of
  Claude being the only implicit option. Switching providers resets the
  default-model field, since a model id from one provider is not valid for
  the other.
- `ModelSelector.tsx`, used throughout the feature pages, now follows the
  user's configured default provider when a caller does not pin one
  explicitly - choosing Codex in Settings actually changes what every page
  recommends, not just the Settings page's own preview.
- `app/ai/models.py` gained a single `codex-default` registry entry rather
  than a list of named Codex model snapshots - see `docs/AI_MODELS.md` for
  why (Codex's own reported default model name during testing did not match
  common assumptions about current OpenAI product naming, which is direct
  evidence a hardcoded list would already be wrong).
- Docs updated: `AI_PROVIDERS.md`, `CLI_INTEGRATION.md` (broadened to cover
  both CLIs), `AI_MODELS.md`, `SETTINGS.md`, `EXTENDING_THE_APPLICATION.md`.
- 24 new tests (260 → 284), including a live-but-skippable suite
  (`TestCodexProviderLive`) that asserts the availability check stays fast
  against the real installed CLI.
- A new top-level `README.fa.md` - a comprehensive, fully Persian guide aimed
  at public GitHub visitors (features, prerequisites, install, configuration,
  troubleshooting), linked from `README.md` and from `docs/DEVELOPMENT_GUIDE.md`.

## 1.0.0 — Initial platform (2026-08-29)

First production-ready version. Every feature in the acceptance criteria is
implemented against real infrastructure — no placeholder buttons, no mocked
providers.

**Architecture**
- Provider-neutral layers for text AI (`app/ai/`), speech recognition
  (`app/transcription/`), and speech synthesis (`app/tts/`) — Claude, local
  Whisper, and Edge/SAPI5 are the v1 implementations; each layer documented
  as an extension seam in `docs/AI_PROVIDERS.md`, `docs/AI_SYSTEM.md`,
  `docs/TTS_SYSTEM.md`.
- Background job system with a shared SSE event bus for live progress
  (`docs/JOB_SYSTEM.md`).
- SQLite persistence via a repository pattern, forward-only migrations
  (`docs/DATABASE.md`).
- FastAPI backend also serves the built React frontend from one origin — no
  authentication anywhere, by design (`docs/ARCHITECTURE.md`).

**Feature 1 — Video → Audio**
- Speech-optimised extraction with three presets (Opus/MP3/WAV), mono, tuned
  for ASR rather than fidelity (`docs/AUDIO_PROCESSING.md`).
- Verified empirically that Opus always decodes at 48kHz regardless of the
  requested `-ar` — the preset system accounts for this rather than
  requesting a rate the codec can't produce.

**Feature 2 — Audio → Text**
- Two-stage pipeline: local faster-whisper for real, timed transcription
  (stage 1), optional Claude refinement pass for punctuation/spelling
  (stage 2) — explicitly not one blurred "AI transcribes audio" step, since no
  LLM CLI accepts audio (`docs/AI_SYSTEM.md`).

**Features 3 & 4 — Text editing & translation**
- The AI never overwrites the original: every AI text operation creates a new
  versioned document; "apply" is a separate, explicit frontend action
  (`docs/TEXT_PROCESSING.md`).
- Custom prompts with a built-in template library plus user-saved prompts,
  schema already shaped for future variables/categories/history.

**Feature 5 — Subtitles**
- Structured cue model (never a text blob), generated from real ASR word
  timings where available, from proportional estimation otherwise — and the
  distinction is surfaced to the user (`docs/SUBTITLE_SYSTEM.md`).
- Full timeline editor: drag-to-move, drag-to-resize, click-to-seek,
  click-to-select, split/merge, live-styled preview that matches the actual
  burned-in render pixel-for-pixel in relative sizing.
- FFmpeg subtitle burn-in with a Windows path-escaping workaround (relative
  filename + working directory, never an absolute path in the filtergraph) —
  see `docs/VIDEO_RENDERING.md`.

**Feature 6 — Text → Speech**
- Structured pause segments (never textual markup) rendered as real silence
  and assembled with the spoken segments via FFmpeg concat
  (`docs/TTS_SYSTEM.md`).
- Two real providers: Edge neural (genuine Persian voices, online) and SAPI5
  (fully offline, honest about its lack of Persian voices on a stock Windows
  install).
- Found and fixed a real `edge-tts` version incompatibility (7.0.2 → 7.2.8)
  during verification — see `docs/TTS_SYSTEM.md`.

**Platform**
- Persian RTL UI throughout, with LTR islands for technical content
  (`docs/RTL_UI_GUIDELINES.md`).
- Responsive layout: mobile drawer sidebar, horizontally-scrollable timeline,
  touch-friendly controls.
- Dependency doctor on the dashboard and Settings page reporting FFmpeg,
  Claude CLI, ASR engine and TTS provider availability with Persian
  explanations and fixes.
- `scripts/setup.ps1` provisions everything (Python via `uv`, FFmpeg,
  frontend build) in one idempotent run; `start.bat`/`start.ps1` launch the
  platform with automatic port-conflict recovery (Windows reserves ranges for
  Hyper-V/WinNAT — see `docs/DEVELOPMENT_GUIDE.md`).
- 260+ tests, all against real infrastructure — no mocked FFmpeg, database, or
  (where available) Claude CLI. See `docs/TESTING.md`.

**Known limitations, deliberately left for later**
- Language pickers in a few pages (transcription, TTS) are hardcoded fa/en
  toggles rather than rendering from a dynamic language list — adding a third
  language would need those specific components updated (see
  `docs/EXTENDING_THE_APPLICATION.md`'s language section).
- No automated frontend test suite yet (relies on `tsc --noEmit` plus manual
  verification against the real backend during development —
  `docs/TESTING.md`).
- GPT/Gemini/other providers are not implemented — only the extension seam
  exists (`docs/AI_PROVIDERS.md`).
