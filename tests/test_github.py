"""Tests for GitHub helper defaults."""

from __future__ import annotations

import json
import subprocess

from agentry.github import STANDARD_LABELS, has_open_pr_with_label, pr_checks_state


def test_standard_labels_cover_bundled_workflow_failure_states():
    for label in (
        "changes-requested",
        "pr-open",
        "merge-conflict",
        "needs-rebase",
        "merge-train-waiting",
        "needs-hardware-verification",
        "agent-approved",
    ):
        assert label in STANDARD_LABELS


def test_pr_check_gate_skips_pending_pr(monkeypatch):
    monkeypatch.setattr("agentry.github.gh_available", lambda: True)

    def fake_run(args, **kwargs):
        if args[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps([{"number": 42, "title": "test"}]),
                stderr="",
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps([{"name": "ci", "state": "IN_PROGRESS", "bucket": "pending"}]),
                stderr="",
            )
        raise AssertionError(args)

    monkeypatch.setattr("agentry.github.subprocess.run", fake_run)

    assert not has_open_pr_with_label("owner/repo", "ready-for-review", check_gate="settled")


def test_pr_check_gate_allows_green_pr(monkeypatch):
    monkeypatch.setattr("agentry.github.gh_available", lambda: True)

    def fake_run(args, **kwargs):
        if args[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps([{"number": 42, "title": "test"}]),
                stderr="",
            )
        if args[:3] == ["gh", "pr", "checks"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps([{"name": "ci", "state": "SUCCESS", "bucket": "pass"}]),
                stderr="",
            )
        raise AssertionError(args)

    monkeypatch.setattr("agentry.github.subprocess.run", fake_run)

    assert has_open_pr_with_label("owner/repo", "ready-for-review", check_gate="green")


def test_pr_checks_state_treats_no_checks_as_none(monkeypatch):
    monkeypatch.setattr("agentry.github.gh_available", lambda: True)

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="no checks reported")

    monkeypatch.setattr("agentry.github.subprocess.run", fake_run)

    assert pr_checks_state("owner/repo", 42) == "none"
