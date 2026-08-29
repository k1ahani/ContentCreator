# Text Processing (Features 3 & 4: Editing and Translation)

## Purpose

How AI-powered text editing, translation, and custom-prompt processing work,
and — this is the part that matters most — how the platform guarantees the
AI never silently overwrites what the user wrote. Read `docs/AI_SYSTEM.md`
first for how a task actually gets executed.

## The core guarantee

Requirement: "The AI must never silently overwrite the original." This is not
a UI convention layered on top of a system that could overwrite — it's
structural, at the data model level:

- Every AI text operation runs through `app/jobs/handlers/text_task.py`
  (`JobType.TEXT_TASK`), which **always creates a new `TextDocument` row**
  (`app/db/repositories/documents.py::DocumentRepository.create`) pointing at
  its source via `source_document_id`. There is no update path from an AI job
  to an existing document's `content` field.
- Document versioning follows the source chain: a document created from a
  source continues that source's version number
  (`DocumentRepository.create` looks up the source's version and increments
  it), so "نسخه ۳" in the UI reflects a real lineage, not an arbitrary counter.
- The frontend's text editor (`frontend/src/pages/project/TextEditPage.tsx`)
  keeps the editable original and the AI result in **separate React state**
  (`content` vs `result`). "Apply" copies `result` into `content` locally —
  it does not touch the source document either. Nothing is persisted back to
  the original until the user explicitly saves or generates a new document
  from the (now-edited) `content`.
- A caller can request `save: false` (used by the editor's "preview before
  committing" flow) to get the AI's result back without creating a document
  row at all — useful for a quick look that the user might reject outright.

## One handler, several tasks

`text_task.py` serves editing, translation, analysis, summarisation and
custom-prompt tasks through a single handler, because they differ only in
task type and prompt — exactly what `TaskProfile` and the prompt library exist
to express (`docs/AI_SYSTEM.md`). Adding "generate a title" or "SEO analysis"
later needs no new handler, just a new `AITaskType` and prompt.

## Instruction resolution

`_build_instruction` in `text_task.py`, in priority order:

1. **A custom prompt the user typed**, optionally rendered through
   `app/ai/prompts/renderer.py::render_template` if `variables` were supplied.
2. **A dedicated built-in translation template** for the exact language pair
   (`app/ai/prompts/library.py::translation_prompt` — currently fa→en and
   en→fa).
3. **A generic translation instruction** naming both languages, for any pair
   without a dedicated template — this is what makes adding a language cheap:
   no template is *required*, just recommended for quality.
4. **The first built-in prompt for the task** (`list_builtins(task)[0]`),
   e.g. `edit_proofread` for `text_editing`.

Same-language translation (source == target) is rejected before any AI call,
with a Persian message telling the user to pick a different target — not a
wasted API call that would just echo the input back.

## Custom prompts (requirement 16)

`app/ai/prompts/renderer.py` and `app/db/repositories/prompts.py`. Version 1
ships:

- **Built-in templates** (`app/ai/prompts/library.py::BUILTIN_PROMPTS`),
  read-only, defined in code.
- **User-saved prompts**, stored in the `prompts` table with the same shape
  (`name`, `task`, `category`, `body`, `variables`) so the UI can list both
  together (`GET /api/ai/prompts`).

The `variables` and `category` columns already exist specifically so that
saved-prompt categories, a prompt history, and reusable variable-driven
templates can be added later **without a migration** — the schema was
designed ahead of the UI that will eventually expose them (see requirement
16's explicit ask for this forward-compatibility).

## Output cleanup

Raw-text tasks (`TaskProfile.expects_raw_text`) get their result passed
through `app/ai/service.py::strip_conversational_framing` — see
`docs/AI_SYSTEM.md` for what it does and why it exists. Analysis-style tasks
(`expects_raw_text=False`, e.g. `text_analysis`) skip this, since their output
is meant to be prose commentary, not a drop-in document replacement.

## Adding a new text task

1. Add a member to `AITaskType` (`app/domain/enums.py`).
2. Add a `TaskProfile` to `app/ai/tasks.py` (quality/speed weights,
   `expects_raw_text`, input limits).
3. Add a built-in prompt to `BUILTIN_PROMPTS` in `app/ai/prompts/library.py`.
4. Optionally map it to a `DocumentType` in `text_task.py::_RESULT_TYPE` if it
   should save as something other than `DocumentType.EDITED`.

No changes needed to the handler itself, the job system, or the frontend's
task selector — they all read from the enum and the task-info endpoint
(`GET /api/ai/tasks`).

## Common mistakes

- **Writing an AI result directly to `document.content`.** There is no
  legitimate reason to do this — always create a new document via
  `DocumentRepository.create` with `source_document_id` set.
- **Bypassing `AIService.run`** to call a provider directly from a handler —
  this loses model resolution, prompt composition, and output cleanup all at
  once. See `docs/AI_SYSTEM.md`.

## Testing

`backend/tests/integration/test_jobs_pipeline.py::TestTextTaskJob` (marked
`@pytest.mark.slow`, real Claude calls) confirms `save: false` produces no
document and `save: true` produces one with real content. Prompt rendering
and instruction-resolution logic are covered without a live call in
`backend/tests/unit/test_ai.py::TestPromptTemplates` and
`TestTemplateRendering`.
