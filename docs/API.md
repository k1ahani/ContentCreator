# API

## Purpose

The HTTP contract between frontend and backend. Full interactive docs are
always available at `GET /api/docs` (Swagger UI, generated from the FastAPI
routers — the source of truth for exact request/response shapes). This
document is the map: what exists, how it's organised, and the conventions
every endpoint follows.

## Conventions

- **No authentication anywhere.** Single-user local tool; see
  `docs/ARCHITECTURE.md`'s security section for what *is* enforced instead.
- **Errors are uniform**: `{"error": {"code": "...", "message": "...(Persian)",
  "hint": "...", "details": {...}}}`. See `app/api/errors.py` and
  `app/core/errors.py`. Never a raw stack trace or exception name.
- **Long operations return `202 Accepted`** with a `{"job": {...}, "message":
  "..."}` body immediately; the frontend follows progress over
  `GET /api/events` (SSE). See `docs/JOB_SYSTEM.md`.
- **List endpoints** return `{"items": [...], "total": N}`
  (`ListResponse[T]`), never a bare array — leaves room for pagination
  metadata later without a breaking shape change.
- **Project-scoped resources** are always addressed through their project:
  `/api/projects/{project_id}/<resource>`, never a bare `/api/assets/{id}`.
  This keeps workspace paths derivable from the URL structure.

## Router map

| Router | Prefix | Covers |
|---|---|---|
| `app/api/routers/projects.py` | `/api/projects` | projects, assets (import/upload/delete), documents |
| `app/api/routers/jobs.py` | `/api` | job submission (one endpoint per feature action), job inspection, cancellation, `/api/events` (SSE) |
| `app/api/routers/subtitles.py` | `/api/projects/{id}/subtitles` | tracks, cues (CRUD + split/merge), preview, export |
| `app/api/routers/ai.py` | `/api/ai` | provider/model discovery, recommendations, prompts, transcription engines, TTS voices |
| `app/api/routers/system.py` | `/api` | dependency status, settings, file serving, filesystem browsing |

## Endpoints by feature

**Projects & workspace**
```
GET    /api/projects                          list (filter: status, search)
POST   /api/projects                           create
GET    /api/projects/{id}                      get
PATCH  /api/projects/{id}                       update
DELETE /api/projects/{id}                       delete (?delete_files=true to also remove workspace)

GET    /api/projects/{id}/assets                list (filter: type)
POST   /api/projects/{id}/assets/import         register a file from a local path (validated, not uploaded)
POST   /api/projects/{id}/assets/upload         multipart upload fallback
DELETE /api/projects/{id}/assets/{asset_id}     delete (optionally the file too)

GET    /api/projects/{id}/documents             list (filter: type)
POST   /api/projects/{id}/documents             create
GET    /api/projects/{id}/documents/{doc_id}    get
PATCH  /api/projects/{id}/documents/{doc_id}    update
DELETE /api/projects/{id}/documents/{doc_id}    delete
```

**Feature actions (all return 202 + job)**
```
POST /api/projects/{id}/audio/extract           Feature 1
POST /api/projects/{id}/transcribe               Feature 2
POST /api/projects/{id}/text/process              Features 3 & 4
POST /api/projects/{id}/subtitles/generate         Feature 5 (build cues)
POST /api/projects/{id}/subtitles/sync             Feature 5 (re-time from audio)
POST /api/projects/{id}/subtitles/render           Feature 5 (burn in)
POST /api/projects/{id}/speech/synthesize           Feature 6
```

Note the one deliberate asymmetry: subtitle synchronisation has **two**
endpoints, and only the automatic one is a job. `.../subtitles/sync` runs
speech recognition and therefore takes minutes; `.../subtitles/{track}/retime`
below is pure arithmetic over rows and answers inline. Making the second one a
job too would be consistency for its own sake — a progress bar for something
already finished. See `docs/SUBTITLE_SYSTEM.md`.

