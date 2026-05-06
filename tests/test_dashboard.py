"""Tests for dashboard status payloads."""

from __future__ import annotations

from pathlib import Path

from agentry.dashboard import build_status_payload
from agentry.runtime_control import set_role_runtime_enabled
from agentry.session import begin_session, update_session


def test_build_status_payload_includes_sessions_logs_and_mode(tmp_path: Path):
    agentry_dir = tmp_path / "agentry"
    agentry_dir.mkdir()
    (agentry_dir / "config.yml").write_text(
        """
target_repo: user/repo
mode: pipeline
agents:
  researcher:
    enabled: true
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "gpt-5.4-mini"]
    interval_min: 60
    total_min: 30
    stall_min: 30
  implementer:
    enabled: true
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "gpt-5.4"]
    interval_min: 5
    total_min: 60
    stall_min: 60
""",
        encoding="utf-8",
    )
    log = tmp_path / "agentry" / "logs" / "implementer" / "123.log"
    log.parent.mkdir(parents=True)
    log.write_text("line one\nline two\n", encoding="utf-8")
    begin_session(
        tmp_path,
        role="implementer",
        log_path=log,
        token_budget=60000,
        mode="pipeline",
    )
    update_session(tmp_path, "implementer", pid=123, tokens_used=42)

    payload = build_status_payload(tmp_path)

    assert payload["target_repo"] == "user/repo"
    assert payload["mode"] == "pipeline"
    roles = {role["role"]: role for role in payload["roles"]}
    assert roles["researcher"]["mode_allowed"] is False
    assert roles["researcher"]["configured_enabled"] is True
    assert roles["researcher"]["effective_enabled"] is True
    assert roles["researcher"]["runtime_override"] is None
    assert roles["implementer"]["mode_allowed"] is True
    assert roles["implementer"]["session"]["pid"] == 123
    assert "line two" in roles["implementer"]["latest_log_tail"]


def test_build_status_payload_reports_runtime_override(tmp_path: Path):
    agentry_dir = tmp_path / "agentry"
    agentry_dir.mkdir()
    (agentry_dir / "config.yml").write_text(
        """
target_repo: user/repo
agents:
  implementer:
    enabled: true
    cli: npx
    interval_min: 5
    total_min: 60
    stall_min: 60
""",
        encoding="utf-8",
    )
    set_role_runtime_enabled(tmp_path, "implementer", False)

    payload = build_status_payload(tmp_path)

    role = payload["roles"][0]
    assert role["role"] == "implementer"
    assert role["configured_enabled"] is True
    assert role["runtime_override"] is False
    assert role["effective_enabled"] is False
