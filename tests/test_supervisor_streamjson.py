"""Tests for the stream-JSON helpers in supervisor.py.

The full end-to-end stream-JSON path (spawning claude, sending check-ins,
parsing replies) is exercised by the integration smoke test against a real
target repo. These unit tests cover the parsers and helpers so regressions
are caught fast.
"""

from __future__ import annotations

import json

from agentry.supervisor import (
    _STATUS_RE,
    _extract_result_from_event,
    _extract_text_from_event,
    _is_streamjson_mode,
    _parse_minutes,
    _wrap_user_message,
)


class TestIsStreamJsonMode:
    def test_detects_equals_form(self):
        assert _is_streamjson_mode(["-p", "--input-format=stream-json", "--verbose"])

    def test_detects_separated_form(self):
        assert _is_streamjson_mode(["-p", "--input-format", "stream-json"])

    def test_legacy_text_mode_returns_false(self):
        assert not _is_streamjson_mode(["-p", "--dangerously-skip-permissions"])

    def test_codex_args_return_false(self):
        assert not _is_streamjson_mode(["exec", "--dangerously-bypass-approvals-and-sandbox"])

    def test_empty_args(self):
        assert not _is_streamjson_mode([])

    def test_unrelated_input_format_value_ignored(self):
        # If someone passes --input-format=text (the default), don't activate streamjson.
        assert not _is_streamjson_mode(["--input-format=text"])
        assert not _is_streamjson_mode(["--input-format", "text"])


class TestWrapUserMessage:
    def test_produces_valid_json_line(self):
        out = _wrap_user_message("hello world")
        assert out.endswith("\n")
        payload = json.loads(out)
        assert payload["type"] == "user"
        assert payload["message"]["role"] == "user"
        assert payload["message"]["content"][0]["type"] == "text"
        assert payload["message"]["content"][0]["text"] == "hello world"

    def test_handles_unicode(self):
        out = _wrap_user_message("→ check ✓ status")
        payload = json.loads(out)
        assert payload["message"]["content"][0]["text"] == "→ check ✓ status"

    def test_handles_quotes_and_newlines(self):
        text = 'multiline\n"with quotes"\nand more'
        out = _wrap_user_message(text)
        payload = json.loads(out)
        assert payload["message"]["content"][0]["text"] == text


class TestExtractTextFromEvent:
    def test_assistant_text_block(self):
        evt = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "STATUS:WORKING"}],
                },
            }
        )
        assert _extract_text_from_event(evt) == "STATUS:WORKING"

    def test_assistant_thinking_only_returns_none(self):
        evt = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "hmm..."}],
                },
            }
        )
        assert _extract_text_from_event(evt) is None

    def test_assistant_mixed_blocks_returns_text_only(self):
        evt = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "reasoning"},
                        {"type": "text", "text": "visible reply"},
                        {"type": "tool_use", "id": "x", "name": "Bash", "input": {}},
                    ],
                },
            }
        )
        assert _extract_text_from_event(evt) == "visible reply"

    def test_system_event_returns_none(self):
        evt = json.dumps({"type": "system", "subtype": "init"})
        assert _extract_text_from_event(evt) is None

    def test_tool_use_event_returns_none(self):
        evt = json.dumps({"type": "tool_use", "name": "Bash"})
        assert _extract_text_from_event(evt) is None

    def test_invalid_json_returns_none(self):
        assert _extract_text_from_event("not json at all") is None
        assert _extract_text_from_event("{partial") is None

    def test_empty_input_returns_none(self):
        assert _extract_text_from_event("") is None
        assert _extract_text_from_event("   \n") is None


class TestExtractResultFromEvent:
    def test_success_result(self):
        evt = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "terminal_reason": "completed",
            }
        )
        result = _extract_result_from_event(evt)
        assert result is not None
        assert result.exit_code == 0
        assert result.error_detail is None

    def test_error_result(self):
        evt = json.dumps(
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "api_error_status": "rate_limited",
            }
        )
        result = _extract_result_from_event(evt)
        assert result is not None
        assert result.exit_code == 1
        assert result.error_detail == "rate_limited"

    def test_non_result_returns_none(self):
        assert _extract_result_from_event(json.dumps({"type": "assistant"})) is None
        assert _extract_result_from_event("not json") is None


class TestStatusRegex:
    def test_status_working(self):
        m = _STATUS_RE.search("STATUS:WORKING")
        assert m is not None
        assert m.group(1).upper() == "WORKING"

    def test_status_done(self):
        m = _STATUS_RE.search("Some preamble. STATUS:DONE\nMore text.")
        assert m is not None
        assert m.group(1).upper() == "DONE"

    def test_status_blocked_with_reason(self):
        m = _STATUS_RE.search("STATUS:BLOCKED missing spec")
        assert m is not None
        assert m.group(1).upper() == "BLOCKED"
        assert "missing spec" in m.group(2)

    def test_status_needmoretime_with_minutes(self):
        m = _STATUS_RE.search("STATUS:NEEDMORETIME 30")
        assert m is not None
        assert m.group(1).upper() == "NEEDMORETIME"
        assert "30" in m.group(2)

    def test_case_insensitive(self):
        m = _STATUS_RE.search("status:working")
        assert m is not None
        assert m.group(1).upper() == "WORKING"

    def test_first_status_wins(self):
        m = _STATUS_RE.search("STATUS:WORKING\nlater STATUS:DONE")
        assert m is not None
        assert m.group(1).upper() == "WORKING"

    def test_no_status_returns_none(self):
        assert _STATUS_RE.search("just a regular response") is None


class TestParseMinutes:
    def test_pure_integer(self):
        assert _parse_minutes("30") == 30

    def test_integer_with_text(self):
        assert _parse_minutes("about 15 more") == 15

    def test_caps_at_240(self):
        assert _parse_minutes("9999") == 240

    def test_clamps_to_min_1(self):
        # "0 minutes" gets clamped to 1.
        assert _parse_minutes("0") == 1

    def test_no_digits(self):
        assert _parse_minutes("a while longer please") is None

    def test_none_input(self):
        assert _parse_minutes(None) is None

    def test_empty_string(self):
        assert _parse_minutes("") is None
