"""Configuration helpers used by the CLI wizard and local dashboard."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from agentry.config import target_config_file

ROLE_ORDER = ("researcher", "architect", "implementer", "tester", "reviewer", "release")

TOKEN_BUDGETS = {
    "researcher": 20000,
    "architect": 25000,
    "implementer": 60000,
    "tester": 30000,
    "reviewer": 25000,
    "release": 30000,
}

MODEL_PROFILES = {
    "balanced": {
        "researcher": "gpt-5.4-mini",
        "architect": "gpt-5.4",
        "implementer": "gpt-5.4",
        "tester": "gpt-5.4-mini",
        "reviewer": "gpt-5.4",
        "release": "gpt-5.4-mini",
    },
    "cheap": {
        "researcher": "gpt-5.4-mini",
        "architect": "gpt-5.4-mini",
        "implementer": "gpt-5.4",
        "tester": "gpt-5.4-mini",
        "reviewer": "gpt-5.4",
        "release": "gpt-5.4-mini",
    },
    "strong": {
        "researcher": "gpt-5.4",
        "architect": "gpt-5.4",
        "implementer": "gpt-5.4",
        "tester": "gpt-5.4",
        "reviewer": "gpt-5.4",
        "release": "gpt-5.4",
    },
}


def read_raw_config(target_path: Path | str) -> dict[str, Any]:
    path = target_config_file(target_path)
    if not path.is_file():
        raise FileNotFoundError(f"missing target config: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return raw


def apply_recommended_options(
    target_path: Path | str,
    *,
    mode: str = "pipeline",
    enable_researcher: bool = False,
    enable_release: bool = False,
    model_profile: str = "balanced",
    auto_merge: bool = False,
    stop_when_queue_empty: bool = False,
) -> dict[str, Any]:
    raw = read_raw_config(target_path)
    updated = build_recommended_config(
        raw,
        mode=mode,
        enable_researcher=enable_researcher,
        enable_release=enable_release,
        model_profile=model_profile,
        auto_merge=auto_merge,
        stop_when_queue_empty=stop_when_queue_empty,
    )
    write_raw_config(target_path, updated)
    return updated


def build_recommended_config(
    raw: dict[str, Any],
    *,
    mode: str = "pipeline",
    enable_researcher: bool = False,
    enable_release: bool = False,
    model_profile: str = "balanced",
    auto_merge: bool = False,
    stop_when_queue_empty: bool = False,
) -> dict[str, Any]:
    data = deepcopy(raw)
    mode = mode.strip().lower()
    if mode not in {"manual", "pipeline", "autonomous"}:
        raise ValueError("mode must be manual, pipeline, or autonomous")
    if model_profile not in MODEL_PROFILES:
        raise ValueError(f"unknown model profile: {model_profile}")

    data["mode"] = mode
    data.setdefault("automation", {})
    data["automation"]["auto_merge"] = bool(auto_merge)
    data["automation"]["stop_when_queue_empty"] = bool(stop_when_queue_empty)

    data.setdefault("research", {})
    data["research"]["allow_create_issues"] = bool(mode == "autonomous" and enable_researcher)
    data["research"].setdefault("max_open_ready_for_design", 3)

    agents = data.setdefault("agents", {})
    models = MODEL_PROFILES[model_profile]
    for role in ROLE_ORDER:
        if role not in agents or not isinstance(agents[role], dict):
            continue
        cfg = agents[role]
        cfg["max_sessions"] = 1
        cfg["token_budget"] = TOKEN_BUDGETS[role]
        cfg.setdefault("checkin_response_seconds", 90)
        if role == "researcher":
            cfg["enabled"] = bool(enable_researcher)
        elif role == "release":
            cfg["enabled"] = bool(enable_release)
        else:
            cfg.setdefault("enabled", True)
        cfg["args"] = _set_codex_model(cfg.get("args", []), models[role])
    return data


def write_raw_config(target_path: Path | str, raw: dict[str, Any]) -> None:
    path = target_config_file(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _literalize_multiline(raw)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def summarize_config(raw: dict[str, Any]) -> dict[str, Any]:
    agents = raw.get("agents") if isinstance(raw.get("agents"), dict) else {}
    return {
        "mode": raw.get("mode", "pipeline"),
        "automation": raw.get("automation", {}),
        "research": raw.get("research", {}),
        "roles": {
            role: {
                "enabled": bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else False,
                "model": _codex_model(cfg.get("args", [])) if isinstance(cfg, dict) else None,
                "token_budget": cfg.get("token_budget") if isinstance(cfg, dict) else None,
                "max_sessions": cfg.get("max_sessions", 1) if isinstance(cfg, dict) else None,
            }
            for role, cfg in agents.items()
        },
    }


class LiteralStr(str):
    pass


def _literal_str_representer(dumper: yaml.SafeDumper, data: LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.SafeDumper.add_representer(LiteralStr, _literal_str_representer)


def _literalize_multiline(obj: Any) -> Any:
    if isinstance(obj, str) and "\n" in obj:
        return LiteralStr(obj)
    if isinstance(obj, dict):
        return {k: _literalize_multiline(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_literalize_multiline(v) for v in obj]
    return obj


def _set_codex_model(args: Any, model: str) -> Any:
    if not isinstance(args, list):
        return args
    out = list(args)
    for idx, value in enumerate(out[:-1]):
        if value == "-m":
            out[idx + 1] = model
            return out
    return out


def _codex_model(args: Any) -> str | None:
    if not isinstance(args, list):
        return None
    for idx, value in enumerate(args[:-1]):
        if value == "-m":
            nxt = args[idx + 1]
            return str(nxt) if nxt is not None else None
    return None


__all__ = [
    "MODEL_PROFILES",
    "ROLE_ORDER",
    "TOKEN_BUDGETS",
    "apply_recommended_options",
    "build_recommended_config",
    "read_raw_config",
    "summarize_config",
    "write_raw_config",
]
