"""Tests for role session state and stop safety."""

from __future__ import annotations

from pathlib import Path

from agentry.session import (
    active_session,
    begin_session,
    finish_session,
    parse_tokens_used,
    read_session,
    stop_session,
    update_session,
)
from agentry.supervisor import ExitReason, SupervisedRun


def test_finish_session_records_token_budget(tmp_path: Path):
    log = tmp_path / "role.log"
    begin_session(
        tmp_path,
        role="tester",
        log_path=log,
        token_budget=100,
        mode="pipeline",
    )

    finish_session(
        tmp_path,
        "tester",
        SupervisedRun(
            reason=ExitReason.NORMAL,
            exit_code=0,
            duration_seconds=1.23456,
            stdout_path=log,
            pid=123,
        ),
        tokens_used=120,
        token_budget=100,
    )

    record = read_session(tmp_path, "tester")
    assert record is not None
    assert record["state"] == "completed"
    assert record["tokens_used"] == 120
    assert record["budget_exceeded"] is True
    assert record["duration_seconds"] == 1.235


def test_parse_tokens_used_reads_latest_count(tmp_path: Path):
    log = tmp_path / "out.log"
    log.write_text(
        "first line\n"
        "tokens used 1,234\n"
        "more work\n"
        "tokens used 2,345\n",
        encoding="utf-8",
    )

    assert parse_tokens_used(log) == 2345


def test_active_session_marks_dead_pid_stale(tmp_path: Path, monkeypatch):
    begin_session(
        tmp_path,
        role="architect",
        log_path=tmp_path / "a.log",
        token_budget=None,
        mode="pipeline",
    )
    update_session(tmp_path, "architect", pid=999999)
    monkeypatch.setattr("agentry.session.is_pid_running", lambda pid: False)

    assert active_session(tmp_path, "architect") is None
    record = read_session(tmp_path, "architect")
    assert record is not None
    assert record["state"] == "stale"
    assert record["exit_reason"] == "pid-not-running"


def test_stop_completed_session_does_not_kill_reused_pid(tmp_path: Path, monkeypatch):
    begin_session(
        tmp_path,
        role="reviewer",
        log_path=tmp_path / "r.log",
        token_budget=None,
        mode="pipeline",
    )
    update_session(tmp_path, "reviewer", state="completed", pid=12345)

    def fail_if_called(pid: int) -> bool:
        raise AssertionError(f"should not kill pid {pid}")

    monkeypatch.setattr("agentry.session.kill_pid_tree", fail_if_called)

    assert stop_session(tmp_path, "reviewer") is False
