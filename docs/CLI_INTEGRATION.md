# Claude CLI Integration

## Purpose

Exact reasoning behind every flag and design decision in
`app/ai/providers/claude/cli.py` and `detect.py`. If you're touching how the
platform invokes the Claude CLI, this is the document to update alongside the
code — flags drift as the CLI evolves, and future-you needs to know *why* a
flag is there before removing it.

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
