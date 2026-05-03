"""Orchestrator: spawns one forever-loop per declared role.

Each role thread:
  1. Builds the prompt (per-role config.prompt or framework-generated).
  2. Spawns the configured CLI as a subprocess with cwd = target repo root.
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
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_logs_dir
from agentry.github import has_open_issue_with_label, has_open_pr_with_label
from agentry.notify import DiscordNotifier, Event
from agentry.prompt import make_prompt
from agentry.supervisor import ExitReason, supervise

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
            role: cfg for role, cfg in self.target_config.agents.items() if cfg.enabled
        }
        all_roles = sorted(enabled_agents.keys())
        disabled_roles = sorted(
            role for role, cfg in self.target_config.agents.items() if not cfg.enabled
        )
        for role in disabled_roles:
            logger.info("role %s disabled; not starting thread", role)
        for role, cfg in self.target_config.agents.items():
            if not cfg.enabled:
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
        prompt = cfg.prompt if cfg.prompt else make_prompt(role, all_roles)
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
            if not _role_has_work(self.target_config, cfg):
                message = _no_work_message(cfg)
                logger.info("role %s skipped: %s", role, message)
                self.notifier.emit(Event(role=role, kind="no-work", message=message))
                if self.shutdown_event.wait(timeout=cfg.interval_min * 60):
                    return
                continue

            log_path = log_dir / f"{int(time.time())}.log"
            self.notifier.emit(Event(role=role, kind="started", message=f"cli={cfg.cli}"))

            run = supervise(
                cli=cfg.cli,
                args=cfg.args,
                cwd=self.target_path,
                env=None,
                stall_seconds=cfg.stall_min * 60,
                total_seconds=cfg.total_min * 60,
                log_path=log_path,
                shutdown_event=self.shutdown_event,
                stdin_input=prompt,
            )

            self._emit_outcome(role, run)

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


def _role_has_work(target_config: TargetConfig, cfg: AgentConfig) -> bool:
    """Cheaply decide whether a role should spend an LLM run."""
    trigger = cfg.trigger
    if trigger is None:
        return True

    for label in trigger.issue_labels:
        if has_open_issue_with_label(target_config.target_repo, label):
            return True
    for label in trigger.pr_labels:
        if has_open_pr_with_label(target_config.target_repo, label):
            return True
    return False


def _no_work_message(cfg: AgentConfig) -> str:
    trigger = cfg.trigger
    if trigger is None:
        return "no trigger configured"

    labels: list[str] = []
    labels.extend(f"issue:{label}" for label in trigger.issue_labels)
    labels.extend(f"pr:{label}" for label in trigger.pr_labels)
    if not labels:
        return "empty trigger"
    return f"no matching work for {', '.join(labels)}"


__all__ = ["Orchestrator"]
