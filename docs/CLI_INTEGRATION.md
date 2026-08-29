# CLI Integration

## Purpose

Exact reasoning behind every flag and design decision for both CLIs the
platform drives - Claude and OpenAI Codex. If you're touching how either is
invoked, this is the document to update alongside the code — flags drift as a
CLI evolves, and future-you needs to know *why* a flag is there before
removing it.

The two integrations are structured identically on purpose (detect → build
argv → run → parse), and the reasoning for many individual choices - stdin for
the prompt, an empty scratch directory, inlined attachments - is shared. Where
it is shared, it is written once, under Claude, and the Codex section points
back to it rather than repeating it.

---

# Part 1: Claude CLI

## Detection

`app/ai/providers/claude/detect.py::detect_claude_cli`, resolution order:

1. `ai.claude_cli_path` setting (manual override from Settings → AI)
2. `CLAUDE_CLI_PATH` environment variable
3. `claude` on `PATH` (`shutil.which`)
4. Well-known Windows install locations:
   `~/.local/bin/claude.exe`, `~/AppData/Local/Programs/claude/claude.exe`,
   `~/AppData/Roaming/npm/claude.cmd`

Every candidate is verified by actually running `<candidate> --version` —
a stale `PATH` entry after an uninstall is a common real-world case, and
"the file exists" is not the same as "the file runs."

## Invocation

`app/ai/providers/claude/cli.py::ClaudeCLI.build_argv`:

```
claude --print --output-format json --strict-mcp-config
       --no-session-persistence --tools Read
       [--model <alias>] [--append-system-prompt <text>]
```

| Flag | Why |
|---|---|
| `-p` / `--print` | Non-interactive mode. Without it the CLI starts a REPL and never returns. |
| `--output-format json` | A machine-readable envelope with the answer in `result` plus usage/error fields. Parsing free text would be guesswork and would break on any CLI wording change. |
| `--strict-mcp-config` | A text transformation must not inherit the user's own MCP servers. |
| `--no-session-persistence` | This is a one-shot transformation, not a conversation; no session file should be left behind. |
| `--tools Read` | The CLI rejects an *empty* `--tools` list, so this is the minimum that satisfies it. The provider never actually depends on tool use — see "attachments are inlined" below — so the model has nothing to call it for. |
| `--model <alias>` | Set from `RecommendationEngine.resolve()`, never hardcoded. |
| `--append-system-prompt` | Built by `app/ai/prompts/library.py::build_system_prompt`; see `docs/AI_SYSTEM.md`. |

## The prompt goes on stdin, never as an argument

Two independent reasons:

1. **Length.** Transcripts routinely exceed the Windows command-line length
   limit (~32,767 characters). A prompt as an argument would truncate or fail
   unpredictably above that.
2. **Process-list exposure.** An argument is visible to anything that can list
   processes on the machine; stdin is not.

`ProcessSpec.stdin_text` (`app/process/runner.py`) writes the text and closes
stdin, which is what lets the CLI see EOF and actually return.

## Running from an empty scratch directory

This is the single highest-leverage cost optimisation in the AI layer, and
it's easy to accidentally undo.

The CLI auto-discovers `CLAUDE.md` files and project context from its current
working directory. Running it from inside this repository would prepend the
*entire project* to every single transformation call. Measured on this
machine: a trivial "reply with the word OK" call from the project root used
~37,800 cache-creation input tokens; the same call from an empty directory
used ~5,800 — roughly a 6x reduction, and the cost difference compounds across
every AI call the platform makes.

`ClaudeCLI.run` always executes with `cwd=SCRATCH_DIR`
(`storage/.cli-scratch/`, created on demand, empty by construction). **Never
change this to run from the project workspace or the repository root** without
re-measuring the cost impact.

## Attachments are inlined, not passed as `--add-dir` + tool calls

See `docs/AI_PROVIDERS.md`. In `--print` mode, a tool call needing permission
has nowhere to prompt and can stall or silently fail. `ClaudeProvider._compose_prompt`
reads text attachments and embeds them between `--- FILE: name ---` delimiters
directly in the prompt instead.

## Parsing the response

`_parse_envelope` (`cli.py`) is defensive: it tries `json.loads` on the whole
output first, then falls back to scanning lines in reverse for one that parses
as a JSON object, because the CLI can print warnings before the JSON envelope.
`_extract_text` checks several possible keys (`result`, `text`, `content`,
`response`) in case the envelope shape changes across CLI versions, rather
than hard-coding `payload["result"]`.

## Error translation

