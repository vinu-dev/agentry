"""Lightweight integration test for the orchestrator.

Spawns one role thread with a stub CLI and confirms the loop:
  - reads the per-role prompt OR the framework-generated one
  - spawns the subprocess in the right working directory
  - logs the run inside <target>/.agentry/logs/<role>/
  - sleeps until the shutdown event fires
  - exits cleanly

We don't test the full Discord posting loop here — that's covered in
test_notify.py. We use a no-webhook notifier so events are silently dropped.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_logs_dir, target_worktrees_dir
from agentry.notify import DiscordNotifier
from agentry.orchestrator import (
    USAGE_LIMIT_BACKOFF_FALLBACK_SECONDS,
    Orchestrator,
    _role_allowed_by_mode,
    _role_has_work,
    _usage_limit_backoff_seconds,
)
from agentry.session import read_session


def _make_orchestrator(
    tmp_path: Path,
    *,
    prompt: str | None = None,
    interval_min: int = 1,
    total_min: int = 1,
    stall_min: int = 1,
) -> Orchestrator:
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "tester": AgentConfig(
                cli=sys.executable,
                args=["-c", "print('one iteration done'); import sys; sys.exit(0)"],
                interval_min=interval_min,
                total_min=total_min,
                stall_min=stall_min,
                prompt=prompt,
            ),
        },
    )
    notifier = DiscordNotifier(webhook_url=None, flush_seconds=10)
    notifier.start()
    return Orchestrator(
        target_config=target_config,
        target_path=tmp_path,
        notifier=notifier,
    )


class TestOrchestrator:
    def test_role_loop_runs_one_iteration(self, tmp_path: Path):
        """Start orchestrator, let one iteration complete, then shut down."""
        orch = _make_orchestrator(tmp_path)
        try:
            orch.start()

            # Logs live inside the target — <tmp_path>/.agentry/logs/tester/
            log_dir = target_logs_dir(tmp_path) / "tester"
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if log_dir.is_dir() and any(log_dir.glob("*.log")):
                    break
                time.sleep(0.5)

            assert log_dir.is_dir(), "log dir was not created"
            logs = list(log_dir.glob("*.log"))
            assert logs, "no log file produced after one iteration"
            content = logs[0].read_text(encoding="utf-8")
            assert "one iteration done" in content
            deadline = time.monotonic() + 10.0
            session = None
            while time.monotonic() < deadline:
                session = read_session(tmp_path, "tester")
                if session and session.get("state") == "completed":
                    break
                time.sleep(0.2)
            assert session is not None
            assert session["state"] == "completed"
            assert session["pid"] is not None
        finally:
            orch.shutdown()
            orch.notifier.stop(timeout=2.0)

    def test_uses_per_role_prompt_when_set(self, tmp_path: Path):
        """When AgentConfig.prompt is set, that string is sent to stdin verbatim."""
        prompt_text = "CUSTOM PROMPT FROM CONFIG\n"
        target_config = TargetConfig(
            target_repo="test/repo",
            agents={
                "tester": AgentConfig(
                    cli=sys.executable,
                    args=["-c", "import sys; sys.stdout.write(sys.stdin.read())"],
                    interval_min=60,
                    total_min=1,
                    stall_min=1,
                    prompt=prompt_text,
                ),
            },
        )
        notifier = DiscordNotifier(webhook_url=None, flush_seconds=10)
        notifier.start()
        orch = Orchestrator(
            target_config=target_config,
            target_path=tmp_path,
            notifier=notifier,
        )
        try:
            orch.start()
            log_dir = target_logs_dir(tmp_path) / "tester"
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if log_dir.is_dir() and any(log_dir.glob("*.log")):
                    time.sleep(0.5)
                    break
                time.sleep(0.5)
            logs = list(log_dir.glob("*.log"))
            assert logs
            content = logs[0].read_text(encoding="utf-8")
            assert "CUSTOM PROMPT FROM CONFIG" in content
        finally:
            orch.shutdown()
            orch.notifier.stop(timeout=2.0)

    def test_shutdown_event_stops_threads(self, tmp_path: Path):
        """Calling shutdown() should cause the role loop to exit."""
        orch = _make_orchestrator(tmp_path, interval_min=60)  # long sleep
        try:
            orch.start()
            time.sleep(2.0)
            orch.shutdown()
            for t in orch._threads:
                t.join(timeout=10.0)
        finally:
            orch.notifier.stop(timeout=2.0)


def test_usage_limit_backoff_uses_reported_retry_time(tmp_path: Path):
    log_path = tmp_path / "role.log"
    log_path.write_text(
        "ERROR: You've hit your usage limit. Try again at 2:43 PM.\n",
        encoding="utf-8",
    )

    delay = _usage_limit_backoff_seconds(
        log_path,
        now=datetime(2026, 5, 3, 10, 46, 0),
    )

    assert delay == (3 * 60 + 57) * 60 + 5 * 60


def test_usage_limit_backoff_uses_fallback_without_retry_time(tmp_path: Path):
    log_path = tmp_path / "role.log"
    log_path.write_text("ERROR: You've hit your usage limit.\n", encoding="utf-8")

    assert _usage_limit_backoff_seconds(log_path) == USAGE_LIMIT_BACKOFF_FALLBACK_SECONDS


def test_usage_limit_backoff_ignores_normal_logs(tmp_path: Path):
    log_path = tmp_path / "role.log"
    log_path.write_text("normal run\n", encoding="utf-8")

    assert _usage_limit_backoff_seconds(log_path) is None


def test_disabled_roles_do_not_start_threads(tmp_path: Path):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "researcher": AgentConfig(
                enabled=False,
                cli=sys.executable,
                args=["-c", "print('should not run')"],
                interval_min=1,
                total_min=1,
                stall_min=1,
                prompt="disabled",
            ),
            "implementer": AgentConfig(
                cli=sys.executable,
                args=["-c", "print('enabled role ran')"],
                interval_min=60,
                total_min=1,
                stall_min=1,
                prompt="enabled",
            ),
        },
    )
    notifier = DiscordNotifier(webhook_url=None, flush_seconds=10)
    notifier.start()
    orch = Orchestrator(
        target_config=target_config,
        target_path=tmp_path,
        notifier=notifier,
    )
    try:
        orch.start()
        assert [t.name for t in orch._threads] == ["role-implementer"]

        disabled_log_dir = target_logs_dir(tmp_path) / "researcher"
        enabled_log_dir = target_logs_dir(tmp_path) / "implementer"
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if enabled_log_dir.is_dir() and any(enabled_log_dir.glob("*.log")):
                break
            time.sleep(0.5)

        assert not disabled_log_dir.exists()
        logs = list(enabled_log_dir.glob("*.log"))
        assert logs
        assert "enabled role ran" in logs[0].read_text(encoding="utf-8")
    finally:
        orch.shutdown()
        orch.notifier.stop(timeout=2.0)


def test_manual_mode_starts_no_role_threads(tmp_path: Path):
    target_config = TargetConfig(
        target_repo="test/repo",
        mode="manual",
        agents={
            "implementer": AgentConfig(
                cli=sys.executable,
                args=["-c", "print('should not run')"],
                interval_min=60,
                total_min=1,
                stall_min=1,
            ),
        },
    )
    orch = Orchestrator(
        target_config=target_config,
        target_path=tmp_path,
        notifier=DiscordNotifier(webhook_url=None),
    )

    orch.start()

    assert orch._threads == []


def test_pipeline_mode_blocks_researcher_unless_autonomous():
    researcher = AgentConfig(
        cli=sys.executable,
        args=["-c", "print('research')"],
        interval_min=60,
        total_min=1,
        stall_min=1,
    )
    pipeline_cfg = TargetConfig(
        target_repo="test/repo",
        mode="pipeline",
        agents={"researcher": researcher},
    )
    autonomous_cfg = TargetConfig(
        target_repo="test/repo",
        mode="autonomous",
        research={"allow_create_issues": True},
        agents={"researcher": researcher},
    )

    assert not _role_allowed_by_mode(pipeline_cfg, "researcher")
    assert _role_allowed_by_mode(autonomous_cfg, "researcher")


def test_role_trigger_skips_when_no_matching_github_work(monkeypatch, tmp_path: Path):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "tester": AgentConfig(
                cli=sys.executable,
                args=["-c", "print('should not run')"],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-test"]},
                prompt="gated",
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_issue_with_label",
        lambda repo, label: False,
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_pr_with_label",
        lambda repo, label: False,
    )

    assert not _role_has_work(target_config, target_config.agents["tester"])


def test_role_trigger_runs_when_issue_label_matches(monkeypatch):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "implementer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-implementation", "tests-failed"]},
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_issue_with_label",
        lambda repo, label: label == "tests-failed",
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_pr_with_label",
        lambda repo, label: False,
    )

    assert _role_has_work(target_config, target_config.agents["implementer"])


def test_role_trigger_runs_when_pr_label_matches(monkeypatch):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "reviewer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={"pr_labels": ["ready-for-review"]},
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_issue_with_label",
        lambda repo, label: False,
    )
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_pr_with_label",
        lambda repo, label: label == "ready-for-review",
    )

    assert _role_has_work(target_config, target_config.agents["reviewer"])


def test_role_runs_inside_isolated_git_worktree(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Agentry Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("test target\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    code = (
        "from pathlib import Path; "
        "import os; "
        "print(os.getcwd()); "
        "Path('cwd.txt').write_text(os.getcwd(), encoding='utf-8')"
    )
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "implementer": AgentConfig(
                cli=sys.executable,
                args=["-c", code],
                interval_min=60,
                total_min=1,
                stall_min=1,
                prompt="worktree",
            ),
        },
    )
    notifier = DiscordNotifier(webhook_url=None, flush_seconds=10)
    notifier.start()
    orch = Orchestrator(
        target_config=target_config,
        target_path=tmp_path,
        notifier=notifier,
    )
    try:
        orch.start()
        worktree = target_worktrees_dir(tmp_path) / "implementer"
        marker = worktree / "cwd.txt"
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if marker.is_file():
                break
            time.sleep(0.5)

        assert marker.is_file()
        assert Path(marker.read_text(encoding="utf-8")).resolve() == worktree.resolve()
        assert not (tmp_path / "cwd.txt").exists()
    finally:
        orch.shutdown()
        orch.notifier.stop(timeout=2.0)


def test_role_cwd_returns_none_when_isolated_worktree_cannot_be_created(
    monkeypatch,
    tmp_path: Path,
):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "implementer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
            ),
        },
    )
    orch = Orchestrator(
        target_config=target_config,
        target_path=tmp_path,
        notifier=DiscordNotifier(webhook_url=None),
    )
    monkeypatch.setattr("agentry.orchestrator._is_git_repo", lambda path: path == tmp_path)
    monkeypatch.setattr("agentry.orchestrator._choose_worktree_base_ref", lambda path: "HEAD")

    def fail_worktree_add(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args[0], stderr="nope")

    monkeypatch.setattr("agentry.orchestrator.subprocess.run", fail_worktree_add)

    assert orch._role_cwd("implementer") is None
