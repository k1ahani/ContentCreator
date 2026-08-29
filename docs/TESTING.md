# Testing

## Philosophy

**Nothing is mocked that doesn't have to be.** Every test in this suite runs
against real infrastructure: a real temporary SQLite database (migrated the
same way production is), real FFmpeg (building actual test video/audio with
`ffmpeg -f lavfi`), a real subprocess execution path, and — where available —
real Claude CLI calls.

This is a deliberate trade-off, not an oversight. A test that mocks FFmpeg
proves the code *calls* FFmpeg with certain arguments; it cannot prove those
arguments produce a working video. Several real bugs in this codebase were
only found by actually running the tool and inspecting the output:

- **Opus's fixed 48kHz decode rate** (`docs/AUDIO_PROCESSING.md`) — found by
  encoding the same source three different ways and diffing the output
  bytes; a mocked test would have happily asserted `-ar 16000` was passed and
  missed that the encoder ignores it entirely.
- **The FFmpeg working-directory requirement for the `subtitles` filter on
  Windows paths** (`docs/VIDEO_RENDERING.md`) — found by actually rendering a
  video with a Persian project name and a drive-letter path, and diffing a
  frame before/after to confirm subtitles were really burned in.
- **The UTF-8 BOM requirement for PowerShell 5.1** (`docs/DEVELOPMENT_GUIDE.md`)
  — found by actually launching `start.ps1` from a batch wrapper and reading
  the real parse error, which pointed at a completely unrelated line number
  until the BOM issue was understood.
- **edge-tts's 403 handshake failure on an outdated pinned version**
  (`docs/TTS_SYSTEM.md`) — found by actually attempting Persian speech
  synthesis, not by asserting the right function was called.

None of these would have been caught by a suite of mocks. Keep writing tests
this way.

## Running the suite

```powershell
cd backend
.venv\Scripts\python.exe -m pytest              # everything (260+ tests)
.venv\Scripts\python.exe -m pytest -m "not slow" # skip real Claude CLI calls
.venv\Scripts\python.exe -m pytest tests/unit     # fast, no external process dependency (mostly)
.venv\Scripts\python.exe -m pytest tests/integration  # real FFmpeg/DB/job pipeline
```

## Structure

```
backend/tests/
├── conftest.py              shared fixtures (container, project, sample_video, wait_for_job)
├── unit/
│   ├── test_security.py      path traversal, filename sanitisation, import validation
│   ├── test_subtitles.py     timecode, ASS colour/alignment, segmentation, serialisation
│   ├── test_ai.py             recommendation scoring, prompt rendering, output cleanup
│   ├── test_settings.py       default overlay, type/semantic validation
│   ├── test_database.py       repositories against a real temp SQLite DB
│   └── test_process.py        real subprocess execution, shell-injection resistance, cancellation
└── integration/
    ├── test_media_pipeline.py  real FFmpeg: audio extraction, subtitle burn-in
    ├── test_jobs_pipeline.py    the full job system against real handlers
    └── test_api.py              FastAPI TestClient against a real container
```

The `unit`/`integration` split here is about **scope**, not about mocking —
`test_process.py` (unit) launches real Python subprocesses; `test_database.py`
(unit) uses a real SQLite file. "Integration" means "exercises multiple layers
together through the job system or the HTTP API," not "the only place real
I/O happens."

## Key fixtures (`conftest.py`)

- **`container`** — a fully wired `ServiceContainer` against a temporary
  database (`AppConfig(database_path=tmp_path / "test.db")`), with proper
  startup/shutdown and project-workspace cleanup afterward.
- **`ffmpeg_tools`** — real FFmpeg, resolved once per test session; **skips**
  (not fails) any test that needs it if FFmpeg isn't installed, so the suite
  stays useful on a machine that hasn't run `scripts/setup.ps1` yet.
- **`sample_video`** — a real 4-second H.264+AAC file, generated with
  `ffmpeg -f lavfi` (no binary fixture files committed to the repo).
- **`client`** — a FastAPI `TestClient` wired to the same `container` fixture
  a test can otherwise inspect directly, with the app's own `lifespan` bypassed
  (the fixture already owns startup/shutdown, so running both would migrate
  twice and start two job-worker pools).
- **`wait_for_job`** — polls a job to a terminal state with a timeout, used by
  every integration test that submits a job.

## Marks

- **`@pytest.mark.slow`** — a test that makes a real Claude CLI call (costs
  money, needs the CLI logged in). Skips cleanly
  (`pytest.skip("Claude CLI not available")`) rather than failing when the CLI
  isn't present, so the rest of the suite stays green on a machine without it.

## What proves a feature actually works, not just that code ran

A pattern worth preserving when adding tests for a new feature: assert on the
**observable effect**, not just a successful return.

```python
# Weak: only proves ffmpeg exited 0
result = render_subtitles(...)
assert result.output_path.is_file()

# Strong: proves subtitles were actually drawn into the pixels
frame_before = extract_frame(source, at=1.0)
frame_after = extract_frame(result.output_path, at=1.0)
assert frame_before != frame_after
```

```python
# Weak: only proves the TTS call didn't raise
result = assemble_speech(script_with_pauses, ...)
assert result.output_path.is_file()

# Strong: proves the requested silence is actually in the audio
assert result.duration_seconds > script.total_pause_seconds
```

Both of these patterns are in the real test suite
(`test_media_pipeline.py::TestSubtitleRendering::test_rendered_frame_differs_from_source`,
`test_jobs_pipeline.py::TestTtsJob`).

## Adding tests for a new feature

1. Unit-test any pure logic in isolation (scoring, formatting, validation,
   parsing) — fast, no external process needed unless the logic genuinely
   requires one (process execution, database behaviour).
2. Integration-test the job handler end to end against real infrastructure,
   asserting on the observable output as above, not just `status ==
   "completed"`.
3. If it's a new API endpoint, add a case to `test_api.py` covering the
   success path and at least one realistic failure (missing resource,
   invalid input) with the exact error `code` the frontend will branch on.

## Frontend

No automated frontend test suite exists yet (v1 relies on `tsc --noEmit` for
type safety and manual verification of each page against the real running
backend during development). If adding one, prefer testing against a real
running backend instance the way the Python integration tests do, rather than
mocking `fetch` — the same "don't mock what you can run for real" philosophy
applies.
