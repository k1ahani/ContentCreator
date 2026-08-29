# Project Structure

Full directory layout with what lives where and why. Read `docs/ARCHITECTURE.md`
first for the reasoning behind the layer boundaries this structure encodes.

```
ContentCreatorApp/
│
├── backend/
│   ├── app/
│   │   ├── main.py                FastAPI app factory, lifespan, entry point
│   │   ├── container.py           composition root (ServiceContainer)
│   │   │
│   │   ├── core/                  framework-free foundations
│   │   │   ├── paths.py            AppPaths - single source of truth for filesystem layout
│   │   │   ├── config.py           bootstrap config (env vars, config/app.json)
│   │   │   ├── errors.py           AppError hierarchy - every user-facing Persian message
│   │   │   ├── security.py         path traversal / filename / import validation
│   │   │   ├── logging.py          UTF-8-safe logging setup
│   │   │   ├── ids.py               sortable id generation
│   │   │   └── timecode.py         seconds <-> SRT/VTT/ASS/clock formatting
│   │   │
│   │   ├── domain/                 Pydantic models, no framework/DB/filesystem code
│   │   │   ├── enums.py            every enum in the platform, Language metadata
│   │   │   ├── project.py, asset.py, document.py, job.py
│   │   │   ├── subtitle.py         SubtitleTrack/Cue/Style
│   │   │   ├── transcription.py    TranscriptSegment/Word, TranscriptionResult
│   │   │   ├── tts.py               SpeechScript, TextSegment/PauseSegment, VoiceSpec
│   │   │   └── ai.py                 AIRequest/AIResponse, ModelSpec, ProviderInfo
│   │   │
│   │   ├── process/                 the ONLY place subprocess.Popen is called
│   │   │   └── runner.py            argument-list execution, streaming, cancellation, timeout
│   │   │
│   │   ├── ai/                      text-generation provider layer (see docs/AI_SYSTEM.md)
│   │   │   ├── base.py               AIProvider interface
│   │   │   ├── registry.py           ProviderRegistry (which providers exist)
│   │   │   ├── models.py             ModelRegistry (the only source of model ids)
│   │   │   ├── recommendation.py     RecommendationEngine (which model for a task)
│   │   │   ├── tasks.py              TaskProfile per AITaskType
│   │   │   ├── service.py            AIService - the facade everything else calls
│   │   │   ├── prompts/              prompt templates + rendering
│   │   │   └── providers/claude/     Claude CLI detection, wrapper, provider impl
│   │   │
│   │   ├── transcription/           speech-recognition provider layer
│   │   │   ├── base.py               TranscriptionProvider interface
│   │   │   ├── registry.py
│   │   │   └── providers/faster_whisper_provider.py
│   │   │
│   │   ├── tts/                      text-to-speech provider layer
│   │   │   ├── base.py               TTSProvider interface
│   │   │   ├── registry.py
│   │   │   ├── assembler.py          text + pauses -> one audio file
│   │   │   └── providers/edge.py, sapi5.py
│   │   │
│   │   ├── media/                    FFmpeg integration
│   │   │   ├── ffmpeg/                locator.py, runner.py (progress), probe.py
│   │   │   ├── audio.py               Feature 1: video -> speech-optimised audio
│   │   │   ├── video.py               Feature 5: subtitle burn-in rendering
│   │   │   └── subtitles/             formats.py (SRT/VTT/ASS), style.py, segmentation.py
│   │   │
│   │   ├── jobs/                     background job system (see docs/JOB_SYSTEM.md)
│   │   │   ├── queue.py               worker pool, job lifecycle
│   │   │   ├── context.py             JobContext - what a handler receives
│   │   │   ├── events.py              thread-safe event bus feeding SSE
│   │   │   ├── registry.py            JobType -> handler mapping, startup verification
│   │   │   └── handlers/              one module per JobType
│   │   │
│   │   ├── db/                        SQLite persistence (see docs/DATABASE.md)
│   │   │   ├── connection.py          Database - thread-local connections, WAL
│   │   │   ├── migrations/            forward-only .sql files + runner
│   │   │   └── repositories/          one repository per aggregate, all raw SQL lives here
│   │   │
│   │   ├── services/
│   │   │   └── settings.py            SettingsService - defaults in code, overrides in DB
│   │   │
│   │   └── api/                       HTTP layer (see docs/API.md)
│   │       ├── deps.py                 FastAPI dependencies (container, project lookup)
│   │       ├── errors.py               exception -> Persian JSON error mapping
│   │       ├── schemas/                request/response Pydantic models
│   │       └── routers/                projects, jobs, subtitles, ai, system
│   │
│   ├── tests/
│   │   ├── unit/                      no external processes, or a real one that's fast
│   │   └── integration/               real FFmpeg, real database, real (optional) Claude CLI
│   │
│   ├── pyproject.toml, requirements*.txt
│   └── .venv/                          created by scripts/setup.ps1, gitignored
│
├── frontend/
│   └── src/                            see docs/FRONTEND.md for the full breakdown
│       ├── lib/api/                    typed HTTP client, resource calls, SSE event bus
│       ├── hooks/                      useJobRunner, useJobWatcher, useProject
│       ├── components/                 ui/, layout/, ai/, media/, subtitle/, tts/, console/
│       ├── pages/                      one file per route, project/ for project-scoped pages
│       └── store/                      zustand - theme + mobile drawer only
│
├── bin/
│   └── ffmpeg/                          bundled FFmpeg, downloaded by scripts/setup.ps1
│
├── storage/                             gitignored - all runtime data
│   ├── app.db                           the SQLite database
│   ├── models/                          downloaded Whisper model weights
│   └── projects/<project-id>/           source/ audio/ transcript/ subtitles/ voice/ rendered/ temp/
│
├── config/                              gitignored - local machine overrides
│   ├── app.json                         bootstrap config overrides (see app/core/config.py)
│   └── models.json                      model registry overrides (see app/ai/models.py)
│
├── logs/                                gitignored - app.log, rotated
│
├── docs/                                this directory
├── scripts/                             setup.ps1, install_asr.ps1
├── start.bat, start.ps1
└── README.md
```

