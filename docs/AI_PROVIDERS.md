# AI Providers

## Purpose

Documents the `AIProvider` interface and the two providers that implement it
- Claude and OpenAI Codex - plus exactly what a *third* provider needs to do to
slot in beside them without touching the core. Read `docs/AI_SYSTEM.md` first
for how this layer fits into the whole platform.

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

- **`check_availability` must never raise, and must be fast.** A missing CLI,
  a network outage, an expired login — these are all normal states the UI
  renders (greyed-out option with a Persian reason), not exceptions that break
  the provider selector page. "Fast" turned out to matter concretely: see the
  Codex section below for a real ~35-40 second cost that skipping this rule
  would impose on every page load.
- **`generate` must stream output through `on_output`.** The live CLI console
  (requirement 25) depends on this; a provider that buffers everything and
  returns at the end makes the console silent until the call finishes.
- **`generate` must honour `cancel_token` promptly.** The job system's cancel
  button (requirement: real cancellation) is only real if every provider
  checks it.
- **Provider-specific errors become `AIError` subclasses** (or a more specific
  one - `ClaudeCliNotFoundError`, `CodexNotFoundError`, `EmptyAIResponseError`)
  so the API layer's generic exception handler never has to know about
  provider internals.

## ClaudeProvider

`app/ai/providers/claude/provider.py`.

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

## CodexProvider

`app/ai/providers/codex/provider.py`. Drives OpenAI's official Codex CLI
(`npm install -g @openai/codex`), the second concrete provider and the one
that proves the abstraction is real rather than aspirational - see
`docs/CLI_INTEGRATION.md` for the complete, empirically-verified flag-by-flag
reasoning (installed and probed directly - version `codex-cli 0.150.1` on
Windows - while building this, though without valid credentials, which the
design below routes around rather than assumes past).

**Detection** (`app/ai/providers/codex/detect.py`): same shape as Claude's -
settings override → `CODEX_CLI_PATH` env var → `PATH` → well-known npm install
location, verified by running `--version`.

**Authentication is checked separately from installation, and cheaply.** This
is the one place Codex's availability check goes further than Claude's, for a
concrete, measured reason: an *unauthenticated* `codex exec` call does not
fail fast. It retries the WebSocket transport five times, falls back to
HTTPS, retries five more times, and only then reports failure - about 35-40
seconds end to end, observed directly. Reporting a provider "available" and
only discovering it cannot actually run 40 seconds into the first job would
make the selector feel broken. `codex login status` answers "would a real call
succeed" locally, with no network retry loop, in well under a second (also
measured directly) - `check_availability()` uses this, and **must never** be
changed to probe with a live `exec` call instead.

**Execution** (`app/ai/providers/codex/cli.py`): `codex exec
--skip-git-repo-check --sandbox read-only --ephemeral --ignore-user-config
--ignore-rules --json -o <file>`, prompt on stdin, run from an empty
`storage/.codex-scratch/` directory - the same context-minimization reasoning
as Claude's scratch directory.

**The answer text comes from `-o` (`--output-last-message <FILE>`), not from
parsing `--json` event output.** This is a deliberate design response to an
honest gap: the *success-path* JSONL event shape could not be verified without
real credentials, only the failure path (`turn.failed`, confirmed real and
stable) could be. Rather than guess at an unverified success schema, the
provider relies on a flag whose contract is documented and was directly
confirmed both ways - present with the final message on nothing tested here
that resembles success, and **not created at all** on a failed turn (verified:
the file simply does not exist after a failed run). The `--json` stream is
still consumed, but only for the live console and for detecting a
`turn.failed` message - never as the source of the answer.

**No system-prompt flag exists on `exec`** (absent from its real `--help`
output). `CodexProvider._compose_prompt` folds the system instruction into the
prompt body instead of depending on a flag that is not there.

**Attachments** follow the identical inlining approach as Claude's, for the
identical reason (no reliable way to grant tool-use permission in a
non-interactive run).

## Adding a third provider

1. Create `app/ai/providers/<name>/` with a `<Name>Provider(AIProvider)`.
2. Implement `check_availability` (verify an API key is configured, or a CLI
   is installed **and authenticated** - see the Codex section above for why
   "installed" alone is not the same question, and why that check must stay
   fast regardless of how slow a real call would be).
3. Implement `generate`: build the request in whatever shape that provider
   needs, run it (through `app/process/runner.py` if it's a CLI, or an HTTP
   client if it's a direct API), stream output through `on_output`, map errors
   to `AIError` subclasses.
4. Register it in `ProviderRegistry.build()` (`app/ai/registry.py`) - append
   one line alongside the existing two.
5. Add its models to `ModelRegistry` — either as built-ins in `app/ai/models.py`
   or via `config/models.json`, which merges over built-ins by id at load
   time. If the provider's own model-naming is a moving target you cannot
   verify (as Codex's was here), a single sentinel entry that omits the model
   flag entirely - see `docs/AI_MODELS.md`'s Codex section - is the more
   honest choice than a guessed, possibly-already-stale list.
6. Add its CLI-path setting to `SettingsService.DEFAULTS`
   (`app/services/settings.py`, e.g. `ai.<name>_cli_path`) and to
   `PROVIDER_CLI_PATH_KEY` in `frontend/src/pages/SettingsPage.tsx`'s
   `AiSection`, following the existing two entries.

Nothing else changes. `AIService`, every job handler, the recommendation
engine, and the frontend's provider/model selectors all already work against
the interface, not against a concrete provider by name. The frontend provider
picker (`frontend/src/pages/SettingsPage.tsx`, `AiSection`) and the model
selector (`frontend/src/components/ai/ModelSelector.tsx`) both render whatever
`GET /api/ai/providers` reports — a third entry just appears in both.

## Common mistakes

- **Skipping the availability check pattern, or making it slow.** Don't let
  `generate()` be the first place a missing dependency is discovered — that
  turns into a raw exception mid-job instead of a clean "provider
  unavailable" state the UI can show before the user even starts. And don't
  let `check_availability()` itself make a real network call "just to be
  sure" - see the Codex 40-second measurement above for exactly why not.
- **Returning provider-native error types.** Always wrap in `AIError` (or a
  subclass) with a Persian `user_message`; see `app/core/errors.py`.
- **Assuming every provider supports every task.** Override `supported_tasks`
  if a provider genuinely can't do something (e.g. a provider with no
  analysis capability); `AIService.run` checks this before dispatching.
- **Hardcoding a model name you have not verified against the real CLI.**
  Codex's model naming was observed to already be ahead of common public
  assumptions about it by the time this was built - a single "use the CLI's
  own default" entry beats a guessed list that looks authoritative but is
  quietly wrong.
