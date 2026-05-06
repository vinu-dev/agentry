"""Tests for runtime role controls."""

from __future__ import annotations

import json
from pathlib import Path

from agentry.runtime_control import (
    clear_role_runtime_override,
    read_role_controls,
    role_controls_path,
    role_effective_enabled,
    role_runtime_state,
    set_role_runtime_enabled,
)


def test_runtime_controls_default_to_config(tmp_path: Path):
    state = role_runtime_state(tmp_path, "researcher", configured_enabled=True)

    assert state.configured_enabled is True
    assert state.runtime_override is None
    assert state.effective_enabled is True
    assert state.source == "config"


def test_set_and_clear_role_runtime_enabled(tmp_path: Path):
    set_role_runtime_enabled(tmp_path, "researcher", False)

    assert read_role_controls(tmp_path) == {"researcher": False}
    assert not role_effective_enabled(tmp_path, "researcher", configured_enabled=True)
    raw = json.loads(role_controls_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["roles"]["researcher"]["enabled"] is False
    assert "updated_at" in raw["roles"]["researcher"]

    set_role_runtime_enabled(tmp_path, "researcher", True)
    assert role_effective_enabled(tmp_path, "researcher", configured_enabled=False)

    clear_role_runtime_override(tmp_path, "researcher")
    assert read_role_controls(tmp_path) == {}
    assert not role_effective_enabled(tmp_path, "researcher", configured_enabled=False)


def test_malformed_runtime_controls_are_ignored(tmp_path: Path):
    path = role_controls_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert read_role_controls(tmp_path) == {}
