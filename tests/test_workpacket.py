"""Tests for bounded role work packets."""

from __future__ import annotations

import sys
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig
from agentry.workpacket import write_role_work_packet


def test_write_role_work_packet_includes_trigger_and_context(monkeypatch, tmp_path: Path):
    cfg = TargetConfig(
        target_repo="owner/repo",
        agents={
            "reviewer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=5,
                total_min=1,
                stall_min=1,
                trigger={
                    "pr_labels": ["ready-for-review"],
                    "pr_check_gate": "settled",
                },
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.workpacket.list_open_prs_with_label",
        lambda repo, label, *, limit: [
            {
                "number": 12,
                "title": "Ready PR",
                "headRefName": "feature/test",
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr("agentry.workpacket.pr_checks_state", lambda repo, number: "green")

    path = write_role_work_packet(tmp_path, cfg, "reviewer", cfg.agents["reviewer"])

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "Agentry Work Packet: reviewer" in text
    assert "PR check gate: settled" in text
    assert "#12: Ready PR" in text
    assert "checks=green" in text
    assert "Get-Content -Tail 120" in text


def test_write_role_work_packet_respects_byte_cap(monkeypatch, tmp_path: Path):
    cfg = TargetConfig(
        target_repo="owner/repo",
        context={"max_packet_bytes": 4_000},
        agents={
            "architect": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=5,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-design"]},
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.workpacket.list_open_issues_with_label",
        lambda repo, label, *, limit: [
            {
                "number": n,
                "title": "x" * 500,
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            }
            for n in range(30)
        ],
    )

    path = write_role_work_packet(tmp_path, cfg, "architect", cfg.agents["architect"])

    assert path is not None
    data = path.read_bytes()
    assert len(data) <= 4_000
    assert b"work packet truncated" in data
