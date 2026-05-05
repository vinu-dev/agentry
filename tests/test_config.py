"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentry.config import (
    AgentConfig,
    TargetConfig,
    bundled_default_config_path,
    bundled_default_role_path,
    load_target_config,
    role_rule_path,
    target_agentry_dir,
    target_config_file,
    target_env_file,
    target_logs_dir,
    target_state_dir,
    target_worktrees_dir,
)


class TestAgentConfig:
    def test_minimum_required_fields(self):
        cfg = AgentConfig(cli="claude", interval_min=5, total_min=30, stall_min=5)
        assert cfg.cli == "claude"
        assert cfg.args == []
        assert cfg.prompt is None
        assert cfg.enabled is True
        assert cfg.run_on_start is True

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

    def test_max_sessions_is_one_for_now(self):
        with pytest.raises(ValidationError, match="max_sessions must be 1"):
            AgentConfig(
                cli="claude",
                interval_min=5,
                total_min=30,
                stall_min=5,
                max_sessions=2,
            )

    def test_empty_cli_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfig(cli="", interval_min=5, total_min=30, stall_min=5)

    def test_trigger_requires_at_least_one_label_gate(self):
        with pytest.raises(ValidationError, match="trigger must declare"):
            AgentConfig(
                cli="claude",
                interval_min=5,
                total_min=30,
                stall_min=5,
                trigger={},
            )

    def test_trigger_rejects_empty_labels(self):
        with pytest.raises(ValidationError, match="trigger labels cannot be empty"):
            AgentConfig(
                cli="claude",
                interval_min=5,
                total_min=30,
                stall_min=5,
                trigger={"issue_labels": ["ready-for-test", ""]},
            )

    def test_trigger_accepts_issue_and_pr_labels(self):
        cfg = AgentConfig(
            cli="claude",
            interval_min=5,
            total_min=30,
            stall_min=5,
            trigger={
                "issue_labels": ["ready-for-test"],
                "pr_labels": ["ready-for-review"],
            },
        )
        assert cfg.trigger is not None
        assert cfg.trigger.issue_labels == ["ready-for-test"]
        assert cfg.trigger.pr_labels == ["ready-for-review"]
        assert cfg.trigger.pr_check_gate == "none"

    def test_trigger_accepts_pr_check_gate(self):
        cfg = AgentConfig(
            cli="claude",
            interval_min=5,
            total_min=30,
            stall_min=5,
            trigger={
                "pr_labels": ["ready-for-review"],
                "pr_check_gate": "settled",
            },
        )
        assert cfg.trigger is not None
        assert cfg.trigger.pr_check_gate == "settled"

    def test_trigger_rejects_unknown_pr_check_gate(self):
        with pytest.raises(ValidationError):
            AgentConfig(
                cli="claude",
                interval_min=5,
                total_min=30,
                stall_min=5,
                trigger={
                    "pr_labels": ["ready-for-review"],
                    "pr_check_gate": "maybe",
                },
            )


class TestTargetConfig:
    def test_minimum_valid(self):
        cfg = TargetConfig(
            target_repo="user/repo",
            agents={
                "architect": AgentConfig(cli="claude", interval_min=5, total_min=30, stall_min=5),
            },
        )
        assert cfg.target_repo == "user/repo"
        assert "architect" in cfg.agents
        assert cfg.isolate_worktrees is True
        assert cfg.mode == "pipeline"
        assert cfg.automation.auto_merge is False
        assert cfg.research.allow_create_issues is False
        assert cfg.research.backlog_labels == ["ready-for-design"]
        assert cfg.context.work_packets is True
        assert cfg.context.max_packet_bytes == 32_000
        assert cfg.merge_sensitive_paths == []

    def test_mode_validation(self):
        with pytest.raises(ValidationError, match="mode must be"):
            TargetConfig(
                target_repo="user/repo",
                mode="forever",
                agents={
                    "architect": AgentConfig(
                        cli="claude", interval_min=5, total_min=30, stall_min=5
                    ),
                },
            )

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

    def test_bundled_reviewer_documents_agent_approval_fallback(self):
        text = bundled_default_role_path("reviewer").read_text(encoding="utf-8")
        assert "agent-approved" in text
        assert "same account" in text
        assert "CI pending" in text
        assert "ScheduleWakeup" in text
        assert "merge-train-waiting" in text

    def test_bundled_tester_keeps_issue_visible_after_pr_creation(self):
        text = bundled_default_role_path("tester").read_text(encoding="utf-8")
        assert "pr-open" in text
        assert "ready-for-review" in text

    def test_bundled_tester_uses_body_file_for_pr_create(self):
        text = bundled_default_config_path().read_text(encoding="utf-8")
        assert "--body-file" in text
        assert '--body "<see template in tester.md>"' not in text

    def test_bundled_retry_roles_reset_local_feature_branch_from_remote(self):
        text = bundled_default_config_path().read_text(encoding="utf-8")
        reset_command = 'git switch -C "feature/<id>-${slug}" "origin/feature/<id>-${slug}"'
        assert text.count(reset_command) >= 2

    def test_role_rule_path_falls_back_to_bundled(self, tmp_path: Path):
        path = role_rule_path(tmp_path, "architect")
        # tmp_path has no docs/ai/roles/, so fallback kicks in.
        assert path.is_file()
        assert "architect" in path.name


class TestLoadTargetConfig:
    def test_target_with_local_config(self, tmp_path: Path):
        agentry_dir = tmp_path / "agentry"
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
        agentry_dir = tmp_path / "agentry"
        agentry_dir.mkdir()
        (agentry_dir / "config.yml").write_text("- not a mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level YAML must be a mapping"):
            load_target_config(tmp_path)


class TestTargetPaths:
    def test_agentry_dir_is_visible(self, tmp_path: Path):
        # Visible folder, not dot-prefixed.
        assert target_agentry_dir(tmp_path) == tmp_path / "agentry"

    def test_config_file_inside_agentry_dir(self, tmp_path: Path):
        assert target_config_file(tmp_path) == tmp_path / "agentry" / "config.yml"

    def test_env_file_inside_agentry_dir(self, tmp_path: Path):
        assert target_env_file(tmp_path) == tmp_path / "agentry" / ".env"

    def test_state_and_logs_inside_target(self, tmp_path: Path):
        assert target_state_dir(tmp_path) == tmp_path / "agentry" / "state"
        assert target_logs_dir(tmp_path) == tmp_path / "agentry" / "logs"
        assert target_worktrees_dir(tmp_path) == tmp_path / "agentry" / "worktrees"

    def test_paths_resolve_string_inputs(self, tmp_path: Path):
        # Should accept Path or str
        assert target_state_dir(str(tmp_path)).parent == tmp_path / "agentry"
        assert target_logs_dir(str(tmp_path)).parent == tmp_path / "agentry"
