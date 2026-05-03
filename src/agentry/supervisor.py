"""Subprocess supervisor with check-in protocol + cross-platform process-tree kill.

This is the watchdog. It spawns one LLM CLI subprocess and watches it.

There are two operating modes:

  - **Legacy text mode** (default): caller writes ``stdin_input`` once, stdin
    is closed, supervisor reads stdout. On stall (no stdout for ``stall_min``
    minutes) or total timeout (``total_min`` minutes), the subprocess is
    killed. Backward-compatible with ``codex --auto-approve`` and any other
    one-shot CLI.

  - **Stream-JSON check-in mode** (when args include
    ``--input-format=stream-json``): caller's prompt is wrapped as a JSON
    user message, stdin stays open for the whole run, supervisor parses
    stdout JSON events. On stall or total threshold, supervisor sends an
    ``AGENTRY-CHECKIN:`` message via stdin and waits for a STATUS reply
    (``STATUS:WORKING|DONE|BLOCKED|NEEDMORETIME N``). The subprocess is only
    killed if the agent fails to respond — graceful by default, kill is
    last resort.

We also handle:
  - Process tree termination (children of the LLM CLI also die)
  - SIGTERM during the run (graceful shutdown initiated by orchestrator)
  - Subprocess crashes (non-zero exit, signals)
  - stdin closed (some CLIs misbehave if stdin isn't /dev/null)
  - Massive stdout volumes (we read line-by-line, never buffer everything)

Corner cases NOT handled here (deferred):
  - Auto-recovery via process restart inside the same role iteration
  - Subprocess hardening sandboxes (cgroups, AppArmor) — operator's responsibility
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from io import IOBase
from pathlib import Path

logger = logging.getLogger(__name__)


class ExitReason(StrEnum):
    """Why a supervised subprocess exited."""

    NORMAL = "normal"  # exit code 0
    NONZERO = "nonzero"  # exit code != 0 but process exited on its own
    STALLED = "stalled"  # killed because stdout silent for too long
    TIMED_OUT = "timed_out"  # killed because total runtime exceeded
    INTERRUPTED = "interrupted"  # killed by external shutdown event
    SPAWN_FAILED = "spawn_failed"  # subprocess never started (cli not on PATH, etc.)
    REPORTED_DONE = "reported_done"  # streamjson check-in: agent replied STATUS:DONE
    REPORTED_BLOCKED = "reported_blocked"  # streamjson check-in: STATUS:BLOCKED


@dataclass
class SupervisedRun:
    """Result of one supervised subprocess invocation."""

    reason: ExitReason
    exit_code: int | None  # None if subprocess never started or was killed before exit
    duration_seconds: float
    stdout_path: Path | None  # File where stdout was tee'd (None on spawn failure)
    error_detail: str | None = None  # Free-form text for SPAWN_FAILED, etc.


# -----------------------------------------------------------------------------
# Public entrypoint
# -----------------------------------------------------------------------------


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
    checkin_response_seconds: float = 90.0,
    max_extensions: int = 6,
) -> SupervisedRun:
    """Spawn ``cli args`` and watch it.

    Args:
        cli: Binary name (looked up on PATH) or absolute path.
        args: List of arguments to pass to the binary.
        cwd: Working directory for the subprocess.
        env: Environment variables. If None, inherits parent's environ.
        stall_seconds: Threshold for stall detection (no stdout for this long).
        total_seconds: Threshold for total runtime.
        log_path: Append-mode log file for stdout. Parent dir must exist.
        shutdown_event: If set during the run, kill subprocess and return
            with ``ExitReason.INTERRUPTED``.
        stdin_input: Initial prompt for the subprocess. In legacy text mode,
            it is written once and stdin is closed. In stream-JSON mode, it
            is wrapped as a JSON ``user`` message.
        checkin_response_seconds: How long to wait for STATUS reply on
            check-in (stream-JSON mode only).
        max_extensions: Cap on STATUS:NEEDMORETIME extensions (stream-JSON
            mode only). Prevents an agent from extending forever.

    Returns:
        SupervisedRun describing how the subprocess exited.
    """
    if stall_seconds <= 0 or total_seconds <= 0:
        raise ValueError("stall_seconds and total_seconds must be positive")

    log_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_streamjson_mode(args):
        return _supervise_streamjson(
            cli=cli,
            args=args,
            cwd=cwd,
            env=env,
            stall_seconds=stall_seconds,
            total_seconds=total_seconds,
            log_path=log_path,
            shutdown_event=shutdown_event,
            stdin_input=stdin_input,
            checkin_response_seconds=checkin_response_seconds,
            max_extensions=max_extensions,
        )
    return _supervise_legacy(
        cli=cli,
        args=args,
        cwd=cwd,
        env=env,
        stall_seconds=stall_seconds,
        total_seconds=total_seconds,
        log_path=log_path,
        shutdown_event=shutdown_event,
        stdin_input=stdin_input,
    )


# -----------------------------------------------------------------------------
# Legacy text-mode supervisor (existing behavior preserved)
# -----------------------------------------------------------------------------


def _supervise_legacy(
    *,
    cli: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    stall_seconds: float,
    total_seconds: float,
    log_path: Path,
    shutdown_event: threading.Event | None,
    stdin_input: str | None,
) -> SupervisedRun:
    """Legacy path: write stdin_input once, kill on stall/total."""
    start = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    log_file: IOBase | None = None
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        log_file.write(f"\n--- spawn {cli} {args} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

        try:
            proc = _spawn(cli=cli, args=args, cwd=cwd, env=env, keep_stdin=False)
        except (FileNotFoundError, PermissionError) as e:
            return SupervisedRun(
                reason=ExitReason.SPAWN_FAILED,
                exit_code=None,
                duration_seconds=time.monotonic() - start,
                stdout_path=log_path,
                error_detail=f"could not spawn {cli!r}: {e}",
            )

        if stdin_input is not None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(stdin_input)
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        last_output_lock = threading.Lock()
        last_output_at = time.monotonic()

        def reader() -> None:
            nonlocal last_output_at
            assert proc is not None
            try:
                for line in iter(proc.stdout.readline, ""):  # type: ignore[union-attr]
                    if not line:
                        break
                    with last_output_lock:
                        last_output_at = time.monotonic()
                    if log_file is not None and not log_file.closed:
                        log_file.write(line)
            except (ValueError, OSError):
                pass

        reader_thread = threading.Thread(target=reader, daemon=True, name=f"reader-{cli}")
        reader_thread.start()

        while True:
            ret = proc.poll()
            if ret is not None:
                reader_thread.join(timeout=2.0)
                duration = time.monotonic() - start
                return SupervisedRun(
                    reason=ExitReason.NORMAL if ret == 0 else ExitReason.NONZERO,
                    exit_code=ret,
                    duration_seconds=duration,
                    stdout_path=log_path,
                )

            if shutdown_event is not None and shutdown_event.is_set():
                _kill_tree(proc)
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.INTERRUPTED,
                    exit_code=proc.returncode,
                    duration_seconds=time.monotonic() - start,
                    stdout_path=log_path,
                )

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


# -----------------------------------------------------------------------------
# Stream-JSON supervisor with check-in protocol
# -----------------------------------------------------------------------------


_STATUS_RE = re.compile(
    r"STATUS:\s*(WORKING|DONE|BLOCKED|NEEDMORETIME)(?:\s+([^\n\r]*))?",
    re.IGNORECASE,
)

_CHECKIN_PROMPT = (
    "AGENTRY-CHECKIN: status check from orchestrator. "
    "Reply IMMEDIATELY with EXACTLY ONE LINE in one of these forms "
    "(case-insensitive, the FIRST STATUS: line in your reply wins):\n"
    "  STATUS:WORKING\n"
    "  STATUS:DONE\n"
    "  STATUS:BLOCKED <one-line reason>\n"
    "  STATUS:NEEDMORETIME <integer minutes>\n"
    "After the STATUS line you may continue your work normally."
)


def _supervise_streamjson(
    *,
    cli: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    stall_seconds: float,
    total_seconds: float,
    log_path: Path,
    shutdown_event: threading.Event | None,
    stdin_input: str | None,
    checkin_response_seconds: float,
    max_extensions: int,
) -> SupervisedRun:
    """Stream-JSON path: bidirectional protocol, check-in instead of kill."""
    start = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    log_file: IOBase | None = None
    extensions_used = 0
    deadline = start + total_seconds  # mutable: NEEDMORETIME extends this

    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        log_file.write(
            f"\n--- spawn {cli} {args} at {time.strftime('%Y-%m-%d %H:%M:%S')} (streamjson) ---\n"
        )

        try:
            proc = _spawn(cli=cli, args=args, cwd=cwd, env=env, keep_stdin=True)
        except (FileNotFoundError, PermissionError) as e:
            return SupervisedRun(
                reason=ExitReason.SPAWN_FAILED,
                exit_code=None,
                duration_seconds=time.monotonic() - start,
                stdout_path=log_path,
                error_detail=f"could not spawn {cli!r}: {e}",
            )

        # Send the initial prompt as a JSON user message (replaces the legacy
        # one-shot stdin write).
        if stdin_input is not None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(_wrap_user_message(stdin_input))
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

        # Reader thread streams stdout, parses JSON events for assistant text,
        # tracks last activity, accumulates text into a rotating buffer used
        # by check-in handler to find STATUS replies.
        last_event_lock = threading.Lock()
        last_event_at = time.monotonic()
        text_buffer: list[str] = []
        text_buffer_lock = threading.Lock()

        def reader() -> None:
            nonlocal last_event_at
            assert proc is not None
            try:
                for line in iter(proc.stdout.readline, ""):  # type: ignore[union-attr]
                    if not line:
                        break
                    with last_event_lock:
                        last_event_at = time.monotonic()
                    if log_file is not None and not log_file.closed:
                        log_file.write(line)
                    text = _extract_text_from_event(line)
                    if text:
                        with text_buffer_lock:
                            text_buffer.append(text)
                            # Cap buffer at last ~16 KB of assistant text to
                            # keep STATUS-line scans cheap.
                            joined_len = sum(len(s) for s in text_buffer)
                            while joined_len > 16384 and len(text_buffer) > 1:
                                joined_len -= len(text_buffer.pop(0))
            except (ValueError, OSError):
                pass

        reader_thread = threading.Thread(target=reader, daemon=True, name=f"reader-{cli}")
        reader_thread.start()

        while True:
            # Subprocess finished on its own.
            ret = proc.poll()
            if ret is not None:
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.NORMAL if ret == 0 else ExitReason.NONZERO,
                    exit_code=ret,
                    duration_seconds=time.monotonic() - start,
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

            now = time.monotonic()
            with last_event_lock:
                stale_for = now - last_event_at

            # Both thresholds funnel through the same check-in handler. The
            # difference is which one triggered (logged for diagnostics).
            triggered: str | None = None
            if now > deadline:
                triggered = "total"
            elif stale_for > stall_seconds:
                triggered = "stall"

            if triggered is not None:
                if extensions_used >= max_extensions:
                    log_file.write(
                        f"\n--- {triggered} hit, {extensions_used} extensions used (cap), "
                        f"killing ---\n"
                    )
                    _kill_tree(proc)
                    reader_thread.join(timeout=2.0)
                    return SupervisedRun(
                        reason=ExitReason.TIMED_OUT
                        if triggered == "total"
                        else ExitReason.STALLED,
                        exit_code=proc.returncode,
                        duration_seconds=time.monotonic() - start,
                        stdout_path=log_path,
                    )

                log_file.write(
                    f"\n--- {triggered} threshold hit, sending AGENTRY-CHECKIN ---\n"
                )

                action, detail = _do_checkin(
                    proc=proc,
                    text_buffer=text_buffer,
                    text_buffer_lock=text_buffer_lock,
                    last_event_lock=last_event_lock,
                    response_timeout=checkin_response_seconds,
                    log_file=log_file,
                )

                # Reset stall timer on every check-in: the check-in itself
                # produced a fresh response, so silence is broken.
                with last_event_lock:
                    last_event_at = time.monotonic()

                if action == "WORKING":
                    # Agent self-reports progress; give it another stall
                    # window. Total deadline is also nudged slightly so that
                    # WORKING after total_min doesn't spin forever.
                    extensions_used += 1
                    deadline = max(deadline, time.monotonic()) + stall_seconds
                    log_file.write(
                        f"--- check-in: STATUS:WORKING (ext #{extensions_used}); "
                        f"continuing ---\n"
                    )
                    continue

                if action == "NEEDMORETIME":
                    extensions_used += 1
                    extra = max(60.0, min(detail or 0, stall_seconds * 2))
                    deadline = max(deadline, time.monotonic()) + extra
                    log_file.write(
                        f"--- check-in: STATUS:NEEDMORETIME, extending by "
                        f"{int(extra)}s (ext #{extensions_used}) ---\n"
                    )
                    continue

                if action == "DONE":
                    log_file.write("--- check-in: STATUS:DONE; awaiting graceful exit ---\n")
                    # Close stdin so claude finishes its final response and exits.
                    _close_stdin(proc)
                    if _wait_exit(proc, timeout=60.0):
                        reader_thread.join(timeout=2.0)
                        return SupervisedRun(
                            reason=ExitReason.REPORTED_DONE,
                            exit_code=proc.returncode,
                            duration_seconds=time.monotonic() - start,
                            stdout_path=log_path,
                        )
                    log_file.write("--- DONE but no exit in 60s; killing ---\n")
                    _kill_tree(proc)
                    reader_thread.join(timeout=2.0)
                    return SupervisedRun(
                        reason=ExitReason.REPORTED_DONE,
                        exit_code=proc.returncode,
                        duration_seconds=time.monotonic() - start,
                        stdout_path=log_path,
                    )

                if action == "BLOCKED":
                    log_file.write(
                        f"--- check-in: STATUS:BLOCKED ({detail or '?'}); awaiting exit ---\n"
                    )
                    _close_stdin(proc)
                    if _wait_exit(proc, timeout=30.0):
                        reader_thread.join(timeout=2.0)
                        return SupervisedRun(
                            reason=ExitReason.REPORTED_BLOCKED,
                            exit_code=proc.returncode,
                            duration_seconds=time.monotonic() - start,
                            stdout_path=log_path,
                            error_detail=str(detail) if detail else None,
                        )
                    _kill_tree(proc)
                    reader_thread.join(timeout=2.0)
                    return SupervisedRun(
                        reason=ExitReason.REPORTED_BLOCKED,
                        exit_code=proc.returncode,
                        duration_seconds=time.monotonic() - start,
                        stdout_path=log_path,
                        error_detail=str(detail) if detail else None,
                    )

                # action == "NORESPONSE": no STATUS line within timeout. The
                # agent is genuinely hung. Kill.
                log_file.write(
                    f"--- check-in: no STATUS reply in {checkin_response_seconds}s; "
                    f"killing as {triggered} ---\n"
                )
                _kill_tree(proc)
                reader_thread.join(timeout=2.0)
                return SupervisedRun(
                    reason=ExitReason.TIMED_OUT
                    if triggered == "total"
                    else ExitReason.STALLED,
                    exit_code=proc.returncode,
                    duration_seconds=time.monotonic() - start,
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


def _do_checkin(
    *,
    proc: subprocess.Popen[str],
    text_buffer: list[str],
    text_buffer_lock: threading.Lock,
    last_event_lock: threading.Lock,  # unused but kept for signature symmetry
    response_timeout: float,
    log_file: IOBase,
) -> tuple[str, object]:
    """Send AGENTRY-CHECKIN over stdin, wait for STATUS reply.

    Returns (action, detail) where action is one of:
      "WORKING", "DONE", "BLOCKED", "NEEDMORETIME", "NORESPONSE"
    detail is the parsed reason/minutes when relevant, else None.
    """
    # Snapshot buffer length so we only scan NEW text that arrives after
    # the check-in is sent.
    with text_buffer_lock:
        snapshot_len = sum(len(s) for s in text_buffer)

    # Send the check-in message.
    try:
        assert proc.stdin is not None
        proc.stdin.write(_wrap_user_message(_CHECKIN_PROMPT))
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        log_file.write(f"--- check-in stdin write failed: {e} ---\n")
        return ("NORESPONSE", None)

    # Wait for new assistant text containing a STATUS line.
    deadline = time.monotonic() + response_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        with text_buffer_lock:
            full = "".join(text_buffer)
            new_text = full[snapshot_len:]
        match = _STATUS_RE.search(new_text)
        if match:
            verb = match.group(1).upper()
            detail = match.group(2).strip() if match.group(2) else None
            if verb == "NEEDMORETIME":
                # Detail is supposed to be an integer minute count. Fall
                # back to a default if the agent omitted it or wrote prose.
                minutes = _parse_minutes(detail)
                return ("NEEDMORETIME", minutes * 60.0 if minutes else 600.0)
            return (verb, detail)
        time.sleep(0.5)

    return ("NORESPONSE", None)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _is_streamjson_mode(args: list[str]) -> bool:
    """True iff CLI args request claude's stream-json input format."""
    for i, a in enumerate(args):
        if a == "--input-format" and i + 1 < len(args) and args[i + 1] == "stream-json":
            return True
        if a == "--input-format=stream-json":
            return True
    return False


