"""Tests for the Discord notifier."""

from __future__ import annotations

import time

import httpx

from agentry.notify import DiscordNotifier, Event, _format_events


class TestFormatEvents:
    def test_renders_role_kind_message(self):
        events = [Event(role="architect", kind="started", message="cli=claude")]
        out = _format_events(events)
        assert "architect" in out
        assert "started" in out
        assert "cli=claude" in out

    def test_critical_events_get_marker(self):
        events = [Event(role="architect", kind="stalled", message="silent 5m", critical=True)]
        out = _format_events(events)
        assert "‼" in out

    def test_truncates_huge_payloads(self):
        events = [Event(role="x", kind="y", message="z" * 5000)]
        out = _format_events(events)
        assert len(out) < 2000
        assert "truncated" in out


class TestDiscordNotifier:
    def test_dropped_when_no_webhook(self):
        n = DiscordNotifier(webhook_url=None, flush_seconds=1)
        n.start()
        try:
            n.emit(Event(role="r", kind="k", message="m"))
            time.sleep(2.0)  # allow one flush cycle
        finally:
            n.stop(timeout=2.0)
        assert n._dropped == 1

    def test_emit_does_not_raise_on_full_queue(self):
        """Even under pressure, emit() should never raise."""
        n = DiscordNotifier(webhook_url=None, flush_seconds=10)
        # Don't start the worker; the queue will keep growing but emit must
        # remain non-blocking and exception-free.
        for i in range(10000):
            n.emit(Event(role="r", kind="k", message=str(i)))

    def test_flushes_via_mock_transport(self):
        """A successful POST should not increment dropped."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            return httpx.Response(204)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with DiscordNotifier(
                webhook_url="https://discord.test/webhooks/x",
                flush_seconds=1,
                client=client,
            ) as n:
                n.emit(Event(role="architect", kind="started", message="cli=claude"))
                time.sleep(2.0)

            assert "body" in captured
            assert n._dropped == 0
        finally:
            client.close()

    def test_handles_429_rate_limit(self):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, json={"retry_after": 1}))
        )
        try:
            with DiscordNotifier(
                webhook_url="https://discord.test/webhooks/x",
                flush_seconds=1,
                client=client,
            ) as n:
                n.emit(Event(role="r", kind="k", message="m"))
                time.sleep(2.0)
            # Rate-limited events are dropped, not retried, in v0.1.
            assert n._dropped >= 1
        finally:
            client.close()

    def test_critical_event_flushes_immediately(self):
        """A critical event should not wait for the full flush window."""
        flushes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            flushes.append(int(time.monotonic() * 1000))
            return httpx.Response(204)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with DiscordNotifier(
                webhook_url="https://discord.test/webhooks/x",
                flush_seconds=30,  # long flush window
                client=client,
            ) as n:
                start = time.monotonic()
                n.emit(Event(role="r", kind="k", message="m", critical=True))
                # Wait briefly — should flush well within flush_seconds.
                deadline = time.monotonic() + 5.0
                while not flushes and time.monotonic() < deadline:
                    time.sleep(0.1)
            elapsed = time.monotonic() - start
            assert flushes, "no flush occurred for critical event"
            assert elapsed < 10.0
        finally:
            client.close()
