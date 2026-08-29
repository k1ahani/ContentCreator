# AI Models

## Purpose

`app/ai/models.py` is the **only** source of model identifiers in the
platform. No other file — backend or frontend — may hardcode a model id.
This document explains the registry, the recommendation engine that reads it,
and how to change what's recommended without touching code.

## Why aliases, not pinned versions

Built-in models use the Claude CLI's own aliases (`sonnet`, `opus`, `haiku`,
`fable`) rather than dated version strings like `claude-sonnet-5`. Aliases
keep resolving to the current release automatically, so the platform doesn't
silently go stale as new versions ship — directly addressing the requirement
"do not assume today's model names will remain unchanged forever." A user who
wants a pinned version can still type one into `config/models.json`.

## The registry

`app/ai/models.py::ModelRegistry` holds `ModelSpec` entries:

```python
class ModelSpec(BaseModel):
    id: str
    provider: str
    display_name: str
    tier: ModelTier              # fast | balanced | powerful
    good_for: list[AITaskType]   # tasks this model is endorsed for, best first
    rationale_fa: str            # Persian sentence explaining the strength
    speed: int                   # 1-5
    quality: int                 # 1-5
    available: bool = True
```

Loaded via `ModelRegistry.load()`: built-ins from `_BUILTIN_MODELS`, merged
with `config/models.json` if present (create the file only if you want to
override something — it does not exist by default).

### Overriding without touching code

```json
{
  "models": [
    { "id": "sonnet", "quality": 5 },
    { "id": "fable", "good_for": ["text_editing"], "available": true }
  ]
}
```

Entries merge onto the matching built-in by `id`; an unknown `id` is added as
a new model. Set `"available": false` to hide a model without deleting the
job/document history that references it (a hidden model still resolves by id
if something already used it — it just won't appear in fresh recommendations).

## The recommendation engine

`app/ai/recommendation.py::RecommendationEngine`. Given a task, it:

1. **Checks the user's saved preference** (`ai.model_by_task` setting) for that
   task. If set and the model is available for the provider, it wins outright
   and the response reports `from_user_preference=True`.
2. **Otherwise scores every model** for the task:
   ```
   score = quality_weight * (quality/5) + speed_weight * (speed/5)
           + 1.0 if task in model.good_for else 0.0
           + 0.15 if model.tier == task.preferred_tier else 0.0
   ```
   Weights come from the task's `TaskProfile` (`app/ai/tasks.py`) — translation
   weighs quality 0.85/speed 0.15, subtitle segmentation weighs quality
   0.45/speed 0.55. An explicit endorsement (`good_for`) is a decisive bonus:
   an endorsed model always outranks a stronger unendorsed one.
3. **Returns the top-scored model** plus every alternative, ranked, for the
   UI's manual override list, plus a Persian `reason_fa` explaining the pick.

This is what powers the "مدل پیشنهادی" (recommended model) panel: `GET
/api/ai/recommend?task=...` returns exactly this, and
`frontend/src/components/ai/ModelSelector.tsx` renders it with the override
list always available.

## Resolution at execution time

`RecommendationEngine.resolve(task, provider, requested_model, user_preferences)`
is what job handlers actually call:

- an explicit `requested_model` (the user picked one in the UI) wins,
  validated against the registry and the provider;
- otherwise falls back to `recommend()`.

This is the one function that decides what model actually runs — see
`app/ai/service.py::AIService.run`.

## Built-in models (v1)

| id | tier | endorsed for | notes |
|---|---|---|---|
| `sonnet` | balanced | editing, refinement, translation, summarisation, general | the default workhorse |
| `opus` | powerful | translation, analysis, editing | most accurate, slowest |
| `haiku` | fast | subtitle segmentation, general | cheapest, fastest |
| `fable` | balanced | (none) | available to pick manually; not claimed for any task by default |

`fable` deliberately has an empty `good_for` — the registry doesn't assert a
strength for it that hasn't been evaluated for these specific workloads. This
is a real editorial choice: don't claim a model is good at something just to
fill in a table.

## Codex's single sentinel entry, and why it looks different from Claude's

| id | provider | tier | endorsed for | notes |
|---|---|---|---|---|
| `codex-default` | codex | balanced | (none) | maps to *no* `-m` flag - the CLI's own current default |

Claude gets four named entries; Codex gets one, and that asymmetry is
deliberate rather than incomplete. While building this integration, running
`codex exec` with no `-m` flag reported its own current default model as
`gpt-5.6-sol` - a name that does not match any commonly assumed OpenAI
product naming at the time. That is direct evidence that Codex's model naming
moves faster than a hardcoded list in this codebase could responsibly claim
to track, especially without valid credentials available to verify a
candidate list against the real CLI.

So `codex-default` is not a placeholder to be filled in later with "real"
model names - it is the considered choice: `app/ai/providers/codex/cli.py`
never passes `-m` for this id (see `DEFAULT_MODEL_SENTINEL` in
`provider.py`), so the CLI always resolves whatever its *own* current default
is. This can never go stale the way a pinned snapshot name would, at the cost
of the platform not being able to explain *which* model will run ahead of
time.

An operator who wants a specific Codex model pinned - once they know their
own account's available model names, which this codebase cannot know for
them - adds it the normal way, through `config/models.json`:

```json
{
  "models": [
    { "id": "gpt-5.1-codex", "provider": "codex", "display_name": "GPT-5.1 Codex",
      "good_for": ["text_editing"], "rationale_fa": "...", "speed": 3, "quality": 5 }
  ]
}
```

That entry's `id` becomes a real `-m gpt-5.1-codex` argument the next time it
is selected - `CodexCLI.build_argv` passes through any model id that is not
exactly `codex-default` literally.

## Adding a model

Add a `ModelSpec` to `_BUILTIN_MODELS` in `app/ai/models.py` (or drop an entry
into `config/models.json` for a local-only change — no restart needed once
Settings triggers `ServiceContainer.invalidate`). Write `rationale_fa` as a
real Persian sentence explaining the trade-off, not a placeholder — it's shown
directly to the user.

## Common mistakes

- **A model id anywhere else in the codebase.** Grep for suspicious string
  literals like `"sonnet"` or `"claude-"` outside `app/ai/models.py` and
  `config/` before merging a change — that's a hardcoding regression.
- **Skipping the frontend.** The model selector, provider dropdowns and
  Settings AI section all read from `GET /api/ai/models` /
  `GET /api/ai/recommend` — never add a `<select>` with model names typed into
  JSX.
