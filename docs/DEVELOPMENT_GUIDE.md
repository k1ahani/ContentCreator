# Development Guide

How to work on this codebase, whether you're a human or an AI coding agent
picking this project back up in a future session.

Looking for the user-facing guide instead - what this platform does,
prerequisites, installation, configuration? That's
[`README.fa.md`](../README.fa.md) (Persian, comprehensive) or
[`README.md`](../README.md) (bilingual summary) at the project root. This
document and the rest of `docs/` are for people changing the code itself.

## Read the docs before you touch a subsystem

This is a convention, not a suggestion. Before modifying an area, read its
doc first — the code has already made decisions (often for non-obvious
reasons, like the Opus 48kHz sample rate quirk in `docs/AUDIO_PROCESSING.md`,
or the UTF-8 BOM requirement in `docs/CLI_INTEGRATION.md`) that a fresh read of
the code alone won't surface.

| Touching... | Read first |
|---|---|
| Subtitles (format, style, timeline, segmentation) | `docs/SUBTITLE_SYSTEM.md`, `docs/VIDEO_RENDERING.md` |
| AI providers, models, prompts | `docs/AI_SYSTEM.md`, `docs/AI_PROVIDERS.md`, `docs/AI_MODELS.md` |
| Claude CLI invocation specifically | `docs/CLI_INTEGRATION.md` |
| Audio extraction | `docs/AUDIO_PROCESSING.md`, `docs/MEDIA_PROCESSING.md` |
| Text-to-speech | `docs/TTS_SYSTEM.md` |
| Text editing/translation | `docs/TEXT_PROCESSING.md` |
| Background jobs, SSE | `docs/JOB_SYSTEM.md` |
| Database schema | `docs/DATABASE.md` |
| API routes/contracts | `docs/API.md` |
| Frontend structure | `docs/FRONTEND.md`, `docs/RTL_UI_GUIDELINES.md` |
| Settings | `docs/SETTINGS.md` |
| Adding any new capability | `docs/EXTENDING_THE_APPLICATION.md` |

## Model routing for development work

This convention comes from the original project brief and is worth
preserving for whoever (human or agent) works on this next:

```
Complex problem (architecture, hard debugging, provider/job/DB design)
    -> Opus
Implementation (CRUD, styling, tests, refactor from an established plan)
    -> Sonnet
```

Don't reach for a weaker model on a problem that needs architectural
reasoning just because it is faster.

## Local development loop

```powershell
# Backend, with the real venv
cd backend
.venv\Scripts\python.exe -m app.main
# -> http://127.0.0.1:8420 (or the next free port; see logs/app.log)

# Frontend, separately, with HMR
cd frontend
npm run dev
# -> http://localhost:5173, proxies /api/* to the backend (vite.config.ts)
```

Running both separately during development is normal — the backend's own
static-file serving of `frontend/dist` is what production `start.bat` uses.

## Testing philosophy

**Nothing here is mocked that doesn't have to be.** The test suite runs
against a real temporary SQLite database, real FFmpeg (building actual test
video/audio with `-f lavfi`), and — where the Claude CLI is available — real
Claude calls. See `docs/TESTING.md` for the full breakdown and why: a test
that mocks FFmpeg proves the code calls FFmpeg with certain arguments, not that
those arguments produce a working video. Several real bugs (Opus sample rate,
the FFmpeg working-directory requirement for the `subtitles` filter, the
UTF-8 BOM requirement for PowerShell 5.1) were only found by actually running
the tool.

```powershell
cd backend
.venv\Scripts\python.exe -m pytest              # everything
.venv\Scripts\python.exe -m pytest -m "not slow"  # skip Claude-CLI-dependent tests
```

## Conventions this codebase follows

- **Errors carry two messages.** Every deliberate exception is an `AppError`
  subclass (`app/core/errors.py`) with a technical `message` (English, goes to
  the log) and a `user_message` (Persian, safe to show). Never let a raw
  exception or a `subprocess` repr reach the API response or the frontend.
- **No provider is ever named outside its own layer.** A job handler asks
  `AIService.run(task=..., model=...)`; it never imports `ClaudeProvider`. A
  hardcoded model id anywhere outside `app/ai/models.py` is a bug.
- **Settings defaults live in code, not the database.** `SettingsService.DEFAULTS`
  is the source of truth; the DB only stores overrides a user actually made.
  See `docs/SETTINGS.md`.
- **Migrations are forward-only.** No down-migrations; see `docs/DATABASE.md`
  for why that's the right trade-off here.
- **Original files are never modified.** Every media operation (audio
  extraction, subtitle rendering, TTS) reads its source and writes a new file.
  The integration tests assert on this explicitly (byte-size checks before and
  after).
- **The AI never overwrites user text.** A text-processing job always creates
  a *new* document pointing at its source; applying a result is a separate,
  explicit frontend action (`app/jobs/handlers/text_task.py`,
  `frontend/src/pages/project/TextEditPage.tsx`).

## Windows-specific gotchas worth knowing before you hit them

- **Reserved TCP port ranges.** Windows reserves blocks for Hyper-V/WinNAT
  (commonly 8xxx-9xxx ranges); binding inside one fails with WinError 10013,
  which looks like a permissions error and isn't. `app/main.py::find_free_port`
  probes and picks the next open port automatically; check
  `netsh interface ipv4 show excludedportrange protocol=tcp` if you need to
  understand why a specific port failed.
- **PowerShell 5.1 needs a UTF-8 BOM** in any `.ps1` file containing Persian
  text, or the parser misdecodes it via the system codepage and fails with a
  confusing "string is missing the terminator" error on an unrelated line.
  Verify with `Format-Hex path.ps1 -Count 3` and expect `EF BB BF`. See the
  note at the top of `start.ps1`.
- **`cmd.exe`'s Unicode handling in `.bat` files is unreliable even with a
  BOM.** `start.bat` originally had `echo <Persian text>` in its error branch;
  under direct double-click execution it worked, but under
  `cmd.exe /c start.bat` (used by the platform's own launch tests) the same
  line occasionally fragmented into several bogus "X is not recognized as an
  internal or external command" errors, one word at a time. The fix was not a
  better encoding - it was removing Persian text from `.bat` files entirely
  and relying on `start.ps1` (real PowerShell, reliable UTF-8 handling) for
  every user-facing message, including failure messages. Keep `.bat` files
  ASCII-only; they should do nothing but hand off to a `.ps1` script.
- **FFmpeg's `subtitles` filter and Windows paths don't mix.** A drive letter,
  backslashes and Persian characters inside an FFmpeg filtergraph are a
  reliable source of pain. The renderer sidesteps this by running FFmpeg with
  the subtitle script's directory as its working directory and referencing it
  by a bare filename — see `docs/VIDEO_RENDERING.md`.
- **Process-tree cancellation.** `Popen.kill()` only kills the direct child;
  the Claude CLI spawns a Node process tree. Cancellation uses
  `taskkill /F /T` — see `app/process/runner.py::kill_process_tree`.

## Keeping documentation current

When you change architecture or add a feature, update the relevant doc in the
same change. A stale doc is worse than no doc — it actively misleads the next
agent. If you're not sure a doc needs updating, it probably does if you
touched a file it names.
