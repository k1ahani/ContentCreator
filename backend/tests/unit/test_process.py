"""Process runner tests: real subprocess execution, no mocking.

Mocking subprocess here would test the mock. The whole point of this module is
that argument lists never go through a shell, and that is only provable by
actually launching a process with adversarial arguments.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from app.core.errors import ProcessCancelledError, ProcessError, ProcessTimeoutError
from app.process import CancelToken, ProcessSpec, probe_executable, run_process

PY = sys.executable


class TestBasicExecution:
    def test_captures_stdout(self):
        result = run_process(ProcessSpec(argv=[PY, "-c", "print('hello')"]))
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    def test_captures_unicode_stdout(self):
        result = run_process(ProcessSpec(argv=[PY, "-c", "print('سلام دنیا')"]))
        assert "سلام دنیا" in result.stdout

    def test_streams_output_live(self):
        lines = []
        run_process(
            ProcessSpec(argv=[PY, "-c", "print('a'); print('b')"]),
            on_stdout=lines.append,
        )
        assert lines == ["a", "b"]

    def test_stdin_is_passed_through(self):
        result = run_process(
            ProcessSpec(argv=[PY, "-c", "import sys; print(sys.stdin.read().strip())"],
                       stdin_text="hello from stdin")
        )
        assert result.stdout.strip() == "hello from stdin"

    def test_nonzero_exit_raises_by_default(self):
        with pytest.raises(ProcessError) as excinfo:
            run_process(ProcessSpec(argv=[PY, "-c", "import sys; sys.exit(7)"]))
        assert excinfo.value.exit_code == 7

    def test_check_false_does_not_raise(self):
        result = run_process(
            ProcessSpec(argv=[PY, "-c", "import sys; sys.exit(7)"]), check=False
        )
        assert result.exit_code == 7
        assert not result.ok

    def test_missing_executable_raises_process_error(self):
        with pytest.raises(ProcessError):
            run_process(ProcessSpec(argv=["this-executable-does-not-exist-xyz"]))

    def test_empty_argv_raises_value_error(self):
        with pytest.raises(ValueError):
            run_process(ProcessSpec(argv=[]))


class TestNoShellInterpretation:
    """Prove that argument list execution is immune to shell injection."""

    @pytest.mark.parametrize(
        "dangerous",
        [
            "a & echo injected",
            "a; rm -rf /",
            "a | cat /etc/passwd",
            "a `whoami`",
            "a $(whoami)",
            'a "quoted" b',
            "a > /tmp/should-not-be-created",
            "a && echo chained",
        ],
    )
    def test_argument_passed_verbatim(self, dangerous):
        result = run_process(
            ProcessSpec(argv=[PY, "-c", "import sys; print(repr(sys.argv[1]))", dangerous])
        )
        assert result.stdout.strip() == repr(dangerous)


class TestTimeout:
    def test_timeout_kills_process_and_raises(self):
        start = time.monotonic()
        with pytest.raises(ProcessTimeoutError):
            run_process(
                ProcessSpec(argv=[PY, "-c", "import time; time.sleep(30)"], timeout_seconds=1)
            )
        assert time.monotonic() - start < 10


class TestCancellation:
    def test_cancel_token_stops_running_process(self):
        token = CancelToken()
        threading.Timer(0.5, token.cancel).start()

        start = time.monotonic()
        with pytest.raises(ProcessCancelledError):
            run_process(
                ProcessSpec(argv=[PY, "-c", "import time; time.sleep(30)"]),
                cancel_token=token,
            )
        assert time.monotonic() - start < 10

    def test_raise_if_cancelled_before_run(self):
        token = CancelToken()
        token.cancel()
        with pytest.raises(ProcessCancelledError):
            token.raise_if_cancelled()

    def test_not_cancelled_initially(self):
        assert CancelToken().cancelled is False


class TestProbeExecutable:
    def test_working_executable_returns_true(self):
        ok, output = probe_executable(PY, ["--version"])
        assert ok is True
        assert "Python" in output

    def test_missing_executable_returns_false_not_raise(self):
        ok, _ = probe_executable("definitely-not-a-real-exe-xyz")
        assert ok is False
