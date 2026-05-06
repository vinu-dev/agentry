"""Runtime operator controls for Agentry roles.

These controls are target-local state, not committed configuration. They let an
operator pause or resume one role while Agentry is running without rewriting the
target's ``agentry/config.yml`` or changing any other role.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentry.config import target_state_dir
from agentry.session import utc_now


@dataclass(frozen=True)
class RoleRuntimeState:
    """Effective enabled state for one role."""

    configured_enabled: bool
    runtime_override: bool | None

    @property
    def effective_enabled(self) -> bool:
        if self.runtime_override is None:
            return self.configured_enabled
        return self.runtime_override

    @property
    def source(self) -> str:
        return "runtime" if self.runtime_override is not None else "config"


def role_controls_path(target_path: Path | str) -> Path:
    """Return the per-target runtime role-control state path."""

    return target_state_dir(target_path) / "role-controls.json"


def read_role_controls(target_path: Path | str) -> dict[str, bool]:
    """Read runtime role overrides.

    Missing or malformed state is treated as no overrides. Runtime control files
    are intentionally recoverable because operators may delete ``agentry/state``.
    """

    path = role_controls_path(target_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    roles = data.get("roles") if isinstance(data, dict) else None
    if not isinstance(roles, dict):
        return {}
    out: dict[str, bool] = {}
    for role, value in roles.items():
        if not isinstance(role, str) or not role:
            continue
        if isinstance(value, dict) and isinstance(value.get("enabled"), bool):
            out[role] = value["enabled"]
        elif isinstance(value, bool):
            out[role] = value
    return out


def role_runtime_state(
    target_path: Path | str,
    role: str,
    *,
    configured_enabled: bool,
) -> RoleRuntimeState:
    """Return the configured/runtime/effective state for ``role``."""

    controls = read_role_controls(target_path)
    return RoleRuntimeState(
        configured_enabled=configured_enabled,
        runtime_override=controls.get(role),
    )


def role_effective_enabled(
    target_path: Path | str,
    role: str,
    *,
    configured_enabled: bool,
) -> bool:
    """Return whether a role may start a new run right now."""

    return role_runtime_state(
        target_path,
        role,
        configured_enabled=configured_enabled,
    ).effective_enabled


def set_role_runtime_enabled(
    target_path: Path | str,
    role: str,
    enabled: bool,
) -> dict[str, bool]:
    """Set a runtime enabled override for one role and return all overrides."""

    path = role_controls_path(target_path)
    data = _read_raw_state(path)
    roles = data.setdefault("roles", {})
    if not isinstance(roles, dict):
        roles = {}
        data["roles"] = roles
    roles[role] = {"enabled": bool(enabled), "updated_at": utc_now()}
    _write_raw_state(path, data)
    return read_role_controls(target_path)


def clear_role_runtime_override(target_path: Path | str, role: str) -> dict[str, bool]:
    """Remove a runtime override so the role falls back to committed config."""

    path = role_controls_path(target_path)
    data = _read_raw_state(path)
    roles = data.get("roles")
    if isinstance(roles, dict):
        roles.pop(role, None)
    _write_raw_state(path, data)
    return read_role_controls(target_path)


def _read_raw_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "roles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "roles": {}}
    if not isinstance(data, dict):
        return {"version": 1, "roles": {}}
    data.setdefault("version", 1)
    data.setdefault("roles", {})
    return data


def _write_raw_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "RoleRuntimeState",
    "clear_role_runtime_override",
    "read_role_controls",
    "role_controls_path",
    "role_effective_enabled",
    "role_runtime_state",
    "set_role_runtime_enabled",
]
