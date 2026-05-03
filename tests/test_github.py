"""Tests for GitHub helper defaults."""

from agentry.github import STANDARD_LABELS


def test_standard_labels_cover_bundled_workflow_failure_states():
    for label in (
        "changes-requested",
        "merge-conflict",
        "needs-rebase",
        "needs-hardware-verification",
    ):
        assert label in STANDARD_LABELS
