"""Orchestrator: spawns one forever-loop per declared role.

Each role thread:
  1. Builds the prompt (per-role config.prompt or framework-generated).
  2. Spawns the configured CLI as a subprocess in the target repo or a role worktree.
  3. Supervises with stall + total timeouts.
  4. Logs the outcome to the target's ``agentry/logs/<role>/`` directory.
  5. Optionally posts a Discord event.
  6. Sleeps ``interval_min`` minutes, repeats.

Threads are daemons. Main thread waits on a single ``shutdown_event`` set
by SIGTERM/SIGINT. On shutdown, role threads finish their current sleep,
refuse to spawn another subprocess, and exit. In-flight subprocesses are
killed via the supervisor's interrupt path.

If a role thread crashes (unhandled exception in our code), the orchestrator
logs and respawns it. We never want a single role bug to silently take
down the whole pipeline.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_logs_dir, target_worktrees_dir
from agentry.github import (
    count_open_issues_with_labels,
    has_open_issue_with_label,
    has_open_pr_with_label,
)
from agentry.notify import DiscordNotifier, Event
from agentry.prompt import build_role_prompt
from agentry.session import (
    active_session,
    begin_session,
    finish_session,
    parse_tokens_used,
    update_session,
    utc_now,
)
from agentry.supervisor import ExitReason, supervise
from agentry.workpacket import SelectedPullRequest, selected_pr_for_role, write_role_work_packet

logger = logging.getLogger(__name__)

USAGE_LIMIT_BACKOFF_FALLBACK_SECONDS = 4 * 60 * 60
_USAGE_LIMIT_RE = re.compile(
    r"you've hit your usage limit.*?try again at\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AP]M)",
    re.IGNORECASE | re.DOTALL,
)


class Orchestrator:
    """Owns role threads and the shutdown signal."""

    def __init__(
        self,
        target_config: TargetConfig,
        target_path: Path,
        notifier: DiscordNotifier,
    ) -> None:
        self.target_config = target_config
        self.target_path = Path(target_path).resolve()
        self.notifier = notifier
        self.shutdown_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        enabled_agents = {
            role: cfg
            for role, cfg in self.target_config.agents.items()
            if cfg.enabled and _role_allowed_by_mode(self.target_config, role)
        }
        all_roles = sorted(enabled_agents.keys())
        disabled_roles = sorted(
            role
            for role, cfg in self.target_config.agents.items()
            if not cfg.enabled or not _role_allowed_by_mode(self.target_config, role)
        )
        for role in disabled_roles:
            logger.info("role %s disabled or blocked by mode; not starting thread", role)
        for role, cfg in self.target_config.agents.items():
            if role not in enabled_agents:
                continue
            t = threading.Thread(
                target=self._role_loop_with_recovery,
                args=(role, cfg, all_roles),
                daemon=True,
                name=f"role-{role}",
            )
            t.start()
            self._threads.append(t)
        logger.info("started %d role threads: %s", len(self._threads), ", ".join(all_roles))

    def wait(self) -> None:
        try:
            while not self.shutdown_event.is_set():
                self.shutdown_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt; shutting down")
            self.shutdown_event.set()

        deadline = time.monotonic() + 30.0
        for t in self._threads:
            remaining = max(0.1, deadline - time.monotonic())
            t.join(timeout=remaining)

    def shutdown(self) -> None:
        self.shutdown_event.set()

    # ----- internals -----

    def _role_loop_with_recovery(
        self,
        role: str,
        cfg: AgentConfig,
        all_roles: list[str],
    ) -> None:
        consecutive_crashes = 0
        while not self.shutdown_event.is_set():
            try:
                self._role_loop(role, cfg, all_roles)
                return
            except Exception:
                consecutive_crashes += 1
                logger.exception("role %s crashed (#%d); restarting", role, consecutive_crashes)
                self.notifier.emit(
                    Event(
                        role=role,
                        kind="thread-crashed",
                        message=(
                            f"role thread crashed (#{consecutive_crashes}); "
                            "orchestrator restarting it"
                        ),
                        critical=True,
                    )
                )
                if consecutive_crashes >= 5:
                    logger.error("role %s crashed 5+ times; giving up", role)
                    return
                if self.shutdown_event.wait(timeout=min(60 * consecutive_crashes, 600)):
                    return

    def _role_loop(self, role: str, cfg: AgentConfig, all_roles: list[str]) -> None:
        log_dir = target_logs_dir(self.target_path) / role
        log_dir.mkdir(parents=True, exist_ok=True)

        if not cfg.run_on_start:
            logger.info("role %s waiting %d minutes before first run", role, cfg.interval_min)
            self.notifier.emit(
                Event(
                    role=role,
                    kind="deferred",
                    message=f"first run deferred for {cfg.interval_min} minutes",
                )
            )
            if self.shutdown_event.wait(timeout=cfg.interval_min * 60):
                return

        while not self.shutdown_event.is_set():
            existing = active_session(self.target_path, role)
            if existing is not None:
                logger.info("role %s skipped: existing running session", role)
                self.notifier.emit(
                    Event(role=role, kind="session-active", message="existing session running")
                )
                if self.shutdown_event.wait(timeout=cfg.interval_min * 60):
                    return
                continue

            if not _role_has_work(self.target_config, role, cfg):
                message = _no_work_message(self.target_config, role, cfg)
                logger.info("role %s skipped: %s", role, message)
                self.notifier.emit(Event(role=role, kind="no-work", message=message))
                if self.shutdown_event.wait(timeout=cfg.interval_min * 60):
                    return
                continue

            selected_pr = selected_pr_for_role(self.target_config, cfg)
            role_cwd = self._role_cwd(role, selected_pr=selected_pr)
            if role_cwd is None:
                message = "could not prepare isolated worktree; role will retry later"
                logger.warning("role %s skipped: %s", role, message)
                self.notifier.emit(
                    Event(role=role, kind="worktree-error", message=message, critical=True)
                )
                if self.shutdown_event.wait(timeout=cfg.interval_min * 60):
                    return
                continue

            work_packet_path = write_role_work_packet(
                self.target_path,
                self.target_config,
                role,
                cfg,
            )
            prompt = build_role_prompt(
                role,
                all_roles,
                cfg.prompt,
                work_packet_path=str(work_packet_path) if work_packet_path else None,
            )

            log_path = log_dir / f"{int(time.time())}.log"
            self.notifier.emit(Event(role=role, kind="started", message=f"cli={cfg.cli}"))
            begin_session(
                self.target_path,
                role=role,
                log_path=log_path,
                token_budget=cfg.token_budget,
                mode=self.target_config.mode,
            )
            last_session_touch = 0.0

            def on_spawn(pid: int) -> None:
                update_session(self.target_path, role, pid=pid)

            def on_output() -> None:
                nonlocal last_session_touch
                now = time.monotonic()
                if now - last_session_touch < 5:
                    return
                last_session_touch = now
                update_session(self.target_path, role, last_output_at=utc_now())

            run = supervise(
                cli=cfg.cli,
                args=cfg.args,
                cwd=role_cwd,
                env=None,
                stall_seconds=cfg.stall_min * 60,
                total_seconds=cfg.total_min * 60,
                log_path=log_path,
                shutdown_event=self.shutdown_event,
                stdin_input=prompt,
                checkin_response_seconds=cfg.checkin_response_seconds,
                on_spawn=on_spawn,
                on_output=on_output,
            )
            tokens_used = parse_tokens_used(log_path)
            finish_session(
                self.target_path,
                role,
                run,
                tokens_used=tokens_used,
                token_budget=cfg.token_budget,
            )

            self._emit_outcome(role, run)
            if (
                tokens_used is not None
                and cfg.token_budget is not None
                and tokens_used > cfg.token_budget
            ):
                self.notifier.emit(
                    Event(
                        role=role,
                        kind="token-budget-exceeded",
                        message=f"used {tokens_used} tokens > budget {cfg.token_budget}",
                        critical=False,
                    )
                )

            if run.reason == ExitReason.INTERRUPTED:
                return

            sleep_seconds = _usage_limit_backoff_seconds(run.stdout_path)
            if sleep_seconds is not None:
                minutes = max(1, round(sleep_seconds / 60))
                logger.warning("role %s hit usage limit; backing off for %d minutes", role, minutes)
                self.notifier.emit(
                    Event(
                        role=role,
                        kind="usage-limit",
                        message=f"usage limit hit; retrying in ~{minutes} minutes",
                        critical=False,
                    )
                )
            else:
                sleep_seconds = cfg.interval_min * 60
            if self.shutdown_event.wait(timeout=sleep_seconds):
                return

    def _emit_outcome(self, role: str, run) -> None:
        kind_map = {
            ExitReason.NORMAL: "exited",
            ExitReason.NONZERO: "exited-error",
            ExitReason.STALLED: "stalled",
            ExitReason.TIMED_OUT: "timed-out",
            ExitReason.INTERRUPTED: "interrupted",
            ExitReason.SPAWN_FAILED: "spawn-failed",
            ExitReason.REPORTED_DONE: "reported-done",
            ExitReason.REPORTED_BLOCKED: "reported-blocked",
        }
        critical = run.reason in {ExitReason.STALLED, ExitReason.TIMED_OUT, ExitReason.SPAWN_FAILED}

        if run.reason == ExitReason.SPAWN_FAILED:
            msg = run.error_detail or "could not spawn"
        else:
            msg = (
                f"exit={run.exit_code} duration={int(run.duration_seconds)}s"
                f" log={run.stdout_path.name if run.stdout_path else '?'}"
            )

        self.notifier.emit(
            Event(role=role, kind=kind_map[run.reason], message=msg, critical=critical)
        )

    def _role_cwd(
        self,
        role: str,
        *,
        selected_pr: SelectedPullRequest | None = None,
    ) -> Path | None:
        if not self.target_config.isolate_worktrees:
            return self.target_path

        if not _is_git_repo(self.target_path):
            logger.info("target is not a git repo; role %s using target path", role)
            return self.target_path

        worktree = target_worktrees_dir(self.target_path) / _safe_role_name(role)
        if _is_git_repo(worktree):
            if not _is_git_worktree_clean(worktree):
                logger.warning("role %s worktree is dirty; refusing to spawn", role)
                return None
            if not _refresh_role_worktree(
                self.target_path,
                worktree,
                selected_pr=selected_pr,
            ):
                logger.warning("role %s worktree could not be refreshed", role)
                return None
            return worktree

        worktree.parent.mkdir(parents=True, exist_ok=True)
        _fetch_origin(self.target_path)
        base_ref = _choose_worktree_base_ref(self.target_path)
        logger.info("creating role worktree %s from %s", worktree, base_ref)
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.target_path),
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree),
                    base_ref,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("could not create worktree for role %s: %s", role, e)
            return None
        if not _refresh_role_worktree(
            self.target_path,
            worktree,
            selected_pr=selected_pr,
        ):
            logger.warning("role %s worktree could not be refreshed after creation", role)
            return None
        return worktree


def _is_git_worktree_clean(path: Path) -> bool:
    """Return True when a role worktree has no local repo changes."""
    try:
        subprocess.run(
            ["git", "-C", str(path), "update-index", "-q", "--refresh"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("could not inspect role worktree %s: %s", path, e)
        return False
    return status.stdout.strip() == ""


def _refresh_role_worktree(
    target_path: Path,
    worktree: Path,
    *,
    selected_pr: SelectedPullRequest | None,
) -> bool:
    """Move a clean role worktree to the ref the next role run should inspect."""
    if selected_pr is not None:
        return _checkout_pr_head(worktree, selected_pr.number)

    _fetch_origin(worktree)
    base_ref = _choose_worktree_base_ref(target_path)
    return _checkout_detached(worktree, base_ref)


def _checkout_pr_head(worktree: Path, pr_number: int) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(worktree), "fetch", "origin", f"refs/pull/{pr_number}/head"],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("could not fetch PR #%s into worktree %s: %s", pr_number, worktree, e)
        return False
    return _checkout_detached(worktree, "FETCH_HEAD")


def _checkout_detached(worktree: Path, ref: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(worktree), "checkout", "--detach", ref],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("could not checkout %s in worktree %s: %s", ref, worktree, e)
        return False
    return True


def _fetch_origin(path: Path) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(path), "fetch", "--prune", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return


def _usage_limit_backoff_seconds(
    log_path: Path | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Return a retry delay when a role log contains a Codex usage-limit reset."""
    if log_path is None or not log_path.is_file():
        return None

    text = _read_log_tail(log_path)
    if "hit your usage limit" not in text.lower():
        return None

    now = now or datetime.now()
    match = _USAGE_LIMIT_RE.search(text)
    if not match:
        return USAGE_LIMIT_BACKOFF_FALLBACK_SECONDS

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    retry_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if retry_at <= now:
        retry_at += timedelta(days=1)

    # Add a small buffer so every role does not hammer the CLI at the exact
    # reset minute. Keep malformed/far-future clocks bounded.
    delay = (retry_at - now).total_seconds() + 5 * 60
    return max(15 * 60, min(delay, 24 * 60 * 60))


