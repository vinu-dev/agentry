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

import sys
import time
from datetime import datetime
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_logs_dir
from agentry.notify import DiscordNotifier
from agentry.orchestrator import (
    USAGE_LIMIT_BACKOFF_FALLBACK_SECONDS,
    Orchestrator,
    _usage_limit_backoff_seconds,
)


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
