"""Tests for the Agentry CLI."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import agentry.cli as cli_module
from agentry.runtime_control import read_role_controls
from agentry.session import begin_session, update_session


def _write_config(target: Path) -> None:
    agentry_dir = target / "agentry"
    agentry_dir.mkdir()
    (agentry_dir / "config.yml").write_text(
        """
target_repo: user/repo
labels:
  custom-stage: team-custom-stage
agents:
  architect:
    cli: definitely-not-on-path
    interval_min: 5
    total_min: 30
    stall_min: 5
""",
        encoding="utf-8",
    )


def test_doctor_fails_without_token_or_gh_auth(tmp_path: Path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(cli_module, "gh_available", lambda: False)

    result = CliRunner().invoke(cli_module.cli, ["doctor", "--target", str(tmp_path)])

    assert result.exit_code == 2
    assert "GitHub auth unavailable" in result.output


def test_doctor_init_labels_includes_configured_label(tmp_path: Path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setattr(cli_module, "gh_available", lambda: True)
    monkeypatch.setattr(cli_module, "repo_exists", lambda repo: True)
    monkeypatch.setattr(cli_module, "list_labels", lambda repo: set())
    captured = {}

    def fake_init_labels(repo, labels):
        captured.update(labels)
        return {name: True for name in labels}

    monkeypatch.setattr(cli_module, "gh_init_labels", fake_init_labels)

    result = CliRunner().invoke(
        cli_module.cli, ["doctor", "--target", str(tmp_path), "--init-labels"]
    )

    assert result.exit_code == 0
    assert "team-custom-stage" in captured


def test_status_uses_ascii_log_bullets(tmp_path: Path):
    _write_config(tmp_path)
    log_dir = tmp_path / "agentry" / "logs" / "architect"
    log_dir.mkdir(parents=True)
    (log_dir / "123.log").write_text("hello\n", encoding="utf-8")

    result = CliRunner().invoke(cli_module.cli, ["status", "--target", str(tmp_path)])

    assert result.exit_code == 0
    assert "mode:      pipeline" in result.output
    assert "    - 123.log" in result.output
    assert "└" not in result.output


def test_status_shows_session_tokens(tmp_path: Path):
    _write_config(tmp_path)
    log = tmp_path / "agentry" / "logs" / "architect" / "123.log"
    log.parent.mkdir(parents=True)
    log.write_text("hello\n", encoding="utf-8")
    begin_session(
        tmp_path,
        role="architect",
        log_path=log,
        token_budget=25000,
        mode="pipeline",
    )
    update_session(tmp_path, "architect", state="completed", pid=123, tokens_used=42)

    result = CliRunner().invoke(cli_module.cli, ["status", "--target", str(tmp_path)])

    assert result.exit_code == 0
    assert "tokens=42/25000" in result.output
    assert "pid=123" not in result.output


def test_role_disable_updates_runtime_state_without_touching_config(tmp_path: Path):
    _write_config(tmp_path)
    config_path = tmp_path / "agentry" / "config.yml"
    original_config = config_path.read_text(encoding="utf-8")

    result = CliRunner().invoke(
        cli_module.cli,
        ["role", "disable", "--target", str(tmp_path), "architect"],
    )

    assert result.exit_code == 0
    assert "architect: runtime-disabled" in result.output
    assert read_role_controls(tmp_path) == {"architect": False}
    assert config_path.read_text(encoding="utf-8") == original_config

    status = CliRunner().invoke(cli_module.cli, ["status", "--target", str(tmp_path)])
    assert status.exit_code == 0
    assert "architect: runtime-disabled" in status.output


def test_role_enable_can_override_config_disabled_role(tmp_path: Path):
    _write_config(tmp_path)
    config_path = tmp_path / "agentry" / "config.yml"
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(text.replace("  architect:\n", "  architect:\n    enabled: false\n"))

    result = CliRunner().invoke(
        cli_module.cli,
        ["role", "enable", "--target", str(tmp_path), "architect"],
    )

    assert result.exit_code == 0
    assert read_role_controls(tmp_path) == {"architect": True}
    status = CliRunner().invoke(cli_module.cli, ["status", "--target", str(tmp_path)])
    assert "runtime-enabled" in status.output


def test_configure_defaults_updates_config(tmp_path: Path):
    _write_config(tmp_path)

    result = CliRunner().invoke(
        cli_module.cli,
        ["configure", "--target", str(tmp_path), "--defaults"],
    )

    assert result.exit_code == 0
    assert "mode: pipeline" in result.output
    text = (tmp_path / "agentry" / "config.yml").read_text(encoding="utf-8")
    assert "mode: pipeline" in text
    assert "token_budget: 25000" in text


def test_configure_single_flag_preserves_unrelated_settings(tmp_path: Path):
    agentry_dir = tmp_path / "agentry"
    agentry_dir.mkdir()
    (agentry_dir / "config.yml").write_text(
        """
target_repo: user/repo
mode: autonomous
automation:
  auto_merge: true
  stop_when_queue_empty: false
research:
  allow_create_issues: true
agents:
  researcher:
    enabled: true
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "custom"]
    interval_min: 60
    total_min: 30
    stall_min: 30
  release:
    enabled: true
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "release-custom"]
    interval_min: 60
    total_min: 30
    stall_min: 30
  architect:
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "architect-custom"]
    interval_min: 5
    total_min: 30
    stall_min: 5
    token_budget: 999
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli_module.cli,
        ["configure", "--target", str(tmp_path), "--disable-researcher"],
    )

    assert result.exit_code == 0
    text = (agentry_dir / "config.yml").read_text(encoding="utf-8")
    assert "mode: autonomous" in text
    assert "auto_merge: true" in text
    assert "stop_when_queue_empty: false" in text
    assert "allow_create_issues: false" in text
    assert "release:\n    enabled: true" in text
    assert "architect-custom" in text
    assert "token_budget: 999" in text
