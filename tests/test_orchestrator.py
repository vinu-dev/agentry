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
    _is_git_worktree_clean,
    _role_allowed_by_mode,
    _role_has_work,
    _usage_limit_backoff_seconds,
)
from agentry.runtime_control import set_role_runtime_enabled
from agentry.session import read_session
from agentry.workpacket import SelectedPullRequest


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
            assert session["pid"] is None
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


def test_disabled_roles_start_control_thread_but_do_not_spawn(tmp_path: Path):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "tester": AgentConfig(
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
        assert sorted(t.name for t in orch._threads) == ["role-implementer", "role-tester"]

        disabled_log_dir = target_logs_dir(tmp_path) / "tester"
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


def test_runtime_enable_can_start_config_disabled_role(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("agentry.orchestrator.RUNTIME_CONTROL_POLL_SECONDS", 0.2)
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "tester": AgentConfig(
                enabled=False,
                cli=sys.executable,
                args=["-c", "print('runtime enabled role ran')"],
                interval_min=1,
                total_min=1,
                stall_min=1,
                prompt="disabled until runtime enable",
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
        time.sleep(0.5)
        assert not log_dir.exists()

        set_role_runtime_enabled(tmp_path, "tester", True)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if log_dir.is_dir() and any(log_dir.glob("*.log")):
                break
            time.sleep(0.2)

        logs = list(log_dir.glob("*.log"))
        assert logs
        assert "runtime enabled role ran" in logs[0].read_text(encoding="utf-8")
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


def test_researcher_skips_when_design_backlog_guard_is_full(monkeypatch):
    researcher = AgentConfig(
        cli=sys.executable,
        args=["-c", "print('research')"],
        interval_min=60,
        total_min=1,
        stall_min=1,
    )
    target_config = TargetConfig(
        target_repo="test/repo",
        mode="autonomous",
        research={
            "allow_create_issues": True,
            "max_open_ready_for_design": 2,
            "backlog_labels": ["ready-for-design", "needs-risk"],
        },
        agents={"researcher": researcher},
    )
    seen: dict[str, object] = {}

    def fake_count(repo: str, labels: list[str], **kwargs) -> int:
        seen["repo"] = repo
        seen["labels"] = labels
        seen["limit"] = kwargs["limit_per_label"]
        return 2

    monkeypatch.setattr("agentry.orchestrator.count_open_issues_with_labels", fake_count)

    assert not _role_has_work(target_config, "researcher", researcher)
    assert seen == {
        "repo": "test/repo",
        "labels": ["ready-for-design", "needs-risk"],
        "limit": 2,
    }


def test_researcher_runs_when_design_backlog_below_guard(monkeypatch):
    researcher = AgentConfig(
        cli=sys.executable,
        args=["-c", "print('research')"],
        interval_min=60,
        total_min=1,
        stall_min=1,
    )
    target_config = TargetConfig(
        target_repo="test/repo",
        mode="autonomous",
        research={"allow_create_issues": True, "max_open_ready_for_design": 2},
        agents={"researcher": researcher},
    )
    monkeypatch.setattr(
        "agentry.orchestrator.count_open_issues_with_labels",
        lambda repo, labels, **kwargs: 1,
    )

    assert _role_has_work(target_config, "researcher", researcher)


def test_researcher_skips_when_design_backlog_count_fails(monkeypatch):
    researcher = AgentConfig(
        cli=sys.executable,
        args=["-c", "print('research')"],
        interval_min=60,
        total_min=1,
        stall_min=1,
    )
    target_config = TargetConfig(
        target_repo="test/repo",
        mode="autonomous",
        research={"allow_create_issues": True, "max_open_ready_for_design": 2},
        agents={"researcher": researcher},
    )
    monkeypatch.setattr(
        "agentry.orchestrator.count_open_issues_with_labels",
        lambda repo, labels, **kwargs: None,
    )

    assert not _role_has_work(target_config, "researcher", researcher)


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
        lambda repo, label, **kwargs: False,
    )
    monkeypatch.setattr(
        "agentry.orchestrator.count_open_pull_requests",
        lambda repo, **kwargs: 0,
    )

    assert not _role_has_work(target_config, "tester", target_config.agents["tester"])


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
        lambda repo, label, **kwargs: False,
    )

    assert _role_has_work(target_config, "implementer", target_config.agents["implementer"])


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
        lambda repo, label, **kwargs: label == "ready-for-review",
    )

    assert _role_has_work(target_config, "reviewer", target_config.agents["reviewer"])


