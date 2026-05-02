"""Configuration loading and validation.

Two locations:
  - Per-target ``<target>/.agentry/config.yml``: agent assignments + sensitive
    paths. Committed to the target repo. Logs and runtime state ALSO live in
    ``<target>/.agentry/{logs,state}/`` (gitignored), so each target carries
    its own activity history with it.
  - Per-host ``<host-agentry-dir>/.env``: secrets only (GITHUB_TOKEN,
    optional API keys, optional Discord webhook URL). NEVER committed.

      Windows: ``%USERPROFILE%\\Agentry\\.env``  (visible folder)
      Linux/macOS: ``~/.agentry/.env``           (Unix dot-folder convention)

The framework also ships **bundled defaults** for the standard 6-role roster.
A target that provides nothing falls back to those defaults so operators can
start with zero setup.
"""

from __future__ import annotations

import os
import sys
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------


class AgentConfig(BaseModel):
    """Per-role configuration block in ``.agentry/config.yml``."""

    cli: str = Field(..., min_length=1, description="Binary name or absolute path")
    args: list[str] = Field(default_factory=list, description="Arguments passed before the prompt")
    interval_min: int = Field(..., gt=0, description="Sleep N minutes between subprocess invocations")
    total_min: int = Field(..., gt=0, description="Kill subprocess if it exceeds N minutes total")
    stall_min: int = Field(..., gt=0, description="Kill subprocess if no stdout for N minutes")
    prompt: str | None = Field(
        default=None,
        description=(
            "Optional per-role prompt. If set, this exact text is sent to the LLM CLI "
            "as stdin. If unset, the framework synthesizes a generic prompt from "
            "prompt.GENERIC_PROMPT_TEMPLATE that mentions the parallel-pipeline pattern "
            "and points the agent at docs/ai/roles/<role>.md."
        ),
    )

    @field_validator("interval_min", "total_min", "stall_min")
    @classmethod
    def _reasonable_minutes(cls, v: int, info) -> int:
        # Sanity bounds — catch typos like 1440000.
        if v > 60 * 24 * 7:
            raise ValueError(
                f"{info.field_name}={v} is more than a week of minutes; check for a typo"
            )
        return v


class TargetConfig(BaseModel):
    """Top-level shape of a target repo's ``.agentry/config.yml``."""

    target_repo: str = Field(..., min_length=1, description="GitHub owner/repo (e.g. vinu-dev/rpi-home-monitor)")
    agents: dict[str, AgentConfig] = Field(..., min_length=1)
    sensitive_paths: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Optional rename: {default-label: actual-label-in-this-repo}",
    )

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
# Path resolvers
# -----------------------------------------------------------------------------

DEFAULTS_PACKAGE = "agentry.defaults.standard"


def host_secrets_dir() -> Path:
    """Return the per-user host directory that holds ONLY secrets (.env).

    Windows: ``%USERPROFILE%\\Agentry\\``
    Linux/macOS: ``~/.agentry/``

    This is the only host-level location Agentry uses. Everything else
    (logs, state, target config) lives inside each target repository's
    ``.agentry/`` directory.
    """
    home = Path.home()
    if sys.platform == "win32":
        return home / "Agentry"
    return home / ".agentry"


def host_env_file() -> Path:
    """Path to the operator's secrets file."""
    return host_secrets_dir() / ".env"


def target_state_dir(target_path: Path | str) -> Path:
    """Where runtime state for ``target_path`` lives. Inside the target itself.

    Path is ``<target>/.agentry/state/``. Created on demand by callers.
    Should be in the target's ``.gitignore`` (the bundled defaults already
    ignore ``.agentry/state/`` and ``.agentry/logs/``).
    """
    return Path(target_path) / ".agentry" / "state"


def target_logs_dir(target_path: Path | str) -> Path:
    """Where per-role agent stdout/stderr logs live for ``target_path``."""
    return Path(target_path) / ".agentry" / "logs"


def bundled_default_config_path() -> Path:
    """Path to the bundled standard 6-role config file shipped with the package."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath("config.yml")))


def bundled_default_role_path(role: str) -> Path:
    """Path to the bundled default role rule file for ``role``."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath(f"roles/{role}.md")))


def load_target_config(target_path: Path | str) -> TargetConfig:
    """Load and validate the target repo's `.agentry/config.yml`.

    Falls back to the bundled standard config when the target doesn't have one.
    Callers can detect the fallback via ``(target_path / '.agentry' / 'config.yml').is_file()``.

    Args:
        target_path: Path to the target repository root.

    Raises:
        FileNotFoundError: If ``target_path`` itself doesn't exist.
        ValidationError: If the config is malformed.
    """
    target_root = Path(target_path)
    if not target_root.exists():
        raise FileNotFoundError(f"target path does not exist: {target_root}")

    config_file = target_root / ".agentry" / "config.yml"
    if not config_file.is_file():
        config_file = bundled_default_config_path()

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{config_file}: top-level YAML must be a mapping")

    return TargetConfig.model_validate(raw)


def role_rule_path(target_path: Path, role: str) -> Path:
    """Resolve the rule file path for ``role`` in this target.

    Returns the target's ``docs/ai/roles/<role>.md`` if it exists; otherwise
    the bundled default.
    """
    target_specific = Path(target_path) / "docs" / "ai" / "roles" / f"{role}.md"
    if target_specific.is_file():
        return target_specific
    bundled = bundled_default_role_path(role)
    if Path(str(bundled)).is_file():
        return Path(str(bundled))
    return target_specific


def _opt(v: object) -> Path | None:
    """Tolerate ``~`` and ``$VAR`` in path-typed config fields."""
    if v is None or v == "":
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(v))))


__all__ = [
    "AgentConfig",
    "TargetConfig",
    "ValidationError",
    "bundled_default_config_path",
    "bundled_default_role_path",
    "host_env_file",
    "host_secrets_dir",
    "load_target_config",
    "role_rule_path",
    "target_logs_dir",
    "target_state_dir",
]
