# Extending the Application

This is the document a future AI coding agent (or a human returning to the
project after months away) should read before adding a capability. Every
recipe below names exact files and follows a pattern already proven in the
codebase — none of this is theoretical.

Read `docs/ARCHITECTURE.md` first if you haven't already; the recipes here
assume you understand the layer boundaries it explains.

---

## Adding a new AI provider

Full reasoning in `docs/AI_PROVIDERS.md`; this is the terse checklist. Claude
and OpenAI Codex (`app/ai/providers/claude/`, `app/ai/providers/codex/`) are
both real implementations of this exact recipe - read either as a concrete
template, especially the Codex one if the provider you're adding is also a
third-party CLI rather than a direct API.

1. `app/ai/providers/<name>/provider.py` — implement `AIProvider`
   (`app/ai/base.py`): `check_availability` (never raises, and stays fast -
   see `docs/AI_PROVIDERS.md`'s Codex section for a real ~40-second cost of
   getting this wrong by probing with a live call instead of a cheap status
   check), `generate` (streams via `on_output`, honours `cancel_token`, wraps
   errors as `AIError` subclasses).
2. `app/ai/registry.py::ProviderRegistry.build()` — add one line alongside
   the existing two.
3. `app/ai/models.py` — add the provider's `ModelSpec` entries (or let a user
   add them via `config/models.json`). If you cannot verify the provider's
   current model names against a real installed CLI, prefer a single
   "use the CLI's own default" sentinel entry (see Codex's `codex-default`)
   over a guessed list that might already be stale.
4. `app/services/settings.py::SettingsService.DEFAULTS` — add
   `ai.<name>_cli_path` (or equivalent) if the provider is CLI-driven, then
   thread it through `ServiceContainer.providers`
   (`app/container.py`) into `ProviderRegistry.build()`.
5. `frontend/src/pages/SettingsPage.tsx`'s `AiSection` —
   add the new provider to `PROVIDER_CLI_PATH_KEY` so its CLI path field and
   install hint appear alongside Claude's and Codex's.

Nothing else changes. `AIService`, every job handler, the recommendation
engine, and the frontend's provider/model selectors (including
`ModelSelector.tsx`, which reads the user's configured default provider
rather than a hardcoded one) already work against the interface. **Verify**
by hitting `GET /api/ai/providers` and confirming the new provider appears
with correct availability reporting.

---

## Adding a new AI task (e.g. Summarisation, SEO Analysis, Title Generation)

Full reasoning in `docs/AI_SYSTEM.md` and `docs/TEXT_PROCESSING.md`.

1. `app/domain/enums.py::AITaskType` — add the member.
2. `app/ai/tasks.py` — add a `TaskProfile` (Persian label/description, quality
   vs. speed weight for the recommendation engine, `expects_raw_text`, input
   character limit).
3. `app/ai/prompts/library.py::BUILTIN_PROMPTS` — add at least one built-in
   `PromptTemplate` for it.
4. `app/ai/models.py` — list the task under `good_for` on whichever models
   actually suit it.
5. Optional: `app/jobs/handlers/text_task.py::_RESULT_TYPE` — map it to a
   `DocumentType` other than the `EDITED` default, if appropriate.

**No new handler, no new endpoint, no frontend change required** —
`text_task.py` serves every text task generically, and the frontend's task
selector reads from `GET /api/ai/tasks`.

---

## Adding a new transcription engine

Full reasoning in `docs/AI_SYSTEM.md`'s "why transcription is separate"
section.

1. `app/transcription/providers/<name>.py` — implement `TranscriptionProvider`
   (`app/transcription/base.py`): `check_availability`, `transcribe` (return
   `TranscriptionResult` with real `TranscriptSegment`/`TranscriptWord`
   timings if the engine provides them — the subtitle timeline depends on
   these being genuine).
2. `app/transcription/registry.py::TranscriptionRegistry.build()` — register
   it.

Appears automatically in `GET /api/ai/transcription/engines` and the
transcription page's engine status banner.

---

## Adding a new TTS provider

Full reasoning in `docs/TTS_SYSTEM.md`.

1. `app/tts/providers/<name>.py` — implement `TTSProvider`
   (`app/tts/base.py`): `check_availability`, `list_voices` (rich
   `VoiceSpec` metadata — language, gender, age, styles, pitch/rate support),
   `synthesize` (**one continuous span of text only** — never handle pauses
   yourself, that's `app/tts/assembler.py`'s job).
2. `app/tts/registry.py::TTSRegistry.build()` — register it.

Appears automatically in `GET /api/ai/tts/providers` and
`GET /api/ai/tts/voices`; the speech page's voice selector renders whatever
the registry reports.

---

## Adding a new media processor / FFmpeg operation

