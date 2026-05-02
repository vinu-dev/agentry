"""Discord webhook notifier with batching and rate-limit safety.

Discord enforces 30 messages/minute/webhook. A chatty role pipeline can
exceed that easily. The notifier accumulates events for ``flush_seconds``
and emits at most one message per flush as a digest; critical events
(quarantine, budget exhausted) bypass the batch and fire immediately.

If the webhook is misconfigured (no URL, network error, 4xx response),
the notifier logs and drops events — notifications are best-effort, never
block the orchestrator.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Queue

import httpx

logger = logging.getLogger(__name__)


# Discord rejects message bodies larger than 2000 chars, but we leave headroom.
_MAX_DISCORD_BODY = 1800
_DISCORD_TIMEOUT = 10.0


@dataclass
class Event:
    """A single notification event."""

    role: str
    kind: str  # e.g. "started", "exited", "stalled", "timed_out"
    message: str
    critical: bool = False  # bypass the batch
    timestamp: float = field(default_factory=time.time)


class DiscordNotifier:
    """Background notifier that batches events to a Discord webhook.

    Thread-safe. Call :py:meth:`emit` from any thread; one writer thread
    drains the queue and flushes to Discord every ``flush_seconds`` (or
    immediately for critical events).

    Use as a context manager or call :py:meth:`stop` explicitly to drain
    pending events on shutdown.
    """

    def __init__(
        self,
        webhook_url: str | None,
        *,
        flush_seconds: int = 60,
        client: httpx.Client | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.flush_seconds = max(1, flush_seconds)
        self._queue: Queue[Event] = Queue()
        self._stop = threading.Event()
        self._client = client or httpx.Client(timeout=_DISCORD_TIMEOUT)
        self._owns_client = client is None
        self._thread: threading.Thread | None = None
        self._dropped = 0  # events dropped because webhook is misconfigured

    def __enter__(self) -> "DiscordNotifier":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="notifier")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._thread = None
        if self._owns_client:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        if self._dropped:
            logger.warning("notifier dropped %d events (webhook unreachable)", self._dropped)

    def emit(self, event: Event) -> None:
        """Enqueue an event. Never blocks. Never raises."""
        try:
            self._queue.put_nowait(event)
        except Exception:  # noqa: BLE001 — emit must not break callers
            logger.exception("failed to enqueue event %r", event)

    # ----- internal -----

    def _run(self) -> None:
        while not self._stop.is_set():
            buffer: list[Event] = []
            critical_seen = False
            deadline = time.monotonic() + self.flush_seconds

            # Block for up to flush_seconds on the first event, then drain.
            timeout = self.flush_seconds
            while time.monotonic() < deadline and not self._stop.is_set():
                try:
                    ev = self._queue.get(timeout=max(0.1, timeout))
                except Empty:
                    break
                buffer.append(ev)
                if ev.critical:
                    critical_seen = True
                    # Critical bypasses the batch — flush right away.
                    break
                # Drain anything else immediately available.
                while True:
                    try:
                        buffer.append(self._queue.get_nowait())
                        if buffer[-1].critical:
                            critical_seen = True
                    except Empty:
                        break
                if critical_seen:
                    break
                timeout = deadline - time.monotonic()

            if buffer:
                self._flush(buffer)

        # Drain on shutdown so we don't lose final events.
        remaining: list[Event] = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
            except Empty:
                break
        if remaining:
            self._flush(remaining)

    def _flush(self, events: list[Event]) -> None:
        if not self.webhook_url:
            self._dropped += len(events)
            return
        body = _format_events(events)
        try:
            r = self._client.post(self.webhook_url, json={"content": body})
            if r.status_code == 429:
                logger.warning("discord rate-limited; dropping %d events", len(events))
                self._dropped += len(events)
                return
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("discord webhook failed: %s; dropping %d events", e, len(events))
            self._dropped += len(events)


def _format_events(events: list[Event]) -> str:
    """Render a digest of events fitting in a Discord message."""
    lines = []
    for ev in events:
        prefix = "‼️ " if ev.critical else ""
        lines.append(f"{prefix}`{ev.role}`: **{ev.kind}** — {ev.message}")
    body = "\n".join(lines)
    if len(body) > _MAX_DISCORD_BODY:
        # Truncate from the middle; keep first and last messages visible.
        keep = _MAX_DISCORD_BODY // 2 - 50
        body = body[:keep] + "\n…(truncated)…\n" + body[-keep:]
    return body


__all__ = ["DiscordNotifier", "Event"]
