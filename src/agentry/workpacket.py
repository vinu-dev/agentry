"""Bounded context packets for role invocations.

Work packets are cheap, deterministic Markdown files written before an LLM role
starts. They give the model a compact starting point so it does not burn tokens
rediscovering queue state or reading full logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_state_dir
from agentry.github import (
    count_open_pull_requests,
    list_open_issues_with_label,
    list_open_prs_with_label,
    pr_checks_state,
)
from agentry.session import list_sessions


@dataclass(frozen=True)
class WorkCandidate:
    """One GitHub queue item discovered during cheap preflight."""

    kind: str
    label: str
    item: dict
    checks: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class SelectedPullRequest:
    """The PR selected for a PR-triggered role run."""

    number: int
    head_ref_name: str | None = None


def work_packet_path(target_path: Path | str, role: str) -> Path:
    """Return the packet path for ``role`` in the target's local state."""
    return target_state_dir(target_path) / "workpackets" / f"{_safe_name(role)}.md"


def write_role_work_packet(
    target_path: Path | str,
    target_config: TargetConfig,
    role: str,
    cfg: AgentConfig,
) -> Path | None:
    """Write a bounded per-run work packet and return its path.

    GitHub lookups are best-effort. If a transient CLI/API error happens, the
    packet records whatever can be collected and the role can still run.
    """
    if not target_config.context.work_packets:
        return None

    path = work_packet_path(target_path, role)
    text = _build_packet(target_path, target_config, role, cfg)
    _write_capped(path, text, max_bytes=target_config.context.max_packet_bytes)
    return path


def selected_pr_for_role(
    target_config: TargetConfig,
    cfg: AgentConfig,
) -> SelectedPullRequest | None:
    """Return the selected PR, if this role is about to process a PR.

    This mirrors the deterministic work-packet candidate selection so the
    orchestrator can prepare the isolated worktree at the same PR head the
    packet asks the role to process.
    """
    trigger = cfg.trigger
    if trigger is None or not trigger.pr_labels:
        return None

    selected = _select_candidate(_candidate_groups(target_config, cfg), cfg)
    if selected is None or selected.kind != "pr":
        return None

    number = selected.item.get("number")
    if not isinstance(number, int):
        return None

    head = selected.item.get("headRefName")
    return SelectedPullRequest(
        number=number,
        head_ref_name=head if isinstance(head, str) else None,
    )


def _build_packet(
    target_path: Path | str,
    target_config: TargetConfig,
    role: str,
    cfg: AgentConfig,
) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    trigger = cfg.trigger
    lines: list[str] = [
        f"# Agentry Work Packet: {role}",
        "",
        f"- Generated: {now}",
        f"- Target repo: {target_config.target_repo}",
        f"- Target path: {Path(target_path).resolve()}",
        f"- Mode: {target_config.mode}",
        f"- Candidate limit per label: {target_config.context.candidate_limit}",
        f"- Log tail guidance: read at most {target_config.context.log_tail_lines} lines at a time",
        (
            "- Diff guidance: inspect file lists first; avoid full diffs above "
            f"{target_config.context.diff_max_lines} lines"
        ),
        "",
        "## Trigger",
    ]

    if trigger is None:
        lines.append("- No trigger configured; this role may be schedule-driven.")
    else:
        if trigger.issue_labels:
            lines.append(f"- Issue labels: {', '.join(trigger.issue_labels)}")
        if trigger.pr_labels:
            lines.append(f"- PR labels: {', '.join(trigger.pr_labels)}")
            lines.append(f"- PR check gate: {trigger.pr_check_gate}")

    groups: list[tuple[str, str, list[WorkCandidate]]] = []
    selected: WorkCandidate | None = None
    if trigger is None:
        lines.extend(["", "## Selected Candidate", "- None; no trigger labels to prefetch."])
    else:
        groups = _candidate_groups(target_config, cfg)
        selected = _select_candidate(groups, cfg)
        lines.extend(["", "## Selected Candidate"])
        lines.extend(_selected_candidate_lines(selected))
        lines.extend(["", "## Other Candidates"])
        lines.append("- Read-only context. Do not process these in this run.")
        for kind, label, candidates in groups:
            lines.extend(_candidate_lines(kind, label, candidates, selected))

    lines.extend(["", "## Recent Sessions"])
    sessions = sorted(
        list_sessions(target_path),
        key=lambda item: str(item.get("started_at") or ""),
        reverse=True,
    )
    if not sessions:
        lines.append("- No session records yet.")
    for session in sessions[:12]:
        role_name = session.get("role", "?")
        state = session.get("state", "?")
        started = session.get("started_at", "?")
        finished = session.get("finished_at") or "-"
        tokens = session.get("tokens_used")
        budget = session.get("token_budget")
        log_path = session.get("log_path") or "-"
        usage_text = "-"
        if tokens is not None:
            usage_text = str(tokens)
            if budget is not None:
                usage_text = f"{tokens}/{budget}"
        lines.append(
            f"- {role_name}: state={state} started={started} finished={finished} "
            f"tokens={usage_text} log={log_path}"
        )

    lines.extend(
        [
            "",
            "## Context Rules",
            "- Read this packet first, then use GitHub and repo files for current truth.",
            "- Do not read full agent logs. Use bounded tails, for example PowerShell "
            f"`Get-Content -Tail {target_config.context.log_tail_lines} <log>` or "
            f"Bash `tail -n {target_config.context.log_tail_lines} <log>`.",
            (
                "- Inspect PR file lists before diffs. Use targeted file diffs "
                "when the full diff is large."
            ),
            "- If a Selected Candidate is present, process only that item in this run.",
            "- Do not inspect, relabel, test, review, or repair other candidates except "
            "to verify they do not block the Selected Candidate.",
            _pr_creation_context_rule(target_config),
            _ci_pending_context_rule(trigger),
        ]
    )
    return "\n".join(lines) + "\n"


