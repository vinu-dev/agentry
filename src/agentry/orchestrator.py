"""Orchestrator: spawns one forever-loop per declared role.

Each role thread:
  1. Builds the framework's generic prompt (or uses the per-role config prompt).
  2. Spawns the configured CLI as a subprocess in the target's working tree.
  3. Supervises with stall + total timeouts.
  4. Logs the outcome to Discord (if configured).
  5. Sleeps ``interval_min`` minutes, repeats.

Threads are daemons. Main thread waits on a single ``shutdown_event`` that
gets set by SIGTERM/SIGINT (caught at the CLI layer). On shutdown, role
threads finish their current sleep, refuse to spawn another subprocess,
and exit. In-flight subprocesses are killed via the supervisor's interrupt
path.

Restart policy: if a role thread crashes (unhandled exception in our code),
the orchestrator logs and respawns it. We never want a single role bug to
silently take down the whole pipeline.

Logs and runtime state for each invocation live INSIDE the target repo at
``<target>/.agentry/logs/<role>/<timestamp>.log``. This keeps each target's
activity history with the target itself; nothing host-level except the
operator's secret ``.env``.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from agentry.config import AgentConfig, TargetConfig, target_logs_dir
from agentry.notify import DiscordNotifier, Event
from agentry.prompt import make_prompt
from agentry.supervisor import ExitReason, supervise

logger = logging.getLogger(__name__)


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
        """Spawn one daemon thread per declared role and return immediately."""
        all_roles = sorted(self.target_config.agents.keys())
        for role, cfg in self.target_config.agents.items():
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
        """Block until shutdown_event is set, then drain threads briefly."""
        try:
            while not self.shutdown_event.is_set():
                # Wait in short chunks so SIGINT can interrupt promptly.
                self.shutdown_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt; shutting down")
            self.shutdown_event.set()

        # Give role threads a moment to exit. They're daemons, so the
        # process will exit even if some are stuck.
        deadline = time.monotonic() + 30.0
        for t in self._threads:
            remaining = max(0.1, deadline - time.monotonic())
            t.join(timeout=remaining)

    def shutdown(self) -> None:
        """Signal all role threads to stop. Idempotent."""
        self.shutdown_event.set()

    # ----- internals -----

    def _role_loop_with_recovery(
        self,
        role: str,
        cfg: AgentConfig,
        all_roles: list[str],
    ) -> None:
        """Wrapper that respawns the inner loop if it crashes."""
        consecutive_crashes = 0
        while not self.shutdown_event.is_set():
            try:
                self._role_loop(role, cfg, all_roles)
                return  # normal exit (only possible on shutdown)
            except Exception:  # noqa: BLE001 — we want truly any error
                consecutive_crashes += 1
                logger.exception("role %s crashed (#%d); restarting", role, consecutive_crashes)
                self.notifier.emit(
                    Event(
                        role=role,
                        kind="thread-crashed",
                        message=f"role thread crashed (#{consecutive_crashes}); orchestrator restarting it",
                        critical=True,
                    )
                )
                if consecutive_crashes >= 5:
                    logger.error("role %s crashed 5+ times; giving up", role)
                    return
                if self.shutdown_event.wait(timeout=min(60 * consecutive_crashes, 600)):
                    return

    def _role_loop(self, role: str, cfg: AgentConfig, all_roles: list[str]) -> None:
        """Run the role until shutdown.

        On each iteration, build the prompt, spawn the CLI, supervise, log,
        sleep. The whole thing runs synchronously inside this thread — no
        nested concurrency, much easier to reason about.

        Prompt resolution: per-role ``cfg.prompt`` takes precedence if set;
        otherwise the framework's generic template is synthesized.
        """
        prompt = cfg.prompt if cfg.prompt else make_prompt(role, all_roles)
        log_dir = target_logs_dir(self.target_path) / role
        log_dir.mkdir(parents=True, exist_ok=True)

        while not self.shutdown_event.is_set():
            log_path = log_dir / f"{int(time.time())}.log"

            self.notifier.emit(Event(role=role, kind="started", message=f"cli={cfg.cli}"))

            run = supervise(
                cli=cfg.cli,
                args=cfg.args,
                cwd=self.target_path,
                env=None,  # inherit; .env is loaded into our env at startup
                stall_seconds=cfg.stall_min * 60,
                total_seconds=cfg.total_min * 60,
                log_path=log_path,
                shutdown_event=self.shutdown_event,
                stdin_input=prompt,
            )

            self._emit_outcome(role, run)

            if run.reason == ExitReason.INTERRUPTED:
                return  # shutdown requested

            sleep_seconds = cfg.interval_min * 60
            if self.shutdown_event.wait(timeout=sleep_seconds):
                return

    def _emit_outcome(self, role: str, run) -> None:
        """Send a Discord event describing how this iteration ended."""
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


__all__ = ["Orchestrator"]
