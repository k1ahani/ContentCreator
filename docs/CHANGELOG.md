# Changelog

Format: newest first. Each entry names what changed, why (when non-obvious),
and which docs were updated alongside it. Keep this current — it's the
fastest way for a future agent to see what's actually shipped versus what the
original requirements document merely asked for.

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