def _read_log_tail(log_path: Path, max_bytes: int = 65536) -> str:
    size = log_path.stat().st_size
    with log_path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def _role_has_work(target_config: TargetConfig, role: str, cfg: AgentConfig) -> bool:
    """Cheaply decide whether a role should spend an LLM run."""
    if role == "researcher" and not _researcher_backlog_needs_work(target_config):
        return False

    trigger = cfg.trigger
    if trigger is None:
        return True

    for label in trigger.issue_labels:
        if has_open_issue_with_label(target_config.target_repo, label):
            return True
    for label in trigger.pr_labels:
        if has_open_pr_with_label(
            target_config.target_repo,
            label,
            check_gate=trigger.pr_check_gate,
        ):
            return True
    return False


def _researcher_backlog_needs_work(target_config: TargetConfig) -> bool:
    """Return True when Researcher should replenish the design backlog."""
    guard = target_config.research.max_open_ready_for_design
    if guard <= 0:
        return True

    labels = [label for label in target_config.research.backlog_labels if label.strip()]
    if not labels:
        labels = ["ready-for-design"]

    count = count_open_issues_with_labels(
        target_config.target_repo,
        labels,
        limit_per_label=max(guard, 1),
    )
    if count is None:
        logger.warning(
            "researcher skipped: could not count backlog labels %s for %s",
            ", ".join(labels),
            target_config.target_repo,
        )
        return False
    return count < guard


