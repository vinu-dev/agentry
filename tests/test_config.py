"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentry.config import (
    AgentConfig,
    HostConfig,
    TargetConfig,
    bundled_default_config_path,
    bundled_default_role_path,
    load_target_config,
    role_rule_path,
)


class TestAgentConfig:
    def test_minimum_required_fields(self):
        cfg = AgentConfig(cli="claude", interval_min=5, total_min=30, stall_min=5)
        assert cfg.cli == "claude"
        assert cfg.args == []
        assert cfg.prompt is None

    def test_prompt_is_optional(self):
        cfg = AgentConfig(
            cli="claude",
            interval_min=5,
            total_min=30,
            stall_min=5,
            prompt="You are X. Read X.md.",
        )
        assert cfg.prompt == "You are X. Read X.md."

    def test_negative_timeouts_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(cli="claude", interval_min=-1, total_min=30, stall_min=5)
        with pytest.raises(ValidationError):
            AgentConfig(cli="claude", interval_min=5, total_min=0, stall_min=5)

    def test_unreasonable_minutes_rejected(self):
        with pytest.raises(ValidationError, match="more than a week"):
            AgentConfig(cli="claude", interval_min=10081, total_min=30, stall_min=5)

    def test_empty_cli_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(cli="", interval_min=5, total_min=30, stall_min=5)


class TestTargetConfig:
    def test_minimum_valid(self):
        cfg = TargetConfig(
            target_repo="user/repo",
            agents={
                "architect": AgentConfig(
                    cli="claude", interval_min=5, total_min=30, stall_min=5
                ),
            },
        )
        assert cfg.target_repo == "user/repo"
        assert "architect" in cfg.agents

    def test_zero_agents_rejected(self):
        with pytest.raises(ValidationError):
            TargetConfig(target_repo="user/repo", agents={})

    def test_role_name_with_spaces_rejected(self):
        with pytest.raises(ValidationError):
            TargetConfig(
                target_repo="user/repo",
                agents={
                    "bad name": AgentConfig(
                        cli="claude", interval_min=5, total_min=30, stall_min=5
                    ),
                },
            )

    def test_role_name_with_slash_rejected(self):
        with pytest.raises(ValidationError):
            TargetConfig(
                target_repo="user/repo",
                agents={
                    "skynet/architect": AgentConfig(
                        cli="claude", interval_min=5, total_min=30, stall_min=5
                    ),
                },
            )


class TestBundledDefaults:
    def test_bundled_config_exists(self):
        p = bundled_default_config_path()
        assert p.is_file(), f"bundled config missing at {p}"

    def test_bundled_config_loads_as_valid_target_config(self, tmp_path: Path):
        """The bundled defaults must be a valid TargetConfig (typo guard)."""
        cfg = load_target_config(tmp_path)
        # tmp_path has no .agentry/, so we get the bundled fallback.
        assert len(cfg.agents) >= 5
        assert all(role in cfg.agents for role in ("researcher", "architect", "implementer"))

    def test_bundled_role_files_exist(self):
        for role in ("researcher", "architect", "implementer", "tester", "reviewer", "release"):
            p = bundled_default_role_path(role)
            assert p.is_file(), f"bundled rule file missing for {role} at {p}"

    def test_role_rule_path_falls_back_to_bundled(self, tmp_path: Path):
        path = role_rule_path(tmp_path, "architect")
        # tmp_path has no docs/ai/roles/, so fallback kicks in.
        assert path.is_file()
        assert "architect" in path.name


class TestLoadTargetConfig:
    def test_target_with_local_config(self, tmp_path: Path):
        agentry_dir = tmp_path / ".agentry"
        agentry_dir.mkdir()
        (agentry_dir / "config.yml").write_text(
            """
target_repo: user/myrepo
agents:
  architect:
    cli: claude
    interval_min: 5
    total_min: 30
    stall_min: 5
""",
            encoding="utf-8",
        )
        cfg = load_target_config(tmp_path)
        assert cfg.target_repo == "user/myrepo"
        assert "architect" in cfg.agents

    def test_target_path_must_exist(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_target_config(tmp_path / "does-not-exist")

    def test_malformed_yaml_rejected(self, tmp_path: Path):
        agentry_dir = tmp_path / ".agentry"
        agentry_dir.mkdir()
        (agentry_dir / "config.yml").write_text("- not a mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level YAML must be a mapping"):
            load_target_config(tmp_path)


class TestHostConfig:
    def test_defaults_when_field_blank(self):
        cfg = HostConfig(state_dir=Path("/tmp/agentry-state"))
        assert cfg.github_token_env == "GITHUB_TOKEN"
        assert cfg.discord_webhook_env == "DISCORD_WEBHOOK_URL"
        assert cfg.batch_notify_seconds == 60