`_hint_for_stderr` maps known failure substrings (`not logged in`, `rate
limit`, `credit`/`billing`, `timed out`, `context ... long`) to actionable
Persian hints, because "Claude درخواست را با خطا برگرداند" alone doesn't tell
a user whether to log in, wait, or shorten their input. Add a new mapping here
when you discover a new class of CLI failure in practice — don't leave the
user guessing.

## Testing

`backend/tests/integration/test_jobs_pipeline.py::TestTextTaskJob` and the
manual verification in this project's build history both exercise real CLI
calls end to end (a real translation, a real cost/token measurement). These
are marked `@pytest.mark.slow` and skip cleanly when the CLI is unavailable —
see `docs/TESTING.md`.

---

# Part 2: OpenAI Codex CLI

Everything below was verified against a real install
(`npm install -g @openai/codex`, resolved version `codex-cli 0.150.1` on
Windows) during development. **One honest limitation up front:** no valid
Codex credentials were available in that environment, so the *failure* path
(auth error, timing, exit codes, JSONL shape) was verified directly and
repeatedly; the *success* path (a real answer coming back) was not. Every
design choice below that touches the success path was made specifically to
not depend on anything unverified - see "Getting the answer text" below for
the concrete mechanism.

## Detection

`app/ai/providers/codex/detect.py::detect_codex_cli`, resolution order:

1. `ai.codex_cli_path` setting (manual override from Settings → AI)
2. `CODEX_CLI_PATH` environment variable
3. `codex` on `PATH` (`shutil.which`)
4. Well-known npm global-install locations:
   `~/AppData/Roaming/npm/codex.cmd`, `~/AppData/Roaming/npm/codex`

Same "verify by actually running `--version`" rule as Claude, same reason.

## Authentication is a second, separate, fast check

This is the one place the Codex integration goes further than Claude's, for a
concrete measured reason, not a stylistic one.

An **unauthenticated** `codex exec` call does not fail fast. Observed directly:
it retries the WebSocket transport (`wss://api.openai.com/v1/responses`) five
times with growing backoff, falls back to HTTPS, retries five more times, and
only then emits a terminal `turn.failed` - roughly **35-40 seconds** end to
end before ever reporting failure. If `check_availability()` had to run a
real prompt to find this out, every page that shows the provider selector
would either block for 40 seconds or need to hide that cost behind a spinner -
neither is acceptable for what should be a cheap status check.

`codex login status` answers the same question - "would a real call
succeed?" - without ever touching the network: confirmed to print `Not logged
in` and exit `1` in about 0.2 seconds when unauthenticated. `check_availability()`
uses this exclusively (`app/ai/providers/codex/detect.py::check_login_status`).
**Never replace this with a live `exec` call** without re-measuring; the cost
above is why it is not one.

## Invocation

`app/ai/providers/codex/cli.py::CodexCLI.build_argv`:

```
codex exec --skip-git-repo-check --sandbox read-only
           --ephemeral --ignore-user-config --ignore-rules
           --json -o <output-file>
           [-m <model>]
