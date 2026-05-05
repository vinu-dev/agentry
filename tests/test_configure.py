"""Tests for recommended configuration helpers."""

from __future__ import annotations

from agentry.configure import build_recommended_config, summarize_config


def test_build_recommended_config_sets_modes_models_and_budgets():
    raw = {
        "target_repo": "user/repo",
        "agents": {
            "researcher": {
                "cli": "npx",
                "args": ["--yes", "@openai/codex", "exec", "-m", "old"],
                "interval_min": 60,
                "total_min": 30,
                "stall_min": 30,
            },
            "architect": {
                "cli": "npx",
                "args": ["--yes", "@openai/codex", "exec", "-m", "old"],
                "interval_min": 5,
                "total_min": 30,
                "stall_min": 30,
            },
            "release": {
                "cli": "npx",
                "args": ["--yes", "@openai/codex", "exec", "-m", "old"],
                "interval_min": 1440,
                "total_min": 60,
                "stall_min": 60,
            },
            "reviewer": {
                "cli": "npx",
                "args": ["--yes", "@openai/codex", "exec", "-m", "old"],
                "interval_min": 5,
                "total_min": 30,
                "stall_min": 30,
                "trigger": {"pr_labels": ["ready-for-review"]},
            },
        },
    }

    updated = build_recommended_config(
        raw,
        mode="autonomous",
        enable_researcher=True,
        enable_release=False,
        model_profile="cheap",
        auto_merge=True,
        stop_when_queue_empty=True,
    )

    assert updated["mode"] == "autonomous"
    assert updated["automation"]["auto_merge"] is True
    assert updated["automation"]["stop_when_queue_empty"] is True
    assert updated["research"]["allow_create_issues"] is True
    assert updated["context"]["work_packets"] is True
    assert updated["context"]["max_packet_bytes"] == 32_000
    assert updated["agents"]["researcher"]["enabled"] is True
    assert updated["agents"]["release"]["enabled"] is False
    assert updated["agents"]["reviewer"]["trigger"]["pr_check_gate"] == "settled"
    assert updated["agents"]["researcher"]["max_sessions"] == 1
    assert updated["agents"]["researcher"]["token_budget"] == 20000
    assert "gpt-5.4-mini" in updated["agents"]["researcher"]["args"]
    assert "gpt-5.4-mini" in updated["agents"]["architect"]["args"]


def test_summarize_config_reports_role_models():
    summary = summarize_config(
        {
            "mode": "pipeline",
            "automation": {"auto_merge": False},
            "research": {"allow_create_issues": False},
            "context": {"work_packets": True},
            "agents": {
                "implementer": {
                    "enabled": True,
                    "args": ["exec", "-m", "gpt-5.4"],
                    "token_budget": 60000,
                    "max_sessions": 1,
                }
            },
        }
    )

    assert summary["mode"] == "pipeline"
    assert summary["context"]["work_packets"] is True
    assert summary["roles"]["implementer"]["model"] == "gpt-5.4"
    assert summary["roles"]["implementer"]["token_budget"] == 60000