`docs/MEDIA_PROCESSING.md` covers the shared plumbing this builds on.

1. Add a function to `app/media/` (a new module, or extend `audio.py`/`video.py`
   if it's closely related to an existing operation) that takes an already-
   resolved `FFmpegTools` and builds an argument list for `run_ffmpeg`
   (`app/media/ffmpeg/runner.py`) — never call `subprocess` directly, and never
   write output over the input path (always `unique_path` into a fresh file).
2. Wire progress/log callbacks through (`on_progress`, `on_log`,
   `cancel_token` parameters, matching the existing functions' signatures).
3. Create a job handler in `app/jobs/handlers/` calling it (see "Adding a job
   type" in `docs/JOB_SYSTEM.md`).
4. Add an API endpoint that submits the job.
5. Add a frontend page or extend an existing one, using `useJobRunner`.

---

## Adding a new page (frontend)

Full conventions in `docs/FRONTEND.md`.

1. `frontend/src/pages/<Name>Page.tsx` (or `pages/project/<Name>Page.tsx` for
   a project-scoped page).
2. Add the route in `frontend/src/App.tsx`.
3. Add a nav entry in `frontend/src/components/layout/navigation.ts`
   (`NAVIGATION` for top-level, `PROJECT_NAVIGATION` for project-scoped) —
   use a `lucide-react` icon component.
4. If the page starts a job: use `useJobRunner`
   (`frontend/src/hooks/useJobRunner.ts`) — don't build a new SSE
   subscription or polling loop.
5. If the page needs new backend data: add the typed call to
   `frontend/src/lib/api/resources.ts` and the type to `types.ts` first.

---

## Adding a new database entity

Full reasoning in `docs/DATABASE.md`.

1. `app/db/migrations/versions/000N_description.sql` — `CREATE TABLE`, with a
   `CHECK` constraint on any enum-valued column.
2. `app/domain/<entity>.py` — a plain Pydantic model, no DB/framework
   knowledge.
3. `app/db/repositories/<entity>.py` — the SQL, following the existing
   `create`/`get`/`list`/`update`/`delete` pattern; export it from
   `app/db/repositories/__init__.py`.
4. `app/container.py::ServiceContainer` — expose it as a property, the way
   every other repository is exposed.
5. If it's user-facing: request/response schemas
   (`app/api/schemas/`) and a router (`app/api/routers/`).

---

## Adding a subtitle export format

`docs/SUBTITLE_SYSTEM.md` has the full detail.

1. `app/media/subtitles/formats.py` — a `to_<format>` function following the
   `to_srt`/`to_vtt`/`to_ass` pattern; wire it into `write_subtitle_file`'s
   suffix dispatch.
2. `app/domain/enums.py::SubtitleFormat` — add the member.

The export endpoint and the frontend's format buttons pick it up
automatically once it's in the enum.

---

## Adding a new supported language

Requirement: the architecture must support adding languages beyond Persian
and English without a rewrite.

1. `app/domain/enums.py::Language` — add the member, and an entry in
   `LANGUAGE_METADATA` (English name, native name, RTL flag, ASR language
   code).
2. For transcription: confirm the ASR engine (faster-whisper/Whisper) supports
   the language code — most do, without further code changes.
3. For translation: optionally add a dedicated prompt template to
   `app/ai/prompts/library.py::translation_prompt` for quality; without one,
   `generic_translation_instruction` still produces a working (if slightly
   less tuned) translation for any language pair.
4. For TTS: add voice entries to whichever provider actually offers that
   language (`app/tts/providers/edge.py::_VOICES` is the most likely
   candidate — Edge's neural service covers dozens of languages already).
5. Frontend: add the language to whatever UI language pickers list it
   (currently hardcoded `fa`/`en` toggles in a few pages, e.g.
   `TranscribePage.tsx`, `SpeechPage.tsx` — these would need to switch to
   rendering from a language list rather than two fixed buttons if a third
   language is added; this is the one place true language-count scaling isn't
   fully automatic yet).

---

## Things that should never need to change for any of the above

If a change to any of the above recipes requires touching one of these, stop
and reconsider — it usually means a boundary was crossed that shouldn't have
been:

- `app/process/runner.py` — the subprocess execution boundary
- `app/core/security.py` — path/filename validation
- `app/jobs/queue.py` / `context.py` / `events.py` — the job system's
  mechanics (only `registry.py` and `handlers/` change per new job type)
- `app/db/connection.py` / `migrations/runner.py` — connection and migration
  mechanics (only `versions/*.sql` grows)
- `AIService`, `TranscriptionRegistry`, `TTSRegistry`'s public methods — new
  providers register with them, they don't change shape to accommodate one

If you find yourself editing one of these for what should be a routine
addition, the addition is probably not as routine as it looked — re-read the
relevant doc above before proceeding.
