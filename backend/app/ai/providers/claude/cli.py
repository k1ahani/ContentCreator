"""Low-level Claude CLI wrapper.

Owns *how* the ``claude`` executable is invoked. The provider above it
(``provider.py``) owns *what* to ask for. Keeping the two apart means a change
in CLI flags touches exactly one file.

Invocation decisions and why they were made:

``-p / --print``
    Non-interactive mode. Without it the CLI starts a REPL and never exits.

prompt on **stdin**, not as an argument
    Transcripts routinely exceed the Windows command-line length limit
    (~32 767 characters), and arguments are visible in the process list.
    Piping avoids both problems.

``--output-format json``
    Gives a machine-readable envelope with the text in ``result`` plus usage
    and error fields. Parsing free text would be guesswork.

``--strict-mcp-config`` and ``--no-session-persistence``
    A text transformation must not inherit the user's MCP servers or leave
    session files behind. This also cuts the context the CLI sends.

``--tools Read``
    The CLI rejects an empty ``--tools`` list, so this is the minimum. The
    provider never depends on tool use: file attachments are inlined into the
    prompt (see ``provider.py``), so the model has no reason to call anything.

**clean working directory**
    The CLI auto-discovers ``CLAUDE.md`` and project context from its cwd.
    Running from the project workspace would prepend the whole repository to
    every call. Measured on this machine, running from an empty directory cut
    a trivial call from ~37 800 to ~10 300 context tokens. The runner therefore
    always executes inside ``storage/.cli-scratch``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.errors import AIError, EmptyAIResponseError, ProcessError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.process import CancelToken, ProcessSpec, run_process

logger = get_logger(__name__)

OutputCallback = Callable[[str, str], None]

#: Directory the CLI runs in. Kept empty so no project context is discovered.
SCRATCH_DIR = PATHS.storage / ".cli-scratch"


@dataclass(slots=True)
class ClaudeResult:
    """Parsed outcome of one CLI invocation."""

    text: str
    model: str
    exit_code: int
    duration_seconds: float
    stderr: str
    usage: dict[str, Any]
    session_id: str | None = None
    cost_usd: float | None = None


class ClaudeCLI:
    """Builds and runs ``claude`` commands."""

    def __init__(self, executable: Path, *, default_timeout: int = 900) -> None:
        self.executable = Path(executable)
        self.default_timeout = default_timeout

    # -- command construction ----------------------------------------------

    def build_argv(
        self,
        *,
        model: str | None,
        system_prompt: str | None,
        extra_dirs: list[Path] | None = None,
    ) -> list[str]:
        """Assemble the argument list. Never a shell string."""
        argv: list[str] = [
            str(self.executable),
            "--print",
            "--output-format",
            "json",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--tools",
            "Read",
        ]
        if model:
            argv += ["--model", model]
        if system_prompt:
            argv += ["--append-system-prompt", system_prompt]
        for directory in extra_dirs or []:
            argv += ["--add-dir", str(directory)]
        return argv

    # -- execution ---------------------------------------------------------

    def run(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        timeout_seconds: int | None = None,
        extra_dirs: list[Path] | None = None,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> ClaudeResult:
        """Run one prompt and return the parsed result."""
        if not prompt.strip():
            raise AIError(
                "refusing to send an empty prompt to the CLI",
                user_message="متنی برای ارسال به هوش مصنوعی وجود ندارد.",
            )

        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        argv = self.build_argv(
            model=model, system_prompt=system_prompt, extra_dirs=extra_dirs
        )

        if on_output:
            # Show the command without the system prompt body, which can be long.
            on_output("system", f"$ {_redact(argv)}")
            on_output("system", f"prompt: {len(prompt)} characters")

        stdout_chunks: list[str] = []

        def handle_stdout(line: str) -> None:
            stdout_chunks.append(line)
            # The JSON envelope arrives as one enormous line; streaming it raw
            # would flood the console with usage data. Report progress instead.
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
                f"claude CLI could not be executed: {exc.message}",
                user_message="اجرای ابزار خط فرمان Claude ممکن نشد.",
                hint="نصب بودن Claude CLI و صحت مسیر آن را در تنظیمات بررسی کنید.",
            ) from exc

        raw = "\n".join(stdout_chunks).strip()

        if result.exit_code != 0 and not raw:
            raise AIError(
                f"claude exited with {result.exit_code}: {result.stderr[:500]}",
                user_message="اجرای Claude با خطا مواجه شد.",
                hint=_hint_for_stderr(result.stderr),
                details={"exit_code": result.exit_code},
            )

        payload = _parse_envelope(raw)
        text = _extract_text(payload, raw)

        if payload.get("is_error"):
            message = str(payload.get("result") or payload.get("error") or "")[:500]
            raise AIError(
                f"claude reported an error: {message}",
                user_message="Claude درخواست را با خطا برگرداند.",
                hint=_hint_for_stderr(message or result.stderr),
            )

        if not text.strip():
            raise EmptyAIResponseError(
                "claude returned an empty result",
                hint="متن ورودی را کوتاه‌تر کنید یا دوباره تلاش کنید.",
            )

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        if on_output:
            on_output("system", f"exit={result.exit_code} in {result.duration_seconds:.1f}s")

        return ClaudeResult(
            text=text.strip(),
            model=_resolve_model_name(payload, model),
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            stderr=result.stderr,
            usage=usage or {},
            session_id=payload.get("session_id"),
            cost_usd=payload.get("total_cost_usd"),
        )


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------


def _parse_envelope(raw: str) -> dict[str, Any]:
    """Parse the ``--output-format json`` envelope.

    The CLI may emit warnings before the JSON, so fall back to the last line
    that parses as an object rather than assuming the whole output is JSON.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _extract_text(payload: dict[str, Any], raw: str) -> str:
    """Pull the answer out of the envelope, tolerating format changes."""
    for key in ("result", "text", "content", "response"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    # No recognisable envelope: the CLI probably printed plain text.
    return "" if raw.lstrip().startswith("{") else raw


def _resolve_model_name(payload: dict[str, Any], requested: str | None) -> str:
    """Report the model the CLI actually used, falling back to the alias."""
    usage = payload.get("modelUsage")
    if isinstance(usage, dict) and usage:
        # Pick the entry with the most output tokens: the main model, not a
        # background helper the CLI may have used.
        try:
            best = max(
                usage.items(),
                key=lambda item: (item[1] or {}).get("outputTokens", 0)
                if isinstance(item[1], dict)
                else 0,
            )
            return best[0]
        except (ValueError, TypeError):  # pragma: no cover - defensive
            pass
    return requested or "unknown"


def _redact(argv: list[str]) -> str:
    """Render argv for the console, truncating the system prompt."""
    parts: list[str] = []
    skip_next = False
    for index, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            parts.append(f"<{len(arg)} chars>")
            continue
        parts.append(Path(arg).name if index == 0 else arg)
        if arg == "--append-system-prompt":
            skip_next = True
    return " ".join(parts)


def _hint_for_stderr(stderr: str) -> str:
    """Map a known CLI failure to actionable Persian advice."""
    lowered = (stderr or "").lower()
    if "not logged in" in lowered or "authentication" in lowered or "unauthorized" in lowered:
        return "به نظر می‌رسد Claude CLI وارد حساب نشده است. در ترمینال دستور claude را اجرا و وارد حساب شوید."
    if "rate limit" in lowered or "429" in lowered:
        return "محدودیت درخواست فعال شده است. چند دقیقه بعد دوباره تلاش کنید."
    if "credit" in lowered or "billing" in lowered or "quota" in lowered:
        return "اعتبار حساب کافی نیست. وضعیت اشتراک یا اعتبار خود را بررسی کنید."
    if "timed out" in lowered or "etimedout" in lowered or "network" in lowered:
        return "ارتباط شبکه برقرار نشد. اتصال اینترنت را بررسی کنید."
    if "context" in lowered and "long" in lowered:
        return "متن ورودی بیش از حد بلند است. آن را به بخش‌های کوچک‌تر تقسیم کنید."
    return "جزئیات فنی در کنسول هوش مصنوعی و فایل لاگ در دسترس است."
