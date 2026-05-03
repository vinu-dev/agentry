"""Configuration loading and validation.

Everything Agentry uses lives INSIDE the target repository — gtest-style.

Per target:
  <target>/agentry/config.yml          agent assignments, prompts, sensitive paths (committed)
  <target>/agentry/.env                secrets — GITHUB_TOKEN etc.        (gitignored)
  <target>/agentry/logs/               per-role agent stdout              (gitignored)
  <target>/agentry/state/              runtime state                      (gitignored)
  <target>/agentry/.venv/              local Python venv with agentry     (gitignored)

  <target>/docs/ai/roles/<role>.md     project-specific role rule files   (committed)

There is no host-level Agentry directory. Each target carries everything
it needs (and brings its own Python venv with a pinned-ish agentry version)
when you clone it to a new machine. The machine itself only needs Python
and the LLM CLIs (claude / codex), installed once via scripts/install-deps.

The framework also ships **bundled defaults** for the standard 6-role roster.
A target that provides nothing falls back to those defaults.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------


class AgentTriggerConfig(BaseModel):
    """Cheap preflight gates checked before starting an LLM role."""

    issue_labels: list[str] = Field(
        default_factory=list,
        description="Run only when an open issue has at least one of these labels.",
    )
    pr_labels: list[str] = Field(
        default_factory=list,
        description="Run only when an open pull request has at least one of these labels.",
    )

    @field_validator("issue_labels", "pr_labels")
    @classmethod
    def _non_empty_labels(cls, v: list[str]) -> list[str]:
        cleaned = [label.strip() for label in v if label.strip()]
        if len(cleaned) != len(v):
            raise ValueError("trigger labels cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def _at_least_one_gate(self) -> AgentTriggerConfig:
        if not self.issue_labels and not self.pr_labels:
            raise ValueError("trigger must declare issue_labels or pr_labels")
        return self


class AgentConfig(BaseModel):
    """Per-role configuration block in ``agentry/config.yml``."""

    enabled: bool = Field(
        default=True,
        description="When false, Agentry does not start or validate this role.",
    )
    cli: str = Field(..., min_length=1, description="Binary name or absolute path")
    args: list[str] = Field(default_factory=list, description="Arguments passed before the prompt")
    interval_min: int = Field(
        ..., gt=0, description="Sleep N minutes between subprocess invocations"
    )
    run_on_start: bool = Field(
        default=True,
        description="When false, wait interval_min before the first run after startup.",
    )
    total_min: int = Field(..., gt=0, description="Kill subprocess if it exceeds N minutes total")
    stall_min: int = Field(..., gt=0, description="Kill subprocess if no stdout for N minutes")
    trigger: AgentTriggerConfig | None = Field(
        default=None,
        description="Optional cheap GitHub gate; if no matching work exists, skip the LLM run.",
    )
    prompt: str | None = Field(
        default=None,
        description=(
            "Optional per-role prompt sent to the LLM CLI as stdin. If unset, the "
            "framework synthesizes a generic prompt from prompt.GENERIC_PROMPT_TEMPLATE."
        ),
    )

    @field_validator("interval_min", "total_min", "stall_min")
    @classmethod
    def _reasonable_minutes(cls, v: int, info) -> int:
        if v > 60 * 24 * 7:
            raise ValueError(
                f"{info.field_name}={v} is more than a week of minutes; check for a typo"
            )
        return v


class TargetConfig(BaseModel):
    """Top-level shape of ``<target>/agentry/config.yml``."""

    target_repo: str = Field(..., min_length=1)
    agents: dict[str, AgentConfig] = Field(..., min_length=1)
    sensitive_paths: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("agents")
    @classmethod
    def _at_least_one_agent(cls, v: dict[str, AgentConfig]) -> dict[str, AgentConfig]:
        if not v:
            raise ValueError("agents must contain at least one role")
        for role_name in v:
            if not role_name or " " in role_name or "/" in role_name:
                raise ValueError(f"invalid role name: {role_name!r}")
        return v


# -----------------------------------------------------------------------------
# Path resolvers — all per-target now (no host directory)
# -----------------------------------------------------------------------------

DEFAULTS_PACKAGE = "agentry.defaults.standard"


def target_agentry_dir(target_path: Path | str) -> Path:
    """``<target>/agentry/`` — visible folder, gtest-style."""
    return Path(target_path) / "agentry"


def target_config_file(target_path: Path | str) -> Path:
    """``<target>/agentry/config.yml``."""
    return target_agentry_dir(target_path) / "config.yml"


def target_env_file(target_path: Path | str) -> Path:
    """``<target>/agentry/.env`` — secrets file, gitignored."""
    return target_agentry_dir(target_path) / ".env"


def target_logs_dir(target_path: Path | str) -> Path:
    """``<target>/agentry/logs/`` — per-role agent stdout."""
    return target_agentry_dir(target_path) / "logs"


def target_state_dir(target_path: Path | str) -> Path:
    """``<target>/agentry/state/`` — runtime state."""
    return target_agentry_dir(target_path) / "state"


def bundled_default_config_path() -> Path:
    """Bundled standard config.yml shipped with the package."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath("config.yml")))


def bundled_default_role_path(role: str) -> Path:
    """Bundled default role rule file for ``role``."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath(f"roles/{role}.md")))


def load_target_config(target_path: Path | str) -> TargetConfig:
    """Load and validate ``<target>/agentry/config.yml``.

    Falls back to the bundled standard config if the target doesn't have one.
    """
    target_root = Path(target_path)
    if not target_root.exists():
        raise FileNotFoundError(f"target path does not exist: {target_root}")

    config_file = target_config_file(target_root)
    if not config_file.is_file():
        config_file = bundled_default_config_path()

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{config_file}: top-level YAML must be a mapping")

    return TargetConfig.model_validate(raw)


def role_rule_path(target_path: Path | str, role: str) -> Path:
    """Resolve the rule file path for ``role`` in this target.

    Looks at ``<target>/docs/ai/roles/<role>.md`` first; falls back to the
    bundled default. Rule files live in the host repo's standard location
    (``docs/ai/roles/``), not inside the ``agentry/`` folder.
    """
    target_specific = Path(target_path) / "docs" / "ai" / "roles" / f"{role}.md"
    if target_specific.is_file():
        return target_specific
    bundled = bundled_default_role_path(role)
    if Path(str(bundled)).is_file():
        return Path(str(bundled))
    return target_specific


def load_target_env(target_path: Path | str) -> None:
    """Load ``<target>/agentry/.env`` into os.environ.

    Idempotent and silent. Existing env vars are NOT overwritten — explicit
    shell exports take precedence.
    """
    env_path = target_env_file(target_path)
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


__all__ = [
    "AgentConfig",
    "TargetConfig",
    "ValidationError",
    "bundled_default_config_path",
    "bundled_default_role_path",
    "load_target_config",
    "load_target_env",
    "role_rule_path",
    "target_agentry_dir",
    "target_config_file",
    "target_env_file",
    "target_logs_dir",
    "target_state_dir",
]
