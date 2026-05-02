"""Configuration loading and validation.

Two layers:
  - Per-target ``.agentry/config.yml`` in the target repository
  - Per-host ``pipeline.local.toml`` in ``~/.agentry/``

The framework also ships **bundled defaults** for the standard 6-role roster.
A target that provides nothing falls back to those defaults so operators can
start with zero setup.
"""

from __future__ import annotations

import os
import tomllib
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from platformdirs import user_config_dir


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
            "as stdin (or wrapped in args, depending on the CLI). If unset, the framework "
            "synthesizes a generic prompt from prompt.GENERIC_PROMPT_TEMPLATE that mentions "
            "the parallel-pipeline pattern and points the agent at docs/ai/roles/<role>.md. "
            "Most operators can leave this unset; override only when a CLI needs special "
            "preamble or when you want very targeted instructions in the prompt itself."
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


class HostConfig(BaseModel):
    """Per-host ``pipeline.local.toml`` shape."""

    state_dir: Path = Field(..., description="Where the daemon writes runtime state and logs")
    env_file: Path | None = Field(default=None, description="Optional path to a .env file")
    github_token_env: str = Field(default="GITHUB_TOKEN")
    discord_webhook_env: str = Field(default="DISCORD_WEBHOOK_URL")
    batch_notify_seconds: int = Field(default=60, gt=0)


# -----------------------------------------------------------------------------
# Bundled defaults
# -----------------------------------------------------------------------------

DEFAULTS_PACKAGE = "agentry.defaults.standard"


def bundled_default_config_path() -> Path:
    """Path to the bundled standard 6-role config file shipped with the package."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath("config.yml")))


def bundled_default_role_path(role: str) -> Path:
    """Path to the bundled default role rule file for ``role``."""
    return Path(str(files(DEFAULTS_PACKAGE).joinpath(f"roles/{role}.md")))


def load_target_config(target_path: Path | str) -> TargetConfig:
    """Load and validate the target repo's `.agentry/config.yml`.

    Falls back to the bundled standard config when the target doesn't have one.
    The returned object always has ``target_repo`` reflecting the bundled
    default's placeholder value if a fallback was used; callers should
    override or refuse to dispatch when ``target_repo`` looks unset.

    Args:
        target_path: Path to the target repository root (the dir containing
            ``.agentry/`` if present).

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


def load_host_config(path: Path | str | None = None) -> HostConfig:
    """Load and validate the per-host ``pipeline.local.toml``.

    When ``path`` is None, looks for ``<user_config_dir>/agentry/pipeline.local.toml``.
    Falls back to in-memory defaults if the file doesn't exist.
    """
    if path is None:
        host_path = Path(user_config_dir("agentry", appauthor=False)) / "pipeline.local.toml"
    else:
        host_path = Path(path)

    if not host_path.is_file():
        # Defaults — operator can run with no config file at all.
        return HostConfig(
            state_dir=Path(user_config_dir("agentry", appauthor=False)) / "state",
        )

    with host_path.open("rb") as f:
        raw = tomllib.load(f)

    flat = {
        "state_dir": _opt(raw.get("host", {}).get("state_dir")),
        "env_file": _opt(raw.get("host", {}).get("env_file")),
        "github_token_env": raw.get("github", {}).get("token_env", "GITHUB_TOKEN"),
        "discord_webhook_env": raw.get("notification", {}).get(
            "discord_webhook_env", "DISCORD_WEBHOOK_URL"
        ),
        "batch_notify_seconds": raw.get("orchestrator", {}).get("batch_notify_seconds", 60),
    }
    flat = {k: v for k, v in flat.items() if v is not None}
    if "state_dir" not in flat:
        flat["state_dir"] = (
            Path(user_config_dir("agentry", appauthor=False)) / "state"
        )
    return HostConfig.model_validate(flat)


def _opt(v: object) -> Path | None:
    """Tolerate ``~`` and ``$VAR`` in path-typed config fields."""
    if v is None or v == "":
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(v))))


def role_rule_path(target_path: Path, role: str) -> Path:
    """Resolve the rule file path for ``role`` in this target.

    Returns the target's ``docs/ai/roles/<role>.md`` if it exists; otherwise
    the bundled default. Callers can pass the result to the LLM as
    "read this file."
    """
    target_specific = Path(target_path) / "docs" / "ai" / "roles" / f"{role}.md"
    if target_specific.is_file():
        return target_specific
    bundled = bundled_default_role_path(role)
    if Path(str(bundled)).is_file():
        return Path(str(bundled))
    # Neither exists — return the target path so the agent can fail loudly.
    return target_specific


__all__ = [
    "AgentConfig",
    "HostConfig",
    "TargetConfig",
    "ValidationError",
    "bundled_default_config_path",
    "bundled_default_role_path",
    "load_host_config",
    "load_target_config",
    "role_rule_path",
]
