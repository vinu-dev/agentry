"""Tests for the Agentry CLI."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import agentry.cli as cli_module


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
    assert "    - 123.log" in result.output
    assert "└" not in result.output