```

| Flag | Why |
|---|---|
| `exec` | The non-interactive subcommand - the Codex analogue of Claude's `--print`. Confirmed: prompts read from stdin when no positional argument is given ("Reading prompt from stdin..." observed on stderr). |
| `--skip-git-repo-check` | `exec` refuses to run outside a git repository by default; the scratch directory this runs from (see below) deliberately is not one. |
| `--sandbox read-only` | The narrowest sandbox Codex offers. A text-in/text-out call never needs to write files - the same minimum-capability reasoning as Claude's `--tools Read`. |
| `--ephemeral` | Do not persist a resumable session for a one-shot call - the Codex analogue of Claude's `--no-session-persistence`. |
| `--ignore-user-config` | Do not load `~/.codex/config.toml` (the user's own MCP servers, provider settings, etc.) - the Codex analogue of Claude's `--strict-mcp-config`. Confirmed this does not affect authentication (`CODEX_HOME` auth is unaffected by this flag per the CLI's own `--help` text). |
| `--ignore-rules` | Do not load project/user execpolicy `.rules` files - further isolates the call from anything specific to whatever happens to be on this machine. |
| `--json` | Emits JSONL events on stdout. Confirmed by direct testing that this stream is clean - zero interleaved log/error lines - which is what makes it usable for the live console at all (see "Streams" below). |
| `-o <file>` | See "Getting the answer text" below - this is the actual mechanism for retrieving the result, not a nicety. |
| `-m <model>` | Only added when a caller resolved an explicit model. Omitted entirely for the registry's `codex-default` sentinel - see `docs/AI_MODELS.md`. |

**Flags that exist on the top-level `codex` command but NOT on `codex exec`,**
learned by testing rather than assuming: `-a/--ask-for-approval` looked like it
should apply (it is listed under interactive-mode `codex --help`) but
`codex exec --ask-for-approval never` fails with `unexpected argument`. `exec`
governs the same concern through `--sandbox` alone. Do not add
`--ask-for-approval` to `exec`'s argv without re-checking against
`codex exec --help` first.

## Streams: stdout is clean JSONL, stderr is the tracing logger

Confirmed by direct testing (redirecting each separately): with `--json`,
**stdout carries only JSON lines** - zero interleaved `ERROR` lines were ever
observed there. The Rust tracing logger's retry/connection noise
(`codex_api::endpoint::responses_websocket: ...`) goes to **stderr**
exclusively. The wrapper relies on this split: `on_output("stdout", ...)` for
JSONL parsing and the primary console feed, `on_output("stderr", ...)` for
the diagnostic noise - swapping these would break JSONL parsing on the first
retry-warning line.

## Getting the answer text: `-o`, not JSON parsing

The success-path JSONL event shape (an "agent message" event, presumably)
could not be observed without valid credentials - every real run available
during development ended in `turn.failed`. Rather than guess at a schema that
might be wrong today or drift tomorrow, the provider depends on
`-o/--output-last-message <FILE>` instead: its own `--help` text documents
that it "specifies file where the last message from the agent should be
written," and this was confirmed both ways in testing - the file is
**not created at all** on a failed turn (checked directly: absent after every
failed run), which is exactly the "did it actually work" signal a fragile
JSON-shape assumption could get wrong.

`CodexCLI.run` therefore treats the `-o` file as authoritative:

* file present and non-empty → that content is the answer, full stop, no
  further parsing needed;
* file absent or empty → treated as failure regardless of exit code, using
  whatever `turn.failed` message or stderr tail was captured for the error
  detail.

The `--json` stream is still consumed, but only for two things: live console
lines, and detecting a `turn.failed` event to build a clean error message
before the process exits. It is never the source of the answer text.

## No system-prompt flag - fold it into the prompt

`codex exec --help` has no `--system-prompt` or equivalent (checked directly
against the real flag list). `CodexProvider._compose_prompt` prepends the
system instruction to the prompt body instead, clearly delimited, rather than
depending on a flag that does not exist.

## Exit codes and the terminal failure event

Confirmed directly: a failed turn exits with status **1** (not 0), and the
final stdout line is `{"type": "turn.failed", "error": {"message": "..."}}`.
`_failure_message()` in `cli.py` extracts that message; `_try_parse_json()`
is defensive about any non-JSON line reaching the parser (the CLI does print
a `Reading prompt from stdin...` notice on stderr, never stdout, but the
parser does not assume that split blindly).

## Running from an empty scratch directory

Same reasoning as Claude's - see Part 1 above. Codex's own directory is
`storage/.codex-scratch/`, kept separate from Claude's
`storage/.cli-scratch/` so the two integrations never share state.

## Attachments

Identical approach to Claude's, for the identical reason - see Part 1. A
non-interactive run has nowhere to grant tool-use permission if the model
tries to read a file itself, so text attachments are inlined into the prompt
instead.

## Error translation

`_hint_for()` in `cli.py` maps known substrings (`not logged in` / `401` /
`unauthorized`, `429` / rate limit, `timed out` / `network` / `reconnecting`)
to actionable Persian hints, mirroring Claude's `_hint_for_stderr`. Extend this
when a new failure class is discovered in practice.

## What was NOT verified, and why the design does not depend on it

Documented explicitly here so nobody "fixes" this integration back into a
fragile state by assuming more was tested than was:

* The exact JSONL event(s) for a **successful** turn - unknown. The `-o` file
  mechanism above is what makes this not matter for correctness.
* Whether a logged-in session's `codex login status` output matches the
  "exit 0 means logged in" assumption exactly, or has its own subtleties -
  `check_login_status()` treats any non-zero exit as "not logged in" rather
  than parsing status text, which is the more conservative reading either way.
* Real-world latency and token/cost characteristics of a genuine authenticated
  call - no equivalent of Claude's measured "empty scratch dir vs. project
  root" cost comparison exists for Codex yet. The same empty-scratch-directory
  precaution is applied on the reasonable assumption that Codex's own
  `AGENTS.md`/project-context discovery has a similar cost profile to Claude's
  `CLAUDE.md` discovery, but this has not been measured directly.

## Testing

`backend/tests/unit/test_ai.py::TestCodexCliArgvConstruction` and
`TestCodexJsonlParsing` cover the pure logic (argv construction, event
parsing) without needing the CLI installed. `TestCodexProviderLive` runs
against the real installed CLI when present (skips otherwise) and asserts the
availability check completes in well under the ~40 seconds an unauthenticated
live call would take - see `docs/TESTING.md`.