## Naming conventions

- **Python**: `snake_case` for modules/functions, `PascalCase` for classes,
  `UPPER_CASE` for module-level constants. Domain enums are `PascalCase` with
  lowercase-string values (`AssetType.VIDEO.value == "video"`).
- **TypeScript**: `camelCase` for functions/variables, `PascalCase` for
  components and types, files match their default export's name
  (`Button.tsx` exports `Button`).
- **API routes**: `/api/<resource>` for collections,
  `/api/projects/{id}/<resource>` for project-scoped ones,
  `/api/projects/{id}/<verb>` for actions that start a job (`/audio/extract`,
  `/subtitles/render`).
- **Job types**: the `JobType` enum value doubles as the handler module name
  under `app/jobs/handlers/` (`JobType.AUDIO_EXTRACT` → `audio_extract.py`).

## Where a new file goes

| Adding... | Goes in... |
|---|---|
| A new AI provider | `app/ai/providers/<name>/`, register in `app/ai/registry.py` |
| A new AI task | `AITaskType` enum, `app/ai/tasks.py`, built-in prompt in `app/ai/prompts/library.py` |
| A new transcription engine | `app/transcription/providers/`, register in `app/transcription/registry.py` |
| A new TTS provider | `app/tts/providers/`, register in `app/tts/registry.py` |
| A new job type | `JobType` enum, handler in `app/jobs/handlers/`, import in `app/jobs/registry.py:load_handlers` |
| A new database entity | migration in `app/db/migrations/versions/`, repository in `app/db/repositories/`, domain model in `app/domain/` |
| A new API endpoint | the relevant router in `app/api/routers/`, schema in `app/api/schemas/` if needed |
| A new frontend page | `frontend/src/pages/`, route in `frontend/src/App.tsx`, nav entry in `frontend/src/components/layout/navigation.ts` |

Full recipes with code are in `docs/EXTENDING_THE_APPLICATION.md`.
