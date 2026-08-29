# AI Providers

## Purpose

Documents the `AIProvider` interface and the one provider that implements it
today, plus exactly what a second provider needs to do to slot in beside it
without touching the core. Read `docs/AI_SYSTEM.md` first for how this layer
fits into the whole platform.

## The interface

`app/ai/base.py::AIProvider` is an abstract class with:

```python
class AIProvider(ABC):
    id: str
    display_name: str

    @property
    def capabilities(self) -> list[ProviderCapability]: ...
    @property
    def supported_tasks(self) -> list[AITaskType]: ...

    def check_availability(self) -> ProviderInfo: ...   # must never raise
    def generate(self, request: AIRequest, *, on_output=None, cancel_token=None) -> AIResponse: ...
```

Contract rules, and why each exists:

- **`check_availability` must never raise.** A missing CLI, a network outage,
  an expired login — these are all normal states the UI renders (greyed-out
  option with a Persian reason), not exceptions that break the provider
  selector page.
- **`generate` must stream output through `on_output`.** The live CLI console
  (requirement 25) depends on this; a provider that buffers everything and
  returns at the end makes the console silent until the call finishes.
- **`generate` must honour `cancel_token` promptly.** The job system's cancel
  button (requirement: real cancellation) is only real if every provider
  checks it.
- **Provider-specific errors become `AIError` subclasses** (or a more specific
  one - `ClaudeCliNotFoundError`, `EmptyAIResponseError`) so the API layer's
  generic exception handler never has to know about provider internals.

## ClaudeProvider

`app/ai/providers/claude/provider.py`. The only provider registered in
version 1.

**Detection** (`app/ai/providers/claude/detect.py`): settings override →
`CLAUDE_CLI_PATH` env var → `PATH` → well-known Windows install locations
(`~/.local/bin/claude.exe`, npm global installs). Every candidate is verified
by actually running `--version`, because a stale `PATH` entry after an
uninstall is common.

**Execution** (`app/ai/providers/claude/cli.py`): see `docs/CLI_INTEGRATION.md`
for the full reasoning behind every flag. The short version: `--print
--output-format json --strict-mcp-config --no-session-persistence`, prompt on
stdin, executed from an empty scratch directory to avoid the CLI's own project
context inflating every call.

**Attachments are inlined, not passed as files.** `ClaudeProvider._render_attachment`
reads a text file and embeds it in the prompt between `--- FILE: name ---`
delimiters, rather than relying on the CLI's Read tool. In `--print` mode a
tool call needing permission has nowhere to prompt, so depending on tool use
for a headless pipeline is fragile. Every attachment this platform actually
sends (transcripts, drafts, subtitle text) is small enough to inline; binary
or oversized files are rejected with `FileValidationError` rather than
silently dropped.

**Model resolution in responses** (`_resolve_model_name` in `cli.py`): the
CLI's JSON envelope reports usage per-model in `modelUsage`, which can include
a background/haiku helper alongside the main model. The wrapper picks the
entry with the most output tokens as "the model that actually answered."

## Adding a second provider (e.g. GPT)

1. Create `app/ai/providers/gpt/` with a `GptProvider(AIProvider)`.
2. Implement `check_availability` (e.g. verify an API key is configured, or a
   CLI is installed - never raise on failure).
3. Implement `generate`: build the request in whatever shape that provider
   needs, run it (through `app/process/runner.py` if it's a CLI, or an HTTP
   client if it's a direct API), stream output through `on_output`, map errors
   to `AIError` subclasses.
4. Register it in `ProviderRegistry.build()` (`app/ai/registry.py`) - literally
   append one line:
   ```python
   GPTProvider(api_key=...),
   ```
5. Add its models to `ModelRegistry` — either as built-ins in `app/ai/models.py`
   (set `CLAUDE_PROVIDER_ID`-style constant for the new provider id) or via
   `config/models.json`, which merges over built-ins by id at load time.

Nothing else changes. `AIService`, every job handler, the recommendation
engine, and the frontend's provider/model selectors all already work against
the interface, not against `ClaudeProvider` by name. The frontend provider
selector (`frontend/src/pages/SettingsPage.tsx`, `AiSection`) renders whatever
`GET /api/ai/providers` reports — a second entry just appears.

## Common mistakes

- **Skipping the availability check pattern.** Don't let `generate()` be the
  first place a missing dependency is discovered — that turns into a raw
  exception mid-job instead of a clean "provider unavailable" state the UI can
  show before the user even starts.
- **Returning provider-native error types.** Always wrap in `AIError` (or a
  subclass) with a Persian `user_message`; see `app/core/errors.py`.
- **Assuming every provider supports every task.** Override `supported_tasks`
  if a provider genuinely can't do something (e.g. a provider with no
  analysis capability); `AIService.run` checks this before dispatching.
