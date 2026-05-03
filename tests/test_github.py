"""Tests for GitHub helper defaults."""

from agentry.github import STANDARD_LABELS


def test_standard_labels_cover_bundled_workflow_failure_states():
    for label in (
        "changes-requested",
        "pr-open",
        "merge-conflict",
        "needs-rebase",
        "needs-hardware-verification",
        "agent-approved",
    ):
        assert label in STANDARD_LABELS
