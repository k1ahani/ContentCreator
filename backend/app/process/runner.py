"""Managed external process execution.

Every external tool the platform runs - the Claude CLI, ffmpeg, ffprobe,
PowerShell for SAPI voices - goes through this module. Nothing else in the
codebase calls ``subprocess`` directly.

Guarantees:

* **No shell.** Commands are always an argument *list* with ``shell=False``.
  A Persian filename, a path with spaces, or a prompt containing ``&`` or ``|``
  is passed as one opaque argument and can never be re-interpreted as syntax.
* **Live output.** stdout and stderr are drained on separate threads and
  delivered line by line through callbacks, so the UI console updates while the
  process is still running rather than after it exits.
* **Real cancellation.** On Windows, terminating a parent does not stop its
  children; ``claude`` in particular spawns a Node process tree. Cancellation
  therefore uses ``taskkill /T /F`` to kill the whole tree, falling back to
  ``Popen.kill`` if taskkill is unavailable.
* **UTF-8 everywhere.** Pipes are decoded as UTF-8 with ``errors="replace"``
  and the child is given ``PYTHONIOENCODING``/``PYTHONUTF8`` so Persian text
  survives a console whose code page is cp1252.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app.core.errors import ProcessCancelledError, ProcessError, ProcessTimeoutError
from app.core.logging import get_logger

logger = get_logger(__name__)

LineCallback = Callable[[str], None]

# Windows-only creation flags: keep child console windows from flashing on
# screen, and put the child in its own process group so we can signal it.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


class CancelToken:
    """Cooperative cancellation shared between a caller and a running process.

    The job system hands one of these to every handler; the handler passes it
    down to :func:`run_process`, which watches it while draining output.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise ProcessCancelledError("operation cancelled by user")

    def wait(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds, returning True if cancelled."""
        return self._event.wait(timeout)


@dataclass(slots=True)
class ProcessResult:
    """Outcome of a finished process."""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.cancelled


@dataclass(slots=True)
class ProcessSpec:
    """Everything needed to launch one process."""

    argv: Sequence[str]
    cwd: Path | None = None
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: int | None = None
    #: Text written to the child's stdin, then stdin is closed. Used to pass
    #: long prompts to the Claude CLI without hitting the command-line length
    #: limit or exposing prompt text in the process list.
    stdin_text: str | None = None


def _child_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    # Force UTF-8 in any Python child and make ffmpeg's own output predictable.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env.update({key: str(value) for key, value in overrides.items()})
    return env


def _creation_flags() -> int:
    if os.name != "nt":  # pragma: no cover - platform guard
        return 0
    return _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP


def kill_process_tree(process: subprocess.Popen) -> None:
    """Terminate a process and every child it spawned.

    ``Popen.kill`` only kills the direct child. The Claude CLI is a Node
    launcher that spawns further processes, and ffmpeg can spawn helpers, so
    without a tree kill a cancelled job leaves work running in the background.
    """
    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=15,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("taskkill failed for pid %s: %s", process.pid, exc)
        else:
            try:
                process.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                pass

    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        logger.warning("could not kill pid %s: %s", process.pid, exc)


def _pump(stream, sink: list[str], callback: LineCallback | None, label: str) -> None:
    """Drain one pipe to completion, line by line."""
    try:
        for raw_line in iter(stream.readline, ""):
            line = raw_line.rstrip("\r\n")
            sink.append(line)
            if callback is not None:
                try:
                    callback(line)
                except Exception:  # pragma: no cover - callback must not kill the pump
                    logger.exception("error in %s callback", label)
    except (ValueError, OSError):
        # Pipe closed underneath us during cancellation; nothing to report.
        pass
    finally:
        try:
            stream.close()
        except (ValueError, OSError):
            pass


def run_process(
    spec: ProcessSpec,
    *,
    on_stdout: LineCallback | None = None,
    on_stderr: LineCallback | None = None,
    cancel_token: CancelToken | None = None,
    check: bool = True,
) -> ProcessResult:
    """Run a process to completion, streaming its output.

    Raises :class:`ProcessCancelledError` if ``cancel_token`` fires,
    :class:`ProcessTimeoutError` on timeout, and :class:`ProcessError` on a
    non-zero exit when ``check`` is true.
    """
    argv = [str(part) for part in spec.argv]
    if not argv:
        raise ValueError("argv must not be empty")

    started = time.monotonic()
    logger.debug("spawning: %s", argv)

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(spec.cwd) if spec.cwd else None,
            env=_child_environment(spec.env_overrides),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line buffered
            creationflags=_creation_flags(),
            shell=False,
        )
    except FileNotFoundError as exc:
        raise ProcessError(
            f"executable not found: {argv[0]}",
            command=argv[0],
            exit_code=None,
        ) from exc
    except OSError as exc:
        raise ProcessError(
            f"could not start {argv[0]}: {exc}", command=argv[0], exit_code=None
        ) from exc

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    threads = [
        threading.Thread(
            target=_pump,
            args=(process.stdout, stdout_lines, on_stdout, "stdout"),
            daemon=True,
        ),
        threading.Thread(
            target=_pump,
            args=(process.stderr, stderr_lines, on_stderr, "stderr"),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    # Feed stdin then close it, otherwise a CLI waiting on EOF never returns.
    try:
        if spec.stdin_text is not None:
            process.stdin.write(spec.stdin_text)
        process.stdin.close()
    except (OSError, ValueError) as exc:
        logger.debug("could not write stdin for %s: %s", argv[0], exc)

    deadline = (
        started + spec.timeout_seconds if spec.timeout_seconds is not None else None
    )
    cancelled = False
    timed_out = False

    while True:
        try:
            process.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            pass

        if cancel_token is not None and cancel_token.cancelled:
            cancelled = True
            logger.info("cancelling %s (pid %s)", argv[0], process.pid)
            kill_process_tree(process)
            break

        if deadline is not None and time.monotonic() > deadline:
            timed_out = True
            logger.warning(
                "timeout after %ss, killing %s (pid %s)",
                spec.timeout_seconds,
                argv[0],
                process.pid,
            )
            kill_process_tree(process)
            break

    for thread in threads:
        thread.join(timeout=5)

    exit_code = process.poll()
    if exit_code is None:  # pragma: no cover - tree kill did not settle
        exit_code = -1

    result = ProcessResult(
        argv=argv,
        exit_code=exit_code,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        duration_seconds=time.monotonic() - started,
        cancelled=cancelled,
    )

    if cancelled:
        raise ProcessCancelledError(f"{argv[0]} cancelled by user")

    if timed_out:
        raise ProcessTimeoutError(
            f"{argv[0]} exceeded {spec.timeout_seconds}s",
            command=argv[0],
            exit_code=exit_code,
            stderr_tail=result.stderr,
        )

    if check and exit_code != 0:
        raise ProcessError(
            f"{argv[0]} exited with code {exit_code}",
            command=argv[0],
            exit_code=exit_code,
            stderr_tail=result.stderr,
        )

    return result


def probe_executable(
    executable: str | Path, args: Sequence[str] = ("--version",), timeout: int = 20
) -> tuple[bool, str]:
    """Check that an executable runs, returning ``(ok, first_output_line)``.

    Used by the dependency doctor and by every provider's availability check.
    Never raises: a missing tool is a normal, reportable state.
    """
    try:
        result = run_process(
            ProcessSpec(argv=[str(executable), *args], timeout_seconds=timeout),
            check=False,
        )
    except (ProcessError, ProcessCancelledError, ProcessTimeoutError) as exc:
        return False, str(exc)

    output = (result.stdout or result.stderr).strip()
    first_line = output.splitlines()[0] if output else ""
    return result.exit_code == 0, first_line