def _pr_creation_context_rule(target_config: TargetConfig) -> str:
    labels = ", ".join(target_config.automation.pr_creation_issue_labels)
    return (
        "- New PR creation gate: issues without `pr-open` under "
        f"[{labels}] must not open another pull request while the target has "
        f"{target_config.automation.max_open_prs} open PR(s). Before any "
        "`gh pr create`, re-check the open PR count, fetch/rebase on "
        "`origin/main`, and stop with `merge-conflict` if the branch cannot "
        "be made current cleanly."
    )


def _ci_pending_context_rule(trigger) -> str:
    """Return queue guidance for pending CI that matches the role trigger shape."""
    if trigger is None:
        return (
            "- If CI/checks are pending, do not guess. Follow the role's explicit "
            "queue rules and record the pending state."
        )

    if trigger.pr_labels:
        return (
            "- For PR-triggered roles, if required CI/checks are still pending "
            "for the selected PR, leave labels unchanged, record the pending "
            "state, and exit so Agentry can retry after the check gate opens."
        )

    return (
        "- For issue-triggered roles that open or update a PR, do not leave the "
        "issue in the same trigger label solely because GitHub checks are "
        "pending after local validation passed. Move the issue/PR to the role's "
        "next queue state; downstream PR check gates will defer review until "
        "checks settle."
    )


def _candidate_groups(
    target_config: TargetConfig,
    cfg: AgentConfig,
) -> list[tuple[str, str, list[WorkCandidate]]]:
    trigger = cfg.trigger
    if trigger is None:
        return []

    groups: list[tuple[str, str, list[WorkCandidate]]] = []
    for label in trigger.issue_labels:
        issues = list_open_issues_with_label(
            target_config.target_repo,
            label,
            limit=target_config.context.candidate_limit,
        )
        blocked_reason = _issue_label_pr_creation_block_reason(target_config, label)
        candidates = []
        for item in issues:
            item_labels = _label_names_set(item.get("labels"))
            reason = None
            if "pr-open" not in item_labels:
                reason = blocked_reason
            candidates.append(WorkCandidate("issue", label, item, blocked_reason=reason))
        groups.append(("issue", label, candidates))

    for label in trigger.pr_labels:
        prs = list_open_prs_with_label(
            target_config.target_repo,
            label,
            limit=target_config.context.candidate_limit,
        )
        candidates = []
        for item in prs:
            number = item.get("number")
            checks = "unknown"
            if isinstance(number, int):
                checks = pr_checks_state(target_config.target_repo, number)
            candidates.append(WorkCandidate("pr", label, item, checks))
        groups.append(("pr", label, candidates))

    return groups


def _select_candidate(
    groups: list[tuple[str, str, list[WorkCandidate]]],
    cfg: AgentConfig,
) -> WorkCandidate | None:
    trigger = cfg.trigger
    for kind, _label, candidates in groups:
        eligible = [candidate for candidate in candidates if candidate.blocked_reason is None]
        if kind == "pr" and trigger is not None:
            eligible = [
                candidate
                for candidate in eligible
                if _checks_pass_gate(candidate.checks or "unknown", trigger.pr_check_gate)
            ]
        if eligible:
            return sorted(eligible, key=_candidate_sort_key)[0]
    return None


