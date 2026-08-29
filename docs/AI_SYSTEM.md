# AI System

## Purpose

Turns "run an AI task on some text" into a normalised call, regardless of
which provider ends up executing it. This is the layer that made adding a
second provider - OpenAI Codex, alongside Claude - a real, contained change
rather than a rewrite; see `docs/AI_PROVIDERS.md` for both implementations.

## Why transcription and TTS are NOT part of this layer

This is the single most important thing to understand before touching any of
the three provider layers. No LLM CLI accepts audio input and returns audio
output — the Claude CLI takes text on stdin, returns text. So:

- **Speech recognition** (audio → timed text) is `app/transcription/`, backed
  by a local Whisper model. It produces real, measured timestamps that no
  language model could invent — and the subtitle timeline depends on those
  timestamps being real.
- **Speech synthesis** (text → audio) is `app/tts/`, backed by neural and
  offline voice providers.
- **The AI layer** (`app/ai/`, this document) only ever takes text in and
  returns text out.

The two feed into each other: transcription's raw output becomes the AI
layer's input for `AITaskType.TRANSCRIPTION_REFINEMENT`
(`app/jobs/handlers/transcribe.py`). That handler runs the ASR engine first
(stage 1), then optionally calls `AIService.run()` for punctuation/spelling
cleanup (stage 2) — genuinely two different capabilities, not one blurred
together.

## Architecture

```
Job handler / API router
        │
        ▼
  AIService.run(task, prompt, content, model, ...)   <- app/ai/service.py
        │
        ├─ resolve_provider_id()          which provider (claude, future gpt)
        ├─ RecommendationEngine.resolve()  which model (explicit > preference > ranked)
        ├─ build_system_prompt()           task-specific instruction layering
        └─ provider.generate(request)      <- app/ai/base.py AIProvider interface
                    │
                    ▼
            ClaudeProvider              <- app/ai/providers/claude/provider.py
                    │
                    ▼
              ClaudeCLI.run()            <- app/ai/providers/claude/cli.py
                    │
                    ▼
           app/process/runner.py         <- the only subprocess boundary
```

Callers only ever touch `AIService`. Nothing outside `app/ai/providers/`
imports a concrete provider class.

## Key files

| File | Responsibility |
|---|---|
| `app/ai/base.py` | `AIProvider` abstract interface - the extension seam |
| `app/ai/registry.py` | `ProviderRegistry` - which providers exist, availability caching |
| `app/ai/models.py` | `ModelRegistry` - the *only* source of model identifiers |
| `app/ai/recommendation.py` | `RecommendationEngine` - which model for a task |
| `app/ai/tasks.py` | `TaskProfile` per `AITaskType` - quality/speed weights, system notes |
| `app/ai/prompts/library.py` | Built-in prompt templates, system prompt composition |
| `app/ai/prompts/renderer.py` | `{{variable}}` substitution for prompt templates |
| `app/ai/service.py` | `AIService` - the facade; also owns prompt assembly and output cleanup |

## Data flow: one call, in detail

1. A job handler calls
   `container.services.ai.run(task=AITaskType.TRANSLATION, prompt=..., content=..., model=...)`.
2. `AIService.resolve_provider_id` picks a provider: explicit request, else the
   configured default (`ai.provider` setting), else the first available one.
3. `AIService._guard_length` rejects input longer than the task's
   `max_input_chars` (from `TaskProfile`) with a Persian error telling the user
   to split it up, rather than sending a doomed request.
4. `RecommendationEngine.resolve` picks the model: an explicit `model` wins
   outright; otherwise it recommends one (see `docs/AI_MODELS.md`).
5. `build_system_prompt` (in `app/ai/prompts/library.py`) layers: raw-output
   discipline (for tasks whose result goes straight into a document),
   Persian orthography rules, the task's own notes, then caller-supplied rules.
6. `_compose` joins the instruction and the content with an explicit delimiter
   (`<<<TEXT_START>>>` / `<<<TEXT_END>>>`) so a transcript containing something
   that reads like an instruction can never be mistaken for one.
7. `provider.generate()` runs the call and returns a normalised `AIResponse`.
8. If the task's profile says `expects_raw_text`, `strip_conversational_framing`
   removes any leftover chat framing ("Here is the corrected text:") a
   chat-tuned model reached for despite the system prompt.

## Adding a provider

See `docs/EXTENDING_THE_APPLICATION.md` for the full recipe. In short:
implement `AIProvider` in `app/ai/providers/<name>/`, register it in
`ProviderRegistry.build()`, add its models to `ModelRegistry` (or a
`config/models.json` override). Nothing in `AIService`, the job handlers, or
the frontend needs to change — they all go through the interface.

## Adding a task

Add a member to `AITaskType` (`app/domain/enums.py`), a `TaskProfile` in
`app/ai/tasks.py` (quality/speed weights, system notes, input limits), and a
built-in prompt in `app/ai/prompts/library.py`. List it under `good_for` on
whichever models actually suit it in `app/ai/models.py`.

## Common mistakes

- **Hardcoding a model id anywhere outside `app/ai/models.py`.** Requirement:
  model identifiers must be configuration, not constants — a future rename of
  `sonnet` to something else should require editing one file.
- **Calling a provider directly from a job handler.** Always go through
  `AIService`; that's what keeps the recommendation engine and prompt system
  consistently applied.
- **Forgetting `expects_raw_text=False`** on an analysis-style task. Without
  it, `strip_conversational_framing` runs on output that was never meant to be
  raw document text and may mangle a legitimate analytical response.

## Testing

`backend/tests/unit/test_ai.py` covers the pure logic (scoring, resolution
order, prompt rendering, output cleanup) without a live CLI call.
`backend/tests/integration/test_jobs_pipeline.py::TestTextTaskJob` makes real
Claude CLI calls and is marked `@pytest.mark.slow`; it skips cleanly when the
CLI isn't available. See `docs/TESTING.md`.