def test_issue_trigger_blocks_new_pr_creation_when_open_pr_limit_reached(monkeypatch):
    target_config = TargetConfig(
        target_repo="test/repo",
        automation={"max_open_prs": 1, "pr_creation_issue_labels": ["ready-for-test"]},
        agents={
            "tester": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-test"]},
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.orchestrator.count_open_pull_requests",
        lambda repo, **kwargs: 1,
    )
    monkeypatch.setattr(
        "agentry.orchestrator.list_open_issues_with_label",
        lambda repo, label, *, limit: [
            {
                "number": 72,
                "title": "Fresh work",
                "labels": [{"name": "ready-for-test"}],
            }
        ],
    )

    assert not _role_has_work(target_config, "tester", target_config.agents["tester"])


def test_issue_trigger_allows_existing_pr_retry_when_open_pr_limit_reached(monkeypatch):
    target_config = TargetConfig(
        target_repo="test/repo",
        automation={"max_open_prs": 1, "pr_creation_issue_labels": ["ready-for-test"]},
        agents={
            "tester": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-test"]},
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.orchestrator.count_open_pull_requests",
        lambda repo, **kwargs: 3,
    )
    monkeypatch.setattr(
        "agentry.orchestrator.list_open_issues_with_label",
        lambda repo, label, *, limit: [
            {
                "number": 72,
                "title": "Existing PR retry",
                "labels": [{"name": "ready-for-test"}, {"name": "pr-open"}],
            }
        ],
    )

    assert _role_has_work(target_config, "tester", target_config.agents["tester"])


def test_role_trigger_passes_pr_check_gate(monkeypatch):
    target_config = TargetConfig(
        target_repo="test/repo",
        agents={
            "reviewer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
                trigger={
                    "pr_labels": ["ready-for-review"],
                    "pr_check_gate": "settled",
                },
            ),
        },
    )
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        "agentry.orchestrator.has_open_issue_with_label",
        lambda repo, label: False,
    )

    def fake_has_open_pr(repo: str, label: str, **kwargs) -> bool:
        seen["gate"] = kwargs["check_gate"]
        return False

    monkeypatch.setattr("agentry.orchestrator.has_open_pr_with_label", fake_has_open_pr)

    assert not _role_has_work(target_config, "reviewer", target_config.agents["reviewer"])
    assert seen["gate"] == "settled"


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


def test_role_cwd_returns_none_when_existing_worktree_is_dirty(tmp_path: Path):
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

    worktree = orch._role_cwd("implementer")
    assert worktree is not None
    (worktree / "leftover.txt").write_text("partial agent output\n", encoding="utf-8")

    assert not _is_git_worktree_clean(worktree)
    assert orch._role_cwd("implementer") is None


def test_role_cwd_refreshes_existing_worktree_to_origin_main(tmp_path: Path):
    remote, target = _make_remote_backed_repo(tmp_path)
    (target / "README.md").write_text("initial\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "initial")
    _git(target, "push", "-u", "origin", "main")

    orch = Orchestrator(
        target_config=_target_config_with_role("reviewer"),
        target_path=target,
        notifier=DiscordNotifier(webhook_url=None),
    )
    worktree = orch._role_cwd("reviewer")
    assert worktree is not None
    assert not (worktree / "new.txt").exists()

    (target / "new.txt").write_text("from main\n", encoding="utf-8")
    _git(target, "add", "new.txt")
    _git(target, "commit", "-m", "advance main")
    _git(target, "push", "origin", "main")

    refreshed = orch._role_cwd("reviewer")

    assert refreshed == worktree
    assert (worktree / "new.txt").read_text(encoding="utf-8") == "from main\n"
    assert _git_output(worktree, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert remote.exists()


def test_role_cwd_checks_out_selected_pr_head(tmp_path: Path):
    _, target = _make_remote_backed_repo(tmp_path)
    (target / "README.md").write_text("main\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "initial")
    _git(target, "push", "-u", "origin", "main")

    _git(target, "switch", "-c", "feature/pr-doc")
    (target / "pr.txt").write_text("from pr\n", encoding="utf-8")
    _git(target, "add", "pr.txt")
    _git(target, "commit", "-m", "pr change")
    pr_head = _git_output(target, "rev-parse", "HEAD")
    _git(target, "push", "origin", "feature/pr-doc")
    _git(target, "push", "origin", f"{pr_head}:refs/pull/7/head")
    _git(target, "switch", "main")

    orch = Orchestrator(
        target_config=_target_config_with_role("regulatory_reviewer"),
        target_path=target,
        notifier=DiscordNotifier(webhook_url=None),
    )

    worktree = orch._role_cwd(
        "regulatory_reviewer",
        selected_pr=SelectedPullRequest(number=7, head_ref_name="feature/pr-doc"),
    )

    assert worktree is not None
    assert (worktree / "pr.txt").read_text(encoding="utf-8") == "from pr\n"
    assert _git_output(worktree, "rev-parse", "HEAD") == pr_head
    assert _git_output(worktree, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def _make_remote_backed_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    target = tmp_path / "target"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "clone", str(remote), str(target))
    _git(target, "switch", "-c", "main")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Agentry Test")
    return remote, target


def _target_config_with_role(role: str) -> TargetConfig:
    return TargetConfig(
        target_repo="test/repo",
        agents={
            role: AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=60,
                total_min=1,
                stall_min=1,
            )
        },
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
