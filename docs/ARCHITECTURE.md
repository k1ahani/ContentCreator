# Architecture

Read this first. It explains the shape of the system and *why* it is shaped
this way — the reasoning matters more than the diagram, because it tells you
which decisions are load-bearing and safe to lean on, and which were arbitrary
and safe to change.

## What this platform is

A local, single-user, Windows desktop-in-a-browser application for producing
video content: video → audio → transcript → edited/translated text →
subtitles → rendered video, plus a separate text → speech path. It runs a
FastAPI backend on `localhost` that also serves a built React frontend. There
is no multi-tenancy, no authentication, and no network exposure — see
`docs/SETTINGS.md` and the security notes below for what "local" actually
means for the threat model.

## The four layers, and why they're separate

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + TS)                                       │
│  Persian RTL pages, talk only to the HTTP API + SSE stream   │
└───────────────────────────┬───────────────────────────────────┘
                             │ HTTP + Server-Sent Events
┌───────────────────────────▼───────────────────────────────────┐
│  API layer (app/api/)                                        │
│  Thin routers: validate input, call a service, submit a job  │
└───────────────────────────┬───────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼───────┐   ┌────────▼────────┐  ┌────────▼────────┐
│  Job system    │   │  Provider layers │  │  Persistence    │
│  (app/jobs/)   │   │  ai / transcription│  │  (app/db/)      │
│  worker pool,  │   │  / tts             │  │  SQLite +       │
│  SSE events    │   │  (app/ai,          │  │  repositories   │
│                │   │   transcription,  │  │                 │
│                │   │   tts)             │  │                 │
└───────┬────────┘   └────────┬────────┘  └─────────────────┘
        │                     │
