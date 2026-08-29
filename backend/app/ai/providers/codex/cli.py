"""Low-level OpenAI Codex CLI wrapper.

Owns *how* the ``codex`` executable is invoked, mirroring the split in the
Claude integration: this module knows the flags, ``provider.py`` knows what to
ask for. See ``docs/CLI_INTEGRATION.md`` for the full reasoning behind every
flag and for what could and could not be verified empirically - no valid
Codex credentials were available while building this integration, so the
design below deliberately avoids depending on anything that could only be
confirmed with a real authenticated call.

Verified facts this module relies on (real ``codex exec --help`` output and
real runs against ``codex-cli 0.150.1`` on Windows, all without credentials):

* ``codex exec`` reads the prompt from **stdin** when no positional argument
  is given - confirmed by observing "Reading prompt from stdin..." on stderr.
* ``--json`` puts clean, uninterleaved JSONL on **stdout** (verified: zero
  ``ERROR`` lines ever appeared there); the tracing logger's retry/error noise
  goes to **stderr**, never stdout.
* ``-o/--output-last-message <FILE>`` is documented to contain exactly the
  agent's final message, and was confirmed to be **not created at all** on a
  failed turn. This is what the provider treats as authoritative for the
  answer text, instead of parsing a specific JSONL success-event shape that
  could not be observed without credentials - the same "don't assume one
  rigid shape" caution the Claude wrapper applies to its own JSON envelope.
* A failed turn exits with status **1** and emits a terminal
  ``{"type":"turn.failed","error":{"message": "..."}}`` line on stdout.
* There is no ``--system-prompt`` equivalent on ``exec`` (absent from its
  flag list) - system instructions are folded into the prompt body itself
  instead of relying on a flag that does not exist.
* Unauthenticated calls do **not** fail fast: observed 35-40 seconds of
  WebSocket-then-HTTPS retry before the terminal failure. This is exactly why
  availability checks use ``codex login status`` (see ``detect.py``) and never
  a live ``exec`` call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.errors import AIError, ProcessError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.process import CancelToken, ProcessSpec, run_process

logger = get_logger(__name__)

OutputCallback = Callable[[str, str], None]

#: Directory the CLI runs in. Kept empty for the same reason the Claude
#: scratch directory is: Codex's own project/context discovery (AGENTS.md,
#: repo state) should not be pulled into a one-shot text transformation.
SCRATCH_DIR = PATHS.storage / ".codex-scratch"


@dataclass(slots=True)
class CodexResult:
    text: str
    model: str
    exit_code: int
    duration_seconds: float
    stderr: str


class CodexCLI:
    """Builds and runs ``codex exec`` commands."""

    def __init__(self, executable: Path, *, default_timeout: int = 900) -> None:
        self.executable = Path(executable)
        self.default_timeout = default_timeout

    def build_argv(self, *, model: str | None, output_file: Path) -> list[str]:
        argv: list[str] = [
            str(self.executable),
            "exec",
            # This project's scratch directories are not git repositories;
            # exec refuses to run outside one without this.
            "--skip-git-repo-check",
            # No file edits are ever needed for a text-in/text-out call - the
            # narrowest sandbox available, mirroring the Claude provider's
            # `--tools Read`-only minimum-capability choice.
            "--sandbox",
            "read-only",
            # Do not write a resumable session to disk for a one-shot call.
            "--ephemeral",
            # Do not load the user's own ~/.codex/config.toml (MCP servers,
            # project rules, etc.) - the Codex analogue of Claude's
            # `--strict-mcp-config`.
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "-o",
            str(output_file),
        ]
        if model:
            argv += ["-m", model]
        return argv

    def run(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout_seconds: int | None = None,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> CodexResult:
        if not prompt.strip():
            raise AIError(
                "refusing to send an empty prompt to the CLI",
                user_message="متنی برای ارسال به هوش مصنوعی وجود ندارد.",
            )

        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        output_file = SCRATCH_DIR / f"last_message_{new_id()}.txt"
        output_file.unlink(missing_ok=True)

        argv = self.build_argv(model=model, output_file=output_file)

        if on_output:
            on_output("system", f"$ {Path(argv[0]).name} {' '.join(argv[1:])}")
            on_output("system", f"prompt: {len(prompt)} characters")

        failure_message: str | None = None

        def handle_stdout(line: str) -> None:
            nonlocal failure_message
            event = _try_parse_json(line)
            if event is not None:
                message = _failure_message(event)
                if message:
                    failure_message = message
            if on_output and len(line) < 400:
                on_output("stdout", line)

        def handle_stderr(line: str) -> None:
            if on_output:
                on_output("stderr", line)

        try:
            result = run_process(
                ProcessSpec(
                    argv=argv,
                    cwd=SCRATCH_DIR,
                    stdin_text=prompt,
                    timeout_seconds=timeout_seconds or self.default_timeout,
                ),
                on_stdout=handle_stdout,
                on_stderr=handle_stderr,
                cancel_token=cancel_token,
                check=False,
            )
        except ProcessError as exc:
            raise AIError(
                f"codex CLI could not be executed: {exc.message}",
                user_message="اجرای ابزار خط فرمان Codex ممکن نشد.",
                hint="نصب بودن Codex CLI و صحت مسیر آن را در تنظیمات بررسی کنید.",
            ) from exc

        text = ""
        if output_file.is_file():
            text = output_file.read_text(encoding="utf-8", errors="replace").strip()
            output_file.unlink(missing_ok=True)

        if on_output:
            on_output("system", f"exit={result.exit_code} in {result.duration_seconds:.1f}s")

        if not text:
            # Verified: the output-last-message file is not created at all on
            # a failed turn, so an empty/missing file plus a non-zero exit or
            # a captured turn.failed message is a real failure, not a fluke.
            detail = failure_message or result.stderr[-500:] or f"exit code {result.exit_code}"
            raise AIError(
                f"codex produced no output: {detail}",
                user_message="Codex پاسخی برنگرداند.",
                hint=_hint_for(failure_message or result.stderr),
                details={"exit_code": result.exit_code},
            )

        if result.exit_code != 0:
            # A non-empty output file alongside a non-zero exit was never
            # observed in testing; log it rather than discarding a possibly
            # genuine answer, since the file's presence is the stronger
            # verified signal (see module docstring).
            logger.warning(
                "codex exited %s but still wrote an output file; using it anyway",
                result.exit_code,
            )

        return CodexResult(
            text=text,
            model=model or "codex-default",
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            stderr=result.stderr,
        )


def _try_parse_json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _failure_message(event: dict[str, Any]) -> str | None:
    """Extract a human-readable message from a ``turn.failed`` JSONL event.

    Verified shape: ``{"type": "turn.failed", "error": {"message": "..."}}``.
    """
    if event.get("type") != "turn.failed":
        return None
    error = event.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message
    return "اجرای Codex با خطا مواجه شد."


def _hint_for(detail: str | None) -> str:
    """Map a known Codex CLI failure to actionable Persian advice.

    Substrings verified against real output from this CLI version; anything
    unrecognised falls through to a generic hint pointing at the job console.
    """
    lowered = (detail or "").lower()
    if "not logged in" in lowered or "401" in lowered or "unauthorized" in lowered:
        return "به نظر می‌رسد Codex CLI وارد حساب نشده است. در ترمینال دستور codex login را اجرا کنید."
    if "429" in lowered or "rate limit" in lowered:
        return "محدودیت درخواست فعال شده است. چند دقیقه بعد دوباره تلاش کنید."
    if "timed out" in lowered or "timeout" in lowered or "network" in lowered or "reconnecting" in lowered:
        return "ارتباط شبکه با سرویس Codex برقرار نشد. اتصال اینترنت را بررسی کنید."
    return "جزئیات فنی در کنسول هوش مصنوعی و فایل لاگ در دسترس است."
