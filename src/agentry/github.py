"""Thin wrapper over the ``gh`` CLI for label management.

Why ``gh`` and not the raw GitHub API: the operator already has ``gh``
installed and authenticated for routine work, and we want the same auth
mechanism (PAT in env, OAuth via ``gh auth login``) without re-implementing
token handling. The downside is shelling out per call; for label init that's
a one-shot operation per target so the overhead is negligible.

Used only by ``agentry doctor --init-labels``. Other ``gh`` calls in v0.1
happen inside the LLM agent subprocesses, not from framework code.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)


# Standard 6-role labels. Targets that need more declare them in their rule
# files; the operator can extend this list at the CLI.
STANDARD_LABELS: dict[str, str] = {
    "ready-for-design": "8a2be2",  # purple
    "ready-for-implementation": "1f883d",  # green
    "ready-for-test": "0e8a16",  # darker green
    "tests-failed": "d93f0b",  # red
    "changes-requested": "d93f0b",  # red
    "pr-open": "1d76db",  # blue
    "ready-for-review": "1d76db",  # blue
    "agent-approved": "0e8a16",  # green
    "blocked": "b60205",  # dark red
    "merge-conflict": "d93f0b",  # red
    "needs-rebase": "fbca04",  # yellow
    "merge-train-waiting": "fbca04",  # yellow
    "needs-hardware-verification": "c5def5",  # light blue
    "release-approved": "5319e7",  # purple
}


def gh_available() -> bool:
    """True if the gh CLI is installed and on PATH."""
    return shutil.which("gh") is not None


def repo_exists(target_repo: str) -> bool:
    """Check whether ``target_repo`` (owner/repo) is reachable by ``gh``."""
    if not gh_available():
        return False
    try:
        r = subprocess.run(
            ["gh", "repo", "view", target_repo, "--json", "name"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def list_labels(target_repo: str) -> set[str]:
    """Return the set of label names currently defined on ``target_repo``."""
    if not gh_available():
        return set()
    try:
        r = subprocess.run(
            [
                "gh",
                "label",
                "list",
                "--repo",
                target_repo,
                "--json",
                "name",
                "--limit",
                "200",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("gh label list failed for %s: %s", target_repo, e)
        return set()
    try:
        labels = json.loads(r.stdout)
        return {item["name"] for item in labels if isinstance(item, dict)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def has_open_issue_with_label(target_repo: str, label: str) -> bool:
    """Return True when an open issue with ``label`` exists."""
    if not gh_available():
        return False
    try:
        r = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                target_repo,
                "--state",
                "open",
                "--label",
                label,
                "--limit",
                "1",
                "--json",
                "number",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("gh issue list failed for %s label %s: %s", target_repo, label, e)
        return False
    try:
        return bool(json.loads(r.stdout))
    except json.JSONDecodeError:
        return False


CheckGate = Literal["none", "settled", "green"]
CheckState = Literal["none", "pending", "green", "failed", "unknown"]


def list_open_issues_with_label(
    target_repo: str,
    label: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Return a bounded list of open issues with ``label``."""
    if not gh_available():
        return []
    try:
        r = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                target_repo,
                "--state",
                "open",
                "--label",
                label,
                "--limit",
                str(limit),
                "--json",
                "number,title,labels,updatedAt",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("gh issue list failed for %s label %s: %s", target_repo, label, e)
        return []
    try:
        items = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def list_open_prs_with_label(
    target_repo: str,
    label: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Return a bounded list of open pull requests with ``label``."""
    if not gh_available():
        return []
    try:
        r = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                target_repo,
                "--state",
                "open",
                "--label",
                label,
                "--limit",
                str(limit),
                "--json",
                "number,title,headRefName,labels,updatedAt",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("gh pr list failed for %s label %s: %s", target_repo, label, e)
        return []
    try:
        items = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def has_open_pr_with_label(
    target_repo: str,
    label: str,
    *,
    check_gate: CheckGate = "none",
) -> bool:
    """Return True when an open pull request with ``label`` passes the cheap gate."""
    candidates = list_open_prs_with_label(target_repo, label, limit=20)
    if not candidates:
        return False
    if check_gate == "none":
        return True

    for pr in candidates:
        number = pr.get("number")
        if not isinstance(number, int):
            continue
        state = pr_checks_state(target_repo, number)
        if _check_state_passes_gate(state, check_gate):
            return True

    logger.info(
        "open PRs with label %s exist in %s but none pass pr_check_gate=%s",
        label,
        target_repo,
        check_gate,
    )
    return False


def pr_checks_state(target_repo: str, pr_number: int) -> CheckState:
    """Return a coarse check state for one PR.

    Unknown check state is intentionally permissive at the orchestrator gate:
    a transient GitHub/CLI failure should not deadlock the pipeline.
    """
    if not gh_available():
        return "unknown"
    try:
        r = subprocess.run(
            [
                "gh",
                "pr",
                "checks",
                str(pr_number),
                "--repo",
                target_repo,
                "--json",
                "name,state,bucket",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        logger.warning("gh pr checks timed out for %s#%s", target_repo, pr_number)
        return "unknown"

    if r.returncode != 0:
        stderr = r.stderr.strip().lower()
        if "no checks" in stderr or "no check" in stderr:
            return "none"
        logger.warning(
            "gh pr checks failed for %s#%s: %s",
            target_repo,
            pr_number,
            r.stderr.strip(),
        )
        return "unknown"

    try:
        checks = json.loads(r.stdout)
    except json.JSONDecodeError:
        return "unknown"
    if not isinstance(checks, list):
        return "unknown"
    if not checks:
        return "none"

    buckets = {
        _normalize_check_value(item.get("bucket")) for item in checks if isinstance(item, dict)
    }
    states = {
        _normalize_check_value(item.get("state")) for item in checks if isinstance(item, dict)
    }
    values = {value for value in buckets | states if value}

    if values & {"pending", "queued", "in_progress", "waiting", "requested"}:
        return "pending"
    if values & {"fail", "failing", "failed", "failure", "error", "cancelled", "timed_out"}:
        return "failed"
    if values and values <= {
        "pass",
        "passing",
        "success",
        "skipped",
        "skipping",
        "neutral",
        "completed",
    }:
        return "green"
    return "unknown"


def _check_state_passes_gate(state: CheckState, check_gate: CheckGate) -> bool:
    if state == "unknown":
        return True
    if check_gate == "settled":
        return state in {"none", "green", "failed"}
    if check_gate == "green":
        return state in {"none", "green"}
    return True


def _normalize_check_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def create_label(target_repo: str, name: str, color: str = "ededed") -> bool:
    """Create ``name`` label in ``target_repo``. Returns True on success.

    Idempotent: if the label exists, returns True without erroring.
    """
    if not gh_available():
        return False
    try:
        r = subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                target_repo,
                "--color",
                color,
                "--force",  # overwrite if exists
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            logger.warning("gh label create %s failed: %s", name, r.stderr.strip())
            return False
        return True
    except subprocess.TimeoutExpired:
        return False


def init_labels(target_repo: str, labels: dict[str, str] | None = None) -> dict[str, bool]:
    """Create all standard labels (or ``labels``) in ``target_repo``.

    Returns a per-label success map.
    """
    to_create = labels if labels is not None else STANDARD_LABELS
    return {name: create_label(target_repo, name, color) for name, color in to_create.items()}


__all__ = [
    "STANDARD_LABELS",
    "create_label",
    "gh_available",
    "has_open_issue_with_label",
    "has_open_pr_with_label",
    "init_labels",
    "list_labels",
    "list_open_issues_with_label",
    "list_open_prs_with_label",
    "pr_checks_state",
    "repo_exists",
]
