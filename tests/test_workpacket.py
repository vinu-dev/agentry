"""Tests for bounded role work packets."""

from __future__ import annotations

import sys
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig
from agentry.workpacket import selected_pr_for_role, write_role_work_packet


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
    assert "## Selected Candidate" in text
    assert "Process ONLY pr #12" in text
    assert "#12: Ready PR" in text
    assert "checks=green" in text
    assert "Get-Content -Tail 120" in text
    assert "New PR creation gate" in text
    assert "For PR-triggered roles" in text
    assert "leave labels unchanged" in text


def test_write_role_work_packet_selects_one_issue_by_trigger_priority(
    monkeypatch,
    tmp_path: Path,
):
    cfg = TargetConfig(
        target_repo="owner/repo",
        agents={
            "implementer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=5,
                total_min=1,
                stall_min=1,
                trigger={
                    "issue_labels": [
                        "changes-requested",
                        "tests-failed",
                        "ready-for-implementation",
                    ]
                },
            ),
        },
    )

    def issues_for_label(repo, label, *, limit):
        del repo, limit
        if label == "tests-failed":
            return [
                {
                    "number": 14,
                    "title": "Fix localization traceability",
                    "labels": [{"name": label}, {"name": "pr-open"}],
                    "updatedAt": "2026-05-05T00:00:00Z",
                }
            ]
        if label == "ready-for-implementation":
            return [
                {
                    "number": 12,
                    "title": "Reconcile SWR counts",
                    "labels": [{"name": label}, {"name": "pr-open"}],
                    "updatedAt": "2026-05-05T00:00:00Z",
                }
            ]
        return []

    monkeypatch.setattr("agentry.workpacket.list_open_issues_with_label", issues_for_label)

    path = write_role_work_packet(tmp_path, cfg, "implementer", cfg.agents["implementer"])

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "- Trigger label: `tests-failed`" in text
    assert "- Number: #14" in text
    assert "Process ONLY issue #14" in text
    assert "#12:" in text
    assert "Do not process these in this run" in text
    assert "For issue-triggered roles that open or update a PR" in text
    assert (
        "do not leave the issue in the same trigger label solely because GitHub checks are pending"
        in text
    )


def test_write_role_work_packet_skips_pending_pr_for_settled_gate(
    monkeypatch,
    tmp_path: Path,
):
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
                "number": 22,
                "title": "Still building",
                "headRefName": "feature/pending",
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            },
            {
                "number": 23,
                "title": "Ready for review",
                "headRefName": "feature/green",
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(
        "agentry.workpacket.pr_checks_state",
        lambda repo, number: "pending" if number == 22 else "green",
    )

    path = write_role_work_packet(tmp_path, cfg, "reviewer", cfg.agents["reviewer"])

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "- Number: #23" in text
    assert "Process ONLY pr #23" in text
    assert "#22:" in text
    assert "checks=pending" in text


def test_selected_pr_for_role_matches_work_packet_selection(monkeypatch):
    cfg = TargetConfig(
        target_repo="owner/repo",
        agents={
            "regulatory_reviewer": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=5,
                total_min=1,
                stall_min=1,
                trigger={
                    "pr_labels": ["ready-for-regulatory-review"],
                    "pr_check_gate": "green",
                },
            ),
        },
    )
    monkeypatch.setattr(
        "agentry.workpacket.list_open_prs_with_label",
        lambda repo, label, *, limit: [
            {
                "number": 30,
                "title": "Selected PR",
                "headRefName": "feature/pr-head",
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr("agentry.workpacket.pr_checks_state", lambda repo, number: "green")

    selected = selected_pr_for_role(cfg, cfg.agents["regulatory_reviewer"])

    assert selected is not None
    assert selected.number == 30
    assert selected.head_ref_name == "feature/pr-head"


def test_write_role_work_packet_blocks_new_pr_candidate_when_limit_reached(
    monkeypatch,
    tmp_path: Path,
):
    cfg = TargetConfig(
        target_repo="owner/repo",
        automation={"max_open_prs": 1, "pr_creation_issue_labels": ["ready-for-test"]},
        agents={
            "tester": AgentConfig(
                cli=sys.executable,
                args=[],
                interval_min=5,
                total_min=1,
                stall_min=1,
                trigger={"issue_labels": ["ready-for-test"]},
            ),
        },
    )
    monkeypatch.setattr("agentry.workpacket.count_open_pull_requests", lambda repo, **kwargs: 1)
    monkeypatch.setattr(
        "agentry.workpacket.list_open_issues_with_label",
        lambda repo, label, *, limit: [
            {
                "number": 42,
                "title": "Existing PR retest",
                "labels": [{"name": label}, {"name": "pr-open"}],
                "updatedAt": "2026-05-05T00:00:00Z",
            },
            {
                "number": 43,
                "title": "Would open another PR",
                "labels": [{"name": label}],
                "updatedAt": "2026-05-05T00:00:00Z",
            },
        ],
    )

    path = write_role_work_packet(tmp_path, cfg, "tester", cfg.agents["tester"])

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "- Number: #42" in text
    assert "Process ONLY issue #42" in text
    assert "#43: Would open another PR" in text
    assert "blocked=open-pr-limit 1/1" in text


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