def _wrap_user_message(text: str) -> str:
    """Wrap plain text as a claude stream-json user message line."""
    payload = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }
    return json.dumps(payload) + "\n"


def _extract_text_from_event(line: str) -> str | None:
    """Extract assistant *text* content from a stream-json stdout line.

    Returns None for non-assistant events (system, tool_use, result, etc.)
    or for assistant events that only carry thinking / tool_use blocks.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        evt = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if evt.get("type") != "assistant":
        return None
    msg = evt.get("message") or {}
    content = msg.get("content") or []
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    if not parts:
        return None
    return "\n".join(parts)


def _parse_minutes(s: str | None) -> int | None:
    """Best-effort integer-minutes extraction from STATUS:NEEDMORETIME detail."""
    if not s:
        return None
    m = re.search(r"\d+", s)
    if not m:
        return None
    try:
        return max(1, min(int(m.group(0)), 240))  # cap at 4 h
    except ValueError:
        return None


def _close_stdin(proc: subprocess.Popen[str]) -> None:
    if proc.stdin is None or proc.stdin.closed:
        return
    try:
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass


def _wait_exit(proc: subprocess.Popen[str], *, timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for proc to exit. Return True if exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.2)
    return proc.poll() is not None


# -----------------------------------------------------------------------------
# Spawn + kill
# -----------------------------------------------------------------------------


def _spawn(
    *,
    cli: str,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    keep_stdin: bool,
) -> subprocess.Popen[str]:
    """Cross-platform Popen with sensible defaults for our use case.

    On POSIX, starts the subprocess in its own process group so we can kill
    the whole tree later with ``os.killpg``. On Windows, we let
    CREATE_NEW_PROCESS_GROUP do the same job; ``taskkill /T /F`` handles
    tree-kill on the kill side.

    ``keep_stdin`` controls stdin disposition: True for stream-json mode
    where we want to write multiple messages over the run, False for legacy
    mode where stdin gets one write then close.
    """
    cwd = cwd.resolve()
    full_env = (env if env is not None else os.environ).copy()

    popen_kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": full_env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.PIPE,
        # Force UTF-8 on the pipes. `text=True` alone uses
        # locale.getpreferredencoding(False) which is cp1252 on Windows —
        # that crashes on non-ASCII chars in prompts (arrows, em-dashes,
        # etc.) and on agent stdout. errors="replace" keeps a stray byte
        # from killing the cycle; we'd rather see a `?` than die.
        "encoding": "utf-8",
        "errors": "replace",
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

    # In legacy mode we want stdin to /dev/null/NUL semantics after the one
    # write the caller will perform. Reflecting that here keeps callers
    # honest: caller writes, supervisor closes — matches the prior contract.
    # We don't close it ourselves yet; legacy supervise() does the write+close.
    _ = keep_stdin  # kept for documentation / future tightening

    return proc


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Cross-platform best-effort kill of subprocess and its descendants.

    Tries graceful termination first, then SIGKILL/taskkill /F if the
    process is still alive after a short grace period.
    """
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        try:
            subprocess.run(
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
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except OSError:
                pass

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