def _selected_candidate_lines(selected: WorkCandidate | None) -> list[str]:
    if selected is None:
        return [
            "- None found that passed preflight gates.",
            "- Exit successfully if current GitHub state still has no eligible work.",
        ]

    number = selected.item.get("number", "?")
    title = _one_line(selected.item.get("title"))
    labels = _label_names(selected.item.get("labels"))
    updated = selected.item.get("updatedAt", "?")
    lines = [
        f"- Type: {selected.kind}",
        f"- Trigger label: `{selected.label}`",
        f"- Number: #{number}",
        f"- Title: {title}",
        f"- Labels: [{labels}]",
        f"- Updated: {updated}",
    ]
    head = selected.item.get("headRefName")
    if isinstance(head, str):
        lines.append(f"- Head branch: {head}")
    if selected.checks is not None:
        lines.append(f"- Checks: {selected.checks}")
    lines.extend(
        [
            "",
            f"Process ONLY {selected.kind} #{number} in this run.",
            "Do not inspect, relabel, repair, test, review, or merge any other candidate "
            "unless it directly blocks this selected item.",
        ]
    )
    return lines


def _candidate_lines(
    kind: str,
    label: str,
    candidates: list[WorkCandidate],
    selected: WorkCandidate | None,
) -> list[str]:
    heading = "Issues" if kind == "issue" else "PRs"
    lines = [f"### {heading} labeled `{label}`"]
    if not candidates:
        lines.append("- None found or GitHub lookup unavailable.")
        return lines

    for candidate in sorted(candidates, key=_candidate_sort_key):
        item = candidate.item
        number = item.get("number", "?")
        title = _one_line(item.get("title"))
        labels = _label_names(item.get("labels"))
        updated = item.get("updatedAt", "?")
        marker = " (selected)" if candidate == selected else ""
        if kind == "pr":
            head = item.get("headRefName", "?")
            checks = candidate.checks or "unknown"
            lines.append(
                f"- #{number}: {title}{marker} head={head} labels=[{labels}] "
                f"checks={checks} updated={updated}"
            )
        else:
            blocked = (
                f" blocked={candidate.blocked_reason}"
                if candidate.blocked_reason is not None
                else ""
            )
            lines.append(
                f"- #{number}: {title}{marker} labels=[{labels}]{blocked} updated={updated}"
            )
    return lines


def _checks_pass_gate(state: str, check_gate: str) -> bool:
    if state == "unknown":
        return True
    if check_gate == "settled":
        return state in {"none", "green", "failed"}
    if check_gate == "green":
        return state in {"none", "green"}
    return True


def _candidate_sort_key(candidate: WorkCandidate) -> tuple[int, str]:
    number = candidate.item.get("number")
    if isinstance(number, int):
        return (number, "")
    return (10**12, str(number))


def _issue_label_pr_creation_block_reason(
    target_config: TargetConfig,
    label: str,
) -> str | None:
    automation = target_config.automation
    if label not in set(automation.pr_creation_issue_labels):
        return None

    count = count_open_pull_requests(
        target_config.target_repo,
        limit=max(automation.max_open_prs + 1, 1),
    )
    if count is None:
        return "open-pr-count-unavailable"
    if count >= automation.max_open_prs:
        return f"open-pr-limit {count}/{automation.max_open_prs}"
    return None


def _write_capped(path: Path, text: str, *, max_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        path.write_bytes(encoded)
        return
    trailer = f"\n\n[work packet truncated at {max_bytes} bytes]\n".encode()
    keep = max(0, max_bytes - len(trailer))
    capped = encoded[:keep].decode("utf-8", errors="ignore").encode("utf-8") + trailer
    path.write_bytes(capped[:max_bytes])


def _label_names(labels: object) -> str:
    return ", ".join(sorted(_label_names_set(labels)))


def _label_names_set(labels: object) -> set[str]:
    if not isinstance(labels, list):
        return set()
    names = set()
    for label in labels:
        if isinstance(label, dict) and isinstance(label.get("name"), str):
            names.add(label["name"])
        elif isinstance(label, str):
            names.add(label)
    return names


def _one_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "role"


__all__ = [
    "SelectedPullRequest",
    "selected_pr_for_role",
    "work_packet_path",
    "write_role_work_packet",
]