**Jobs**
```
GET    /api/jobs                                list (filter: project_id, status, type)
GET    /api/jobs/active                          currently queued/running
GET    /api/jobs/{job_id}                        get
GET    /api/jobs/{job_id}/logs                   persisted console lines
DELETE /api/jobs/{job_id}                        cancel
GET    /api/events                               SSE stream, all job events
```

**Subtitles**
```
GET/POST                     /api/projects/{id}/subtitles
GET/PATCH/DELETE             /api/projects/{id}/subtitles/{track_id}
GET/POST                     /api/projects/{id}/subtitles/{track_id}/cues
PATCH/DELETE                 /api/projects/{id}/subtitles/{track_id}/cues/{cue_id}
POST .../cues/{cue_id}/split  split at a timeline position
POST .../cues/{cue_id}/merge  merge with the following cue
POST .../retime               batch re-time every cue (shift/scale/reading_speed/stretch)
GET  .../preview?format=srt|vtt|ass
POST .../export               write + register as an asset
```

`retime` returns `{items, total, report}` rather than a bare `ListResponse`:
the report (cues changed, overlaps fixed, cues clamped, largest shift) is what
lets the UI say what actually happened instead of "done".

**AI discovery** (see `docs/AI_SYSTEM.md`, `docs/AI_MODELS.md`)
```
GET /api/ai/providers                 text providers + availability
GET /api/ai/models?provider=&task=    model registry
GET /api/ai/recommend?task=&provider= recommended model + Persian reason
GET /api/ai/tasks                     AITaskType list with Persian labels
GET /api/ai/prompts?task=              built-in + saved prompt templates
GET /api/ai/transcription/engines      ASR engine status + model sizes
GET /api/ai/tts/providers              TTS provider status (availability, pricing, key needed)
GET /api/ai/tts/voices?provider=&language=
GET /api/ai/tts/voices/{voice_id}/preview?text=   short spoken sample (audio/mpeg)
```

The preview route declares `voice_id` as a `:path` parameter because the
API-backed providers compose ids containing a colon; it returns audio bytes, not
JSON, and is cached on disk per voice and sample text.

**System & settings**
```
GET /api/system/status         dependency doctor (FFmpeg, Claude CLI, ASR, TTS)
GET /api/system/media           audio presets, render qualities
GET /api/system/browse?path=    read-only filesystem listing (file picker backend)
GET /api/files/{asset_id}       stream a media asset (range-request aware)
GET /api/files/{asset_id}/download

GET  /api/settings              current values + grouped-by-section + defaults
PUT  /api/settings              update (validated server-side per key)
POST /api/settings/reset        reset one key or everything
```

## Adding an endpoint

1. Add or extend a request schema in `app/api/schemas/requests.py` if the
   endpoint takes a body — never accept a raw domain model directly (a client
   should not be able to set an id, timestamp, or derived counter).
2. Add the route to the relevant router in `app/api/routers/`. Keep it thin:
   validate, call a service or submit a job, return. Business logic belongs in
   `app/services/`, `app/jobs/`, or a provider layer — not in the router.
3. If it's a long operation, submit a job instead of doing the work inline —
   see `docs/JOB_SYSTEM.md`.
4. Register the router in `app/main.py::create_app` if it's a new router file.
5. Add the corresponding typed call in `frontend/src/lib/api/resources.ts` and
   the type in `frontend/src/lib/api/types.ts`.

## Common mistakes

- **Returning a raw Python exception's message.** Always raise an `AppError`
  subclass; the global handler in `app/api/errors.py` is what guarantees the
  Persian-message contract, and it only applies to exceptions it recognises.
- **Doing FFmpeg/Claude CLI work directly in a router.** That blocks the
  request thread for the operation's full duration; use the job system.
- **A list endpoint returning a bare array.** Always wrap in
  `ListResponse[T]`.

## Testing

`backend/tests/integration/test_api.py` exercises the full HTTP surface with
FastAPI's `TestClient` against a real container (real database, real FFmpeg
where relevant) — including the exact error shapes (`404` with
`error.code == "not_found"`, `422` for a validation failure) the frontend
relies on.
