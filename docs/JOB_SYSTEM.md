# Job System

## Purpose

Every long-running operation (audio extraction, transcription, text
processing, subtitle generation/render, TTS synthesis) runs as a background
job so FastAPI request handlers stay fast and the frontend can watch progress
live. This document covers the queue, the event bus that feeds Server-Sent
Events, and how to add a new job type.

## Architecture

```
app/jobs/
├── queue.py       JobQueue - worker thread pool, job lifecycle
├── context.py     JobContext - what a handler receives
├── events.py      EventBus - thread-safe publisher feeding SSE
├── registry.py    JobType -> handler mapping, startup completeness check
└── handlers/       one module per JobType
```

## Why threads, not processes

Every long operation here releases the GIL while it runs — they're all either
a subprocess wait (FFmpeg, the Claude CLI) or a native inference loop
(CTranslate2 for Whisper). A process pool would add IPC and Windows
process-spawn cost for zero benefit; a fixed thread pool
(`ServiceContainer.config.job_workers`, default 2) is strictly simpler and
just as parallel for this workload.

## Job lifecycle

```
submit() -> queued -> mark_running() -> running -> mark_completed()/mark_failed()/mark_cancelled()
```

`JobQueue.submit` (`queue.py`) validates the job type has a handler *before*
creating the database row (`get_handler(data.type)` raises immediately for an
unknown type), creates the row via `JobRepository.create`, and pushes the job
id onto an in-process `queue.Queue`. A worker thread pulls it, builds a
`JobContext`, and calls the registered handler — a plain function
`(JobContext) -> dict`.

**Durability is deliberately modest.** The queue lives in memory; jobs do not
survive a process restart. Anything left `queued`/`running` when the process
dies is marked `failed` at the next startup
(`JobRepository.requeue_orphans`, called from `ServiceContainer.startup`)
rather than sitting in the UI forever looking like it's still running. For a
single-user local tool this is the right trade — a persistent, restart-surviving
queue is real machinery that a rare edge case doesn't justify here.

## What a handler receives: `JobContext`

`app/jobs/context.py`. The one object every handler touches:

- `ctx.input` / `ctx.require(key)` — the job's input dict, with `require`
  raising loudly (`KeyError`) if a required key is missing, rather than a
  handler silently proceeding with `None`.
- `ctx.project_dir(subdir)` — a project workspace subdirectory
  (`source`/`audio`/`transcript`/`subtitles`/`voice`/`rendered`/`temp`),
  created on demand.
- `ctx.set_progress(fraction, stage)` — updates the database row and
  publishes a `progress` SSE event in one call. `fraction` is `0.0`-`1.0` or
  `None` for unmeasurable work; `stage` is a short Persian sentence shown
  under the progress bar.
- `ctx.log(stream, text)` / `ctx.system(text)` — console output. Published to
  SSE **immediately** (live console) but persisted to the database in
  **batches** (every 40 lines or 2 seconds, whichever comes first) —
  a hard requirement for anything FFmpeg-driven, which can emit thousands of
  progress lines; one `INSERT` per line would dominate a render's actual
  runtime.
- `ctx.cancel_token` / `ctx.raise_if_cancelled()` — see cancellation below.
- `ctx.services` — the `ServiceContainer`, giving access to every repository
  and provider registry a handler could need.

## Cancellation

Every job gets its own `CancelToken` (`app/process/runner.py`), tracked in
`JobQueue._cancel_tokens` while running. `JobQueue.cancel(job_id)`:

- If the job is still queued (no token yet — no worker has picked it up), it's
  marked cancelled immediately.
- If it's running, the token is set; the handler (and everything it calls —
  FFmpeg, the Claude CLI, the ASR engine) is expected to check it and stop.
  For an external process, cancellation kills the **entire process tree**
  (`taskkill /F /T` — see `docs/ARCHITECTURE.md`'s security section and
  `app/process/runner.py::kill_process_tree`), because `Popen.kill()` alone
  only kills the direct child and the Claude CLI in particular spawns a Node
  process tree.

Verified end-to-end in
`backend/tests/integration/test_jobs_pipeline.py::TestJobCancellation`: a
60-second render, cancelled after ~1.5 seconds, confirmed stopped within
15 seconds total.

## Live updates: the event bus

`app/jobs/events.py::EventBus`. The threading problem it solves: job handlers
run on worker **threads**, but the SSE endpoint (`GET /api/events`, in
`app/api/routers/jobs.py`) is an **async** generator on FastAPI's event loop.
`asyncio.Queue` isn't thread-safe, so a worker can't `put` to it directly —
every publish is marshalled onto the loop via
`loop.call_soon_threadsafe`. The loop reference is captured once at startup
(`container.events.bind_loop(asyncio.get_running_loop())` in
`app/main.py`'s lifespan handler).

One SSE connection serves the **entire application** — the frontend opens a
single shared `EventSource` (`frontend/src/lib/api/events.ts::jobEventBus`)
and every page filters by `job_id` client-side, rather than opening a
connection per watched job. Per-subscriber queues are bounded (500 events);
a slow consumer drops its oldest event rather than growing without bound.

Four event kinds, one envelope (`JobEvent`, `app/domain/job.py`): `status`,
`progress`, `log`, `done` — `kind` decides which other fields are meaningful,
keeping both the backend publisher and the frontend reducer small.

## Adding a job type

1. Add a member to `JobType` (`app/domain/enums.py`).
2. Create `app/jobs/handlers/<name>.py` with a function decorated
   `@register_handler(JobType.X)`.
3. Import the module in `app/jobs/registry.py::load_handlers`.
4. `verify_complete()` (called from `ServiceContainer.startup`) asserts every
   `JobType` has a registered handler — **a job type without one is a startup
   error**, not a runtime surprise a user discovers by clicking a button that
   silently does nothing.
5. Add a router endpoint that submits it (`app/api/routers/jobs.py`) and a
   corresponding request schema if needed (`app/api/schemas/requests.py`).

A handler is a plain function:

```python
@register_handler(JobType.MY_NEW_JOB)
def handle_my_new_job(ctx: JobContext) -> dict:
    asset_id = ctx.require("asset_id")
    ctx.set_progress(0.0, "در حال آماده‌سازی")
    # ... do the work, calling ctx.set_progress / ctx.log as it proceeds ...
    ctx.set_progress(1.0, "کامل شد")
    return {"result": "..."}   # becomes job.output
```

Raise an `AppError` subclass (`app/core/errors.py`) for any expected failure —
the queue catches it, logs the technical `message`, and reports the Persian
`user_message` (plus `hint`, if set) as the job's `error`. An unexpected
exception is also caught (a handler can never crash a worker thread) and
reported as a generic Persian internal-error message, with the real exception
logged to `logs/app.log`.

## Common mistakes

- **Doing slow work in an API route instead of a job.** If an operation could
  take more than roughly a second, it belongs in a job — routes should submit
  and return `202` immediately.
- **Writing to the database on every log line.** Always let `ctx.log` batch;
  never call `JobRepository.append_log` directly from a handler for
  high-frequency output.
- **Forgetting to check `cancel_token` in a loop.** Any handler with its own
  iteration (not just a single external process call) should call
  `ctx.raise_if_cancelled()` periodically.

## Testing

`backend/tests/integration/test_jobs_pipeline.py` runs every handler against
real infrastructure — real FFmpeg, a real temporary database, and (for
`TestTextTaskJob`, marked `@pytest.mark.slow`) a real Claude CLI call —
including the failure path (missing asset → Persian error, no stack trace
leaked) and the cancellation path described above.
