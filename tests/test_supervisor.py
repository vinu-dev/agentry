"""Tests for the subprocess supervisor — the watchdog.

These tests cover the corner cases:
  - normal exit (return code 0 and != 0)
  - stall (no stdout for stall_seconds)
  - total timeout
  - external interrupt (shutdown_event)
  - spawn failure (CLI not on PATH)

Each test uses a real subprocess (Python's own interpreter is always
available) rather than mocking, because the supervisor's correctness
depends on real OS behavior (signals, process trees, stdout pipes).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from agentry.supervisor import ExitReason, supervise


def _run_python(
    *,
    code: str,
    log_path: Path,
    stall_seconds: float = 60.0,
    total_seconds: float = 60.0,
    shutdown_event: threading.Event | None = None,
):
    """Convenience wrapper that runs ``python -c <code>`` under the supervisor."""
    return supervise(
        cli=sys.executable,
        args=["-c", code],
        cwd=log_path.parent,
        env=None,
        stall_seconds=stall_seconds,
        total_seconds=total_seconds,
        log_path=log_path,
        shutdown_event=shutdown_event,
    )


class TestSupervise:
    def test_normal_exit_zero(self, tmp_path: Path):
        log = tmp_path / "out.log"
        run = _run_python(
            code="print('hello'); import sys; sys.exit(0)",
            log_path=log,
        )
        assert run.reason == ExitReason.NORMAL
        assert run.exit_code == 0
        assert log.is_file()
        assert "hello" in log.read_text(encoding="utf-8")

    def test_nonzero_exit(self, tmp_path: Path):
        log = tmp_path / "out.log"
        run = _run_python(
            code="import sys; print('bye'); sys.exit(7)",
            log_path=log,
        )
        assert run.reason == ExitReason.NONZERO
        assert run.exit_code == 7

    def test_stall_kills_subprocess(self, tmp_path: Path):
        """Subprocess produces stdout once, then sleeps forever — should be killed."""
        log = tmp_path / "out.log"
        run = _run_python(
            code="print('still working'); import time; time.sleep(120)",
            log_path=log,
            stall_seconds=2,  # generous enough for CI variability
            total_seconds=60,  # well above stall_seconds
        )
        assert run.reason == ExitReason.STALLED
        # Duration should be at least stall_seconds (subprocess didn't return early).
        assert run.duration_seconds >= 2.0
        # And much less than total_seconds.
        assert run.duration_seconds < 30.0

    def test_total_timeout_kills_chatty_subprocess(self, tmp_path: Path):
        """Subprocess prints continuously but exceeds total_seconds — should still be killed."""
        log = tmp_path / "out.log"
        run = _run_python(
            code=(
                "import time, sys\n"
                "for i in range(60):\n"
                "    print(i, flush=True)\n"
                "    time.sleep(0.5)\n"
            ),
            log_path=log,
            stall_seconds=30,  # never going to trigger
            total_seconds=2,
        )
        assert run.reason == ExitReason.TIMED_OUT
        assert run.duration_seconds >= 2.0
        assert run.duration_seconds < 10.0

    def test_external_interrupt(self, tmp_path: Path):
        """Setting shutdown_event mid-run should kill the subprocess and return INTERRUPTED."""
        log = tmp_path / "out.log"
        ev = threading.Event()

        # Trigger interrupt after 1.5 seconds.
        def trigger():
            time.sleep(1.5)
            ev.set()

        threading.Thread(target=trigger, daemon=True).start()

        run = _run_python(
            code="import time; time.sleep(60)",
            log_path=log,
            stall_seconds=30,
            total_seconds=30,
            shutdown_event=ev,
        )
        assert run.reason == ExitReason.INTERRUPTED
        assert run.duration_seconds < 10.0

    def test_spawn_failure(self, tmp_path: Path):
        """A nonexistent CLI returns SPAWN_FAILED rather than crashing the supervisor."""
        log = tmp_path / "out.log"
        run = supervise(
            cli="absolutely-nonexistent-command-xyz",
            args=[],
            cwd=tmp_path,
            env=None,
            stall_seconds=5,
            total_seconds=5,
            log_path=log,
        )
        assert run.reason == ExitReason.SPAWN_FAILED
        assert run.exit_code is None
        assert run.error_detail is not None

    def test_streamjson_result_event_ends_run(self, tmp_path: Path):
        """A result event marks print-mode completion even while stdin is open."""
        log = tmp_path / "stream.log"
        code = (
            "import json, sys\n"
            "sys.stdin.readline()\n"
            "print(json.dumps({'type':'assistant','message':{'role':'assistant',"
            "'content':[{'type':'text','text':'done'}]}}), flush=True)\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
            "'terminal_reason':'completed'}), flush=True)\n"
            "for _ in sys.stdin:\n"
            "    pass\n"
        )
        started = time.monotonic()
        run = supervise(
            cli=sys.executable,
            args=["-c", code, "--input-format=stream-json"],
            cwd=tmp_path,
            env=None,
            stall_seconds=30,
            total_seconds=30,
            log_path=log,
            stdin_input="hello",
        )

        assert run.reason == ExitReason.NORMAL
        assert run.exit_code == 0
        assert time.monotonic() - started < 10.0
        assert '"type": "result"' in log.read_text(encoding="utf-8")

    def test_streamjson_checkin_extends_when_tool_activity_continues(self, tmp_path: Path):
        """Tool progress during a check-in means the agent is active, not hung."""
        log = tmp_path / "stream-active.log"
        code = (
            "import json, sys, time\n"
            "def emit(obj):\n"
            "    print(json.dumps(obj), flush=True)\n"
            "sys.stdin.readline()\n"
            "emit({'type':'assistant','message':{'role':'assistant',"
            "'content':[{'type':'text','text':'started'}]}})\n"
            "sys.stdin.readline()\n"
            "emit({'type':'system','subtype':'task_progress',"
            "'description':'tool still running'})\n"
            "time.sleep(0.2)\n"
            "emit({'type':'result','subtype':'success','is_error':False,"
            "'terminal_reason':'completed'})\n"
            "for _ in sys.stdin:\n"
            "    pass\n"
        )

        run = supervise(
            cli=sys.executable,
            args=["-c", code, "--input-format=stream-json"],
            cwd=tmp_path,
            env=None,
            stall_seconds=30,
            total_seconds=0.5,
            log_path=log,
            stdin_input="hello",
            checkin_response_seconds=1.0,
        )

        text = log.read_text(encoding="utf-8")
        assert run.reason == ExitReason.NORMAL
        assert run.exit_code == 0
        assert "tool still running" in text
        assert "no STATUS reply" not in text

    def test_invalid_timeouts_raise(self, tmp_path: Path):
        log = tmp_path / "out.log"
        with pytest.raises(ValueError):
            supervise(
                cli=sys.executable,
                args=["-c", "pass"],
                cwd=tmp_path,
                env=None,
                stall_seconds=0,
                total_seconds=5,
                log_path=log,
            )

    def test_log_path_parent_is_created(self, tmp_path: Path):
        """The supervisor should mkdir the log file's parent if needed."""
        log = tmp_path / "deeply" / "nested" / "out.log"
        run = _run_python(code="print('ok')", log_path=log)
        assert run.reason == ExitReason.NORMAL
        assert log.is_file()
