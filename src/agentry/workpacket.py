"""Bounded context packets for role invocations.

Work packets are cheap, deterministic Markdown files written before an LLM role
starts. They give the model a compact starting point so it does not burn tokens
rediscovering queue state or reading full logs.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_state_dir
from agentry.github import (
    list_open_issues_with_label,
    list_open_prs_with_label,
    pr_checks_state,
)
from agentry.session import list_sessions


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

    lines.extend(["", "## GitHub Candidates"])
    if trigger is None:
        lines.append("- No trigger labels to prefetch.")
    else:
        for label in trigger.issue_labels:
            lines.extend(_issue_candidate_lines(target_config, label))
        for label in trigger.pr_labels:
            lines.extend(_pr_candidate_lines(target_config, label))

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
            "- If CI/checks are pending, leave labels unchanged and exit so Agentry can retry.",
        ]
    )
    return "\n".join(lines) + "\n"


def _issue_candidate_lines(target_config: TargetConfig, label: str) -> list[str]:
    issues = list_open_issues_with_label(
        target_config.target_repo,
        label,
        limit=target_config.context.candidate_limit,
    )
    lines = [f"### Issues labeled `{label}`"]
    if not issues:
        lines.append("- None found or GitHub lookup unavailable.")
        return lines
    for item in issues:
        number = item.get("number", "?")
        title = _one_line(item.get("title"))
        labels = _label_names(item.get("labels"))
        updated = item.get("updatedAt", "?")
        lines.append(f"- #{number}: {title} labels=[{labels}] updated={updated}")
    return lines


def _pr_candidate_lines(target_config: TargetConfig, label: str) -> list[str]:
    prs = list_open_prs_with_label(
        target_config.target_repo,
        label,
        limit=target_config.context.candidate_limit,
    )
    lines = [f"### PRs labeled `{label}`"]
    if not prs:
        lines.append("- None found or GitHub lookup unavailable.")
        return lines
    for item in prs:
        number = item.get("number")
        title = _one_line(item.get("title"))
        labels = _label_names(item.get("labels"))
        head = item.get("headRefName", "?")
        updated = item.get("updatedAt", "?")
        checks = "unknown"
        if isinstance(number, int):
            checks = pr_checks_state(target_config.target_repo, number)
        lines.append(
            f"- #{number}: {title} head={head} labels=[{labels}] "
            f"checks={checks} updated={updated}"
        )
    return lines


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
    if not isinstance(labels, list):
        return ""
    names = []
    for label in labels:
        if isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
        elif isinstance(label, str):
            names.append(label)
    return ", ".join(sorted(names))


def _one_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "role"


__all__ = ["work_packet_path", "write_role_work_packet"]
