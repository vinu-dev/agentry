"""Subprocess supervisor with dual timeout + cross-platform process-tree kill.

This is the watchdog. It spawns one LLM CLI subprocess and watches it for two
failure modes:

  - **Stall**: subprocess produces no stdout for ``stall_min`` minutes. We
    interpret silence as "stuck" — the agent is not making progress and we
    can't tell why, so kill it and let the next interval respawn.

  - **Total timeout**: subprocess runs longer than ``total_min`` minutes.
    Even if it's emitting stdout, runaway loops are bounded by this cap.

We also handle:
  - Process tree termination (children of the LLM CLI also die)
  - SIGTERM during the run (graceful shutdown initiated by orchestrator)
  - Subprocess crashes (non-zero exit, signals)
  - stdin closed (some CLIs misbehave if stdin isn't /dev/null)
  - Massive stdout volumes (we read line-by-line, never buffer everything)

Corner cases NOT handled here (deferred):
  - Babysitter LLM that watches stdout for "waiting for input" patterns (v0.2)
  - Auto-recovery via process restart inside the same role iteration
  - Subprocess hardening sandboxes (cgroups, AppArmor) — operator's responsibility
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from io import IOBase
from pathlib import Path


class ExitReason(str, Enum):
    """Why a supervised subprocess exited."""

    NORMAL = "normal"  # exit code 0
    NONZERO = "nonzero"  # exit code != 0 but process exited on its own
    STALLED = "stalled"  # killed because stdout silent for too long
    TIMED_OUT = "timed_out"  # killed because total runtime exceeded
    INTERRUPTED = "interrupted"  # killed by external shutdown event
    SPAWN_FAILED = "spawn_failed"  # subprocess never started (cli not on PATH, etc.)


@dataclass
class SupervisedRun:
    """Result of one supervised subprocess invocation."""

    reason: ExitReason
    exit_code: int | None  # None if subprocess never started or was killed before exit
    duration_seconds: float
    stdout_path: Path | None  # File where stdout was tee'd (None on spawn failure)
    error_detail: str | None = None  # Free-form text for SPAWN_FAILED, etc.


def supervise(
    *,
    cli: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    stall_seconds: float,
    total_seconds: float,
    log_path: Path,
    shutdown_event: threading.Event | None = None,
    stdin_input: str | None = None,
) -> SupervisedRun:
    """Spawn ``cli args`` and watch it.

    Reads stdout line-by-line, writing each line to ``log_path``. Tracks the
    timestamp of the last line. If the gap exceeds ``stall_seconds`` or the
    total runtime exceeds ``total_seconds``, kills the subprocess and its
    children, then returns.

    Args:
        cli: Binary name (looked up on PATH) or absolute path.
        args: List of arguments to pass to the binary.
        cwd: Working directory for the subprocess.
        env: Environment variables. If None, inherits parent's environ.
        stall_seconds: Kill if no stdout for this many seconds.
        total_seconds: Kill if total runtime exceeds this.
        log_path: Append-mode log file for stdout. Parent dir must exist.
        shutdown_event: If set during the run, kill subprocess and return
            with ``ExitReason.INTERRUPTED``.
        stdin_input: Optional string to write to subprocess stdin once at start;
            stdin is then closed. If None, stdin is /dev/null (or NUL on
            Windows).

    Returns:
        SupervisedRun describing how the subprocess exited.
    """
    if stall_seconds <= 0 or total_seconds <= 0:
        raise ValueError("stall_seconds and total_seconds must be positive")

    log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    log_file: IOBase | None = None
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        log_file.write(f"\n--- spawn {cli} {args} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

        try:
            proc = _spawn(cli=cli, args=args, cwd=cwd, env=env, stdin_input=stdin_input)
        except (FileNotFoundError, PermissionError) as e:
            return SupervisedRun(
                reason=ExitReason.SPAWN_FAILED,
                exit_code=None,
                duration_seconds=time.monotonic() - start,
                stdout_path=log_path,
                error_detail=f"could not spawn {cli!r}: {e}",
            )

        # Reader thread streams stdout to the log file and updates last_output.
        last_output_lock = threading.Lock()
        last_output_at = time.monotonic()

        def reader() -> None:
            nonlocal last_output_at
            assert proc is not None  # noqa: S101
            try:
                for line in iter(proc.stdout.readline, ""):  # type: ignore[union-attr]
                    if not line:
                        break
                    with last_output_lock:
                        last_output_at = time.monotonic()
                    if log_file is not None and not log_file.closed:
                        log_file.write(line)
            except (ValueError, OSError):
                # Stdout closed mid-read; happens during kill.
                pass

        reader_thread = threading.Thread(target=reader, daemon=True, name=f"reader-{cli}")
        reader_thread.start()

        while True:
            # Subprocess finished on its own.
            ret = proc.poll()
            if ret is not None:
                # Drain reader briefly before returning.
                reader_thread.join(timeout=2.0)
                duration = time.monotonic() - start
                return SupervisedRun(
                    reason=ExitReason.NORMAL if ret == 0 else ExitReason.NONZERO,
                    exit_code=ret,
                    duration_seconds=duration,
                    stdout_path=log_path,
                )

            # External shutdown.
            if shutdown_event is not None and shutdown_event.is_set():
                _kill_tree(proc)
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.INTERRUPTED,
                    exit_code=proc.returncode,
                    duration_seconds=time.monotonic() - start,
                    stdout_path=log_path,
                )

            # Total timeout.
            now = time.monotonic()
            if now - start > total_seconds:
                _kill_tree(proc)
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.TIMED_OUT,
                    exit_code=proc.returncode,
                    duration_seconds=now - start,
                    stdout_path=log_path,
                )

            # Stall.
            with last_output_lock:
                stale_for = now - last_output_at
            if stale_for > stall_seconds:
                _kill_tree(proc)
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.STALLED,
                    exit_code=proc.returncode,
                    duration_seconds=now - start,
                    stdout_path=log_path,
                )

            time.sleep(1.0)

    finally:
        if log_file is not None and not log_file.closed:
            try:
                log_file.flush()
                log_file.close()
            except OSError:
                pass


def _spawn(
    *,
    cli: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    stdin_input: str | None,
) -> subprocess.Popen[str]:
    """Cross-platform Popen with sensible defaults for our use case.

    On POSIX, starts the subprocess in its own process group so we can kill
    the whole tree later with ``os.killpg``. On Windows, we let CREATE_NEW_PROCESS_GROUP
    do the same job; ``taskkill /T /F`` handles tree-kill on the kill side.
    """
    cwd = cwd.resolve()
    full_env = (env if env is not None else os.environ).copy()

    popen_kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": full_env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.PIPE if stdin_input is not None else subprocess.DEVNULL,
        "text": True,
        "bufsize": 1,  # line-buffered
        "close_fds": True,
    }

    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        popen_kwargs["start_new_session"] = True  # detach from caller's process group

    # Resolve cli via PATH so Windows finds .cmd / .bat wrappers (npm puts
    # claude.cmd / codex.cmd on PATH, but Python's Popen won't auto-append
    # .cmd to a bare 'claude'). On POSIX this is a no-op when cli is already
    # an absolute path or has been resolved.
    resolved_cli = shutil.which(cli) or cli

    proc: subprocess.Popen[str] = subprocess.Popen(  # type: ignore[call-overload]
        [resolved_cli, *args], **popen_kwargs
    )

    if stdin_input is not None:
        try:
            assert proc.stdin is not None  # noqa: S101
            proc.stdin.write(stdin_input)
            proc.stdin.flush()
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            # Subprocess may have closed stdin already; not fatal.
            pass

    return proc


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Cross-platform best-effort kill of subprocess and its descendants.

    Tries graceful termination first, then SIGKILL/taskkill /F if the
    process is still alive after a short grace period.
    """
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        # taskkill walks the process tree.
        try:
            subprocess.run(  # noqa: S603 — well-known executable
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        # POSIX: SIGTERM the process group, wait briefly, then SIGKILL.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except OSError:
                pass

        # Grace period for graceful exit.
        deadline = time.monotonic() + 5.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)

        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except OSError:
                    pass


__all__ = ["ExitReason", "SupervisedRun", "supervise"]