def _role_allowed_by_mode(target_config: TargetConfig, role: str) -> bool:
    """Apply operator run-mode controls before any LLM process is launched."""
    if target_config.mode == "manual":
        return False
    if role == "researcher":
        return target_config.mode == "autonomous" and target_config.research.allow_create_issues
    return True


def _no_work_message(target_config: TargetConfig, role: str, cfg: AgentConfig) -> str:
    if role == "researcher":
        labels = ", ".join(target_config.research.backlog_labels or ["ready-for-design"])
        guard = target_config.research.max_open_ready_for_design
        return f"research backlog has at least {guard} open issue(s) across: {labels}"

    trigger = cfg.trigger
    if trigger is None:
        return "no trigger configured"

    labels: list[str] = []
    labels.extend(f"issue:{label}" for label in trigger.issue_labels)
    labels.extend(f"pr:{label}" for label in trigger.pr_labels)
    if not labels:
        return "empty trigger"
    suffix = ""
    if trigger.pr_labels and trigger.pr_check_gate != "none":
        suffix = f" passing pr_check_gate={trigger.pr_check_gate}"
    return f"no matching work for {', '.join(labels)}{suffix}"


def _is_git_repo(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _choose_worktree_base_ref(target_path: Path) -> str:
    for ref in ("origin/main", "main", "HEAD"):
        try:
            r = subprocess.run(
                ["git", "-C", str(target_path), "rev-parse", "--verify", ref],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return ref
    return "HEAD"


def _safe_role_name(role: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", role).strip("-") or "role"


__all__ = ["Orchestrator"]