┌───────▼─────────────────────▼───────────────────────────────┐
│  Media layer (app/media/) — FFmpeg integration                │
│  External processes (app/process/) — the only place that      │
│  spawns a subprocess, for Claude CLI, FFmpeg, PowerShell/SAPI  │
└─────────────────────────────────────────────────────────────┘
```

**Why three provider layers instead of one "AI" layer.** The master
requirements ask for an `AIProvider` abstraction so GPT can be added later.
That abstraction is real (`app/ai/base.py`), but it only covers *text*
generation, because that is all a chat-completions-style CLI can do. Speech
recognition (audio → timed text) and speech synthesis (text → audio) are
different capabilities with different providers and different failure modes,
so they get their own parallel interfaces: `app/transcription/base.py` and
`app/tts/base.py`. All three follow the identical shape — abstract provider,
registry, availability that never throws, one facade callers use — so the
mental model transfers between them. See `docs/AI_SYSTEM.md`,
`docs/AI_PROVIDERS.md` and `docs/TTS_SYSTEM.md`.

**Why a job queue instead of handling everything in the request.**
Transcription, rendering and TTS synthesis can run for minutes to hours.
FastAPI request handlers must return quickly. Every long operation is
therefore: `POST` returns `202 Accepted` with a job id immediately, a worker
thread runs the actual work, and the frontend watches progress over one shared
SSE connection. See `docs/JOB_SYSTEM.md`.

**Why every subprocess call goes through one module.** `app/process/runner.py`
is the only place `subprocess.Popen` is called, ever. It guarantees argument
lists (never a shell string, so a Persian filename or a prompt containing `&`
can't be reinterpreted as syntax), UTF-8 I/O, live streaming output, real
cancellation (Windows process-tree kill via `taskkill`), and timeouts. The
Claude CLI wrapper, FFmpeg wrapper, and PowerShell/SAPI5 wrapper all sit on top
of it rather than calling `subprocess` themselves.

**Why the domain models have no framework code.** `app/domain/` is pure
Pydantic models with no FastAPI, no SQLite, no filesystem knowledge. Repositories
map database rows to these models; API schemas either reuse them directly or
wrap them for request/response shaping. This is what makes a domain type
usable from a job handler, a repository, and an API response without
duplication.

## Request flow, concretely

A representative feature — audio extraction — end to end:

1. User picks a video in the browser (`frontend/src/components/media/FilePickerDialog.tsx`,
   backed by `GET /api/system/browse`).
2. Frontend calls `POST /api/projects/{id}/assets/import` with the path.
   The router (`app/api/routers/projects.py`) validates the path through
   `app/core/security.py::validate_import_path` (extension allowlist, size cap,
   optional root restriction), probes it with FFmpeg, and registers a
   `media_assets` row.
3. Frontend calls `POST /api/projects/{id}/audio/extract`
   (`app/api/routers/jobs.py`), which submits a `JobCreate` to
   `ServiceContainer.jobs` (`app/jobs/queue.py`) and returns `202` with the job.
4. A worker thread picks up the job, builds a `JobContext`
   (`app/jobs/context.py`) and calls the registered handler
   (`app/jobs/handlers/audio_extract.py`).
5. The handler calls `app/media/audio.py::extract_audio`, which runs FFmpeg
   through `app/media/ffmpeg/runner.py`, which runs the process through
   `app/process/runner.py`, streaming progress and log lines back up through
   callbacks at every layer.
6. `JobContext` publishes `progress`/`log`/`done` events to the `EventBus`
   (`app/jobs/events.py`), which the frontend's shared `EventSource` receives
   at `GET /api/events` and routes to whichever page is watching that job id
   (`frontend/src/hooks/useJobRunner.ts`).
7. On completion the handler registers a new `media_assets` row (the
   extracted audio) and returns an output dict, which becomes the job's
   `output` field.

Every other feature (transcription, text editing, subtitle generation/render,
TTS) follows this same shape. See `docs/JOB_SYSTEM.md` for the job system
itself and `docs/API.md` for the full endpoint list.

## Composition root

`app/container.py::ServiceContainer` is where concrete implementations get
wired together — the database, the provider registries, the job queue. It is
constructed once in `app/main.py`'s lifespan handler and stored on
`app.state.container`; `app/api/deps.py::get_container` pulls it back out for
routers. Provider registries and the AI facade are built lazily and
invalidated when relevant settings change (`ServiceContainer.invalidate`), so
editing the Claude CLI path or FFmpeg path in Settings takes effect
immediately without a restart.

## Security model

This is a local, no-auth, single-user tool — see requirement 1.1 and
`docs/SETTINGS.md`. That does **not** mean the browser is trusted: a
compromised or malicious web page (or a bug in the frontend) can still send
arbitrary requests to `localhost`. The controls that matter are:

- **Path traversal**: `app/core/security.py::ensure_within` and
  `validate_import_path` are the only ways a string becomes a filesystem path.
- **Filename safety**: `sanitize_filename` handles Windows-reserved names,
  illegal characters, and trailing dots/spaces while preserving Persian text.
- **No shell**: `app/process/runner.py` never sets `shell=True`; every argument
  is a list element, immune to injection regardless of its content.
- **Extension allowlists**: `app/api/routers/projects.py::ALLOWED_EXTENSIONS`
  gates both import and upload.
- **CORS**: restricted to the Vite dev origin; in production the frontend is
  served from the same origin as the API, so cross-origin requests are moot.

See `app/core/security.py` for the implementation and
`backend/tests/unit/test_security.py` for the adversarial test cases (path
traversal, injection strings, reserved device names) that prove it holds.

## Where to go next

- New to the AI layer? Read `docs/AI_SYSTEM.md`, then `docs/AI_PROVIDERS.md`
  and `docs/AI_MODELS.md`.
- Touching media/FFmpeg? Read `docs/MEDIA_PROCESSING.md`, then the specific
  `docs/AUDIO_PROCESSING.md`, `docs/SUBTITLE_SYSTEM.md` or
  `docs/VIDEO_RENDERING.md`.
- Adding a feature? Start at `docs/EXTENDING_THE_APPLICATION.md`.
- Touching the database? Read `docs/DATABASE.md`.
- Touching the frontend? Read `docs/FRONTEND.md` and
  `docs/RTL_UI_GUIDELINES.md`.
