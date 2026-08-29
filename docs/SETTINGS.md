# Settings

## Purpose

How user-configurable settings are defined, validated, persisted, and applied
live. Distinct from bootstrap configuration — see the boundary explained
below, since conflating the two is the most common mistake in this area.

## Settings vs. bootstrap config — a real boundary, not a style choice

| | Bootstrap config | User settings |
|---|---|---|
| Lives in | `app/core/config.py::AppConfig` | `app/services/settings.py::SettingsService` |
| Source | env vars, `config/app.json` | SQLite `settings` table, defaults in code |
| Editable from | not from the running app | Settings page, takes effect immediately |
| Examples | host, port, log level, worker count | FFmpeg path, default model, subtitle style |
| Changing it requires | a restart | nothing — `ServiceContainer.invalidate()` |

If a value should be changeable from the UI, it's a user setting. If it's
needed before the app can even talk to its own database, it's bootstrap
config. Do not add a UI-editable field to `AppConfig`, and do not add a
process-level knob (like the SSE keep-alive interval) to `SettingsService`.

## Defaults live in code, not the database

`SettingsService.DEFAULTS` (`app/services/settings.py`) is the single source
of truth for every setting's default value. The database only ever stores an
**override** a user actually made (`repo.get(key, fallback=DEFAULTS[key])`).
This is deliberate and has a real consequence: a fresh install and an
upgraded install behave identically for anything the user hasn't touched, and
adding a new setting is a one-line change with **no migration** — the schema
(`app/db/migrations/versions/0001_initial.sql`'s `settings` table) is just
`key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP`, generic enough to
never need altering.

## Sections

Keys are dotted, `<section>.<name>`, matching exactly what the frontend's
Settings page renders as tabs (`frontend/src/pages/SettingsPage.tsx`,
`SECTION_TABS`):

| Section | Covers |
|---|---|
| `general` | workspace directory, import size limit, allowed import roots, theme |
| `ai` | provider, Claude CLI path, default model, per-task model preferences, timeout |
| `transcription` | engine, model size, language, VAD filter, auto-refine |
| `media` | FFmpeg path, default audio preset, default render quality |
| `subtitle` | style (font/color/position/etc.), segmentation limits, export format |
| `voice` | provider, language, default voice, style, rate, pitch, output format |

Adding a setting to an existing section needs no frontend change beyond a new
field in that section's form — the tab structure and the save mechanism are
already generic (`GET /api/settings` returns `grouped` pre-organised by
section; `PUT /api/settings` validates and persists whatever keys are sent).

## Validation

`SettingsService._validate` (`app/services/settings.py`) runs on every
write, in two passes:

1. **Type check against the default's shape** — a setting whose default is a
   `float` rejects a string, a `bool` default rejects anything but a real
   boolean (Python's `bool` is a subtype of `int`, so this is checked
   explicitly to avoid `True` silently passing as a valid "number").
2. **Semantic validation for specific keys** — a path setting
   (`_PATH_KEYS`) must exist on disk; `ai.model_by_task` keys must be real
   `AITaskType` values; `subtitle.style` round-trips through the
   `SubtitleStyle` Pydantic model so an invalid colour is rejected at save
   time, not at render time; `general.allowed_import_roots` entries must be
   real directories.

A validation failure raises `ValidationError` (422, Persian message naming the
specific field) — the API never accepts a value that would only fail later,
inside a job, in a way that's much harder for the user to trace back to a
setting they changed.

## Live effect: invalidation

`ServiceContainer.invalidate(keys=[...])` (`app/container.py`), called from
the settings PUT/reset endpoints, drops cached objects that depend on the
changed keys:

- any `ai.*` key rebuilds the AI facade, provider registry and model registry
  (so a new Claude CLI path or timeout takes effect on the very next AI call);
- any `media.*` key clears the FFmpeg locator cache;
- `transcription.*` / `voice.*` invalidate the corresponding provider
  registry's availability cache.

This is intentionally generous — these objects are cheap to rebuild, and
being stingy about invalidation produces the much more confusing bug of a UI
showing a saved path that nothing is actually using yet.

## Typed accessors

`SettingsService` exposes a few typed convenience properties beyond the raw
`get`/`set` dict interface — `subtitle_style` (returns a real `SubtitleStyle`
model), `model_preferences`, `claude_cli_path`, `ffmpeg_path`,
`max_import_bytes`, `allowed_import_roots`. Prefer these over calling
`.get("subtitle.style")` and constructing the model yourself at every call
site.

## Adding a setting

1. Add a `"section.name": default_value` entry to
   `SettingsService.DEFAULTS`. No migration needed.
2. If it needs validation beyond a type check, add a branch in `_validate`.
3. Reference it via `settings.get("section.name")` wherever it's consumed.
4. Add the corresponding field to the relevant section component in
   `frontend/src/pages/SettingsPage.tsx`.

## Common mistakes

- **Hardcoding a default somewhere else** ("if not set, use 'opus'" inline in
  a job handler) instead of relying on `SettingsService.get`'s fallback to
  `DEFAULTS`. There should be exactly one place a default value is written.
- **Adding a UI-editable value to `AppConfig`** instead of `SettingsService`
  — see the boundary table above.
- **Forgetting to call `invalidate()`** after a change that affects a cached
  registry — if a new setting affects the AI, media, transcription or voice
  layers, make sure `invalidate`'s key-prefix matching covers it.
