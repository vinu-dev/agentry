"""Runtime session state for Agentry roles.

Session files are the small, boring watchdog state that lets humans and the
controller see what is running without asking an LLM. They live in the target
repo under ``agentry/state/sessions/<role>.json`` and are safe to delete when
no Agentry process is running.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentry.config import target_state_dir
from agentry.supervisor import ExitReason, SupervisedRun

TOKEN_RE = re.compile(r"tokens used\s+([0-9][0-9,]*)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sessions_dir(target_path: Path | str) -> Path:
    return target_state_dir(target_path) / "sessions"


def session_path(target_path: Path | str, role: str) -> Path:
    return sessions_dir(target_path) / f"{_safe_role_name(role)}.json"


def begin_session(
    target_path: Path | str,
    *,
    role: str,
    log_path: Path,
    token_budget: int | None,
    mode: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "version": 1,
        "role": role,
        "state": "running",
        "mode": mode,
        "pid": None,
        "started_at": utc_now(),
        "last_output_at": None,
        "finished_at": None,
        "log_path": str(log_path),
        "exit_reason": None,
        "exit_code": None,
        "duration_seconds": None,
        "tokens_used": None,
        "token_budget": token_budget,
        "budget_exceeded": False,
    }
    _write_json(session_path(target_path, role), record)
    return record


def update_session(target_path: Path | str, role: str, **fields: Any) -> dict[str, Any]:
    path = session_path(target_path, role)
    record = read_session(target_path, role) or {"version": 1, "role": role}
    record.update(fields)
    _write_json(path, record)
    return record


def finish_session(
    target_path: Path | str,
    role: str,
    run: SupervisedRun,
    *,
    tokens_used: int | None,
    token_budget: int | None,
) -> dict[str, Any]:
    budget_exceeded = (
        tokens_used is not None and token_budget is not None and tokens_used > token_budget
    )
    state = _state_for_run(run.reason)
    return update_session(
        target_path,
        role,
        state=state,
        finished_at=utc_now(),
        exit_reason=str(run.reason),
        exit_code=run.exit_code,
        duration_seconds=round(run.duration_seconds, 3),
        tokens_used=tokens_used,
        token_budget=token_budget,
        budget_exceeded=budget_exceeded,
    )


def read_session(target_path: Path | str, role: str) -> dict[str, Any] | None:
    path = session_path(target_path, role)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_sessions(target_path: Path | str) -> list[dict[str, Any]]:
    root = sessions_dir(target_path)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def active_session(target_path: Path | str, role: str) -> dict[str, Any] | None:
    record = read_session(target_path, role)
    if not record or record.get("state") != "running":
        return None
    pid = record.get("pid")
    if isinstance(pid, int) and pid > 0:
        if is_pid_running(pid):
            return record
        update_session(
            target_path,
            role,
            state="stale",
            finished_at=utc_now(),
            exit_reason="pid-not-running",
        )
        return None
    # A just-starting session may not have its pid yet.
    return record


def stop_session(target_path: Path | str, role: str) -> bool:
    record = active_session(target_path, role)
    if not record:
        return False
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        update_session(target_path, role, state="stopped", finished_at=utc_now())
        return False
    stopped = kill_pid_tree(pid)
    update_session(
        target_path,
        role,
        state="stopped" if stopped else "stop-failed",
        finished_at=utc_now(),
        exit_reason="operator-stop",
    )
    return stopped


def stop_all_sessions(target_path: Path | str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for record in list_sessions(target_path):
        role = record.get("role")
        if isinstance(role, str) and role:
            results[role] = stop_session(target_path, role)
    return results


def parse_tokens_used(log_path: Path | None) -> int | None:
    if log_path is None or not Path(log_path).is_file():
        return None
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = list(TOKEN_RE.finditer(text))
    if not matches:
        return None
    raw = matches[-1].group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def read_log_tail(log_path: Path | str, *, max_lines: int = 80) -> str:
    path = Path(log_path)
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any(_windows_tasklist_row_has_pid(line, pid) for line in result.stdout.splitlines())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid_tree(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return not is_pid_running(pid)
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return True
    except PermissionError:
        pgid = None

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            return True
        time.sleep(0.1)
    if not is_pid_running(pid):
        return True
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return not is_pid_running(pid)


def _windows_tasklist_row_has_pid(line: str, pid: int) -> bool:
    # CSV row shape is "Image Name","PID",...
    fields = [part.strip().strip('"') for part in line.split(",")]
    return len(fields) > 1 and fields[1] == str(pid)


def _state_for_run(reason: ExitReason) -> str:
    if reason in {ExitReason.NORMAL, ExitReason.REPORTED_DONE}:
        return "completed"
    if reason == ExitReason.REPORTED_BLOCKED:
        return "blocked"
    if reason == ExitReason.INTERRUPTED:
        return "interrupted"
    if reason == ExitReason.SPAWN_FAILED:
        return "spawn-failed"
    if reason in {ExitReason.STALLED, ExitReason.TIMED_OUT}:
        return "stopped"
    return "failed"


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _safe_role_name(role: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", role).strip("-") or "role"


__all__ = [
    "active_session",
    "begin_session",
    "finish_session",
    "is_pid_running",
    "kill_pid_tree",
    "list_sessions",
    "parse_tokens_used",
    "read_log_tail",
    "read_session",
    "session_path",
    "sessions_dir",
    "stop_all_sessions",
    "stop_session",
    "update_session",
    "utc_now",
]
