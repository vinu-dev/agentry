"""Tests for the framework-supplied generic prompt template."""

from __future__ import annotations

import pytest

from agentry.prompt import (
    GENERIC_PROMPT_TEMPLATE,
    INVOCATION_CONTRACT,
    RUNTIME_CONTRACT,
    build_role_prompt,
    make_prompt,
)


class TestMakePrompt:
    def test_substitutes_role_name(self):
        out = make_prompt("architect", ["researcher", "architect", "implementer"])
        assert "You are the architect" in out
        # Should reference the role's rule file path.
        assert "docs/ai/roles/architect.md" in out

    def test_other_roles_listed_alphabetically(self):
        out = make_prompt("architect", ["researcher", "tester", "architect", "implementer"])
        # Other roles, sorted, comma-separated.
        assert "implementer, researcher, tester" in out

    def test_excludes_self_from_other_roles(self):
        out = make_prompt("architect", ["architect"])
        # Single-role case still produces a coherent prompt.
        assert "You are the architect" in out
        assert "(no other roles configured)" in out

    def test_six_role_standard_roster(self):
        roles = ["researcher", "architect", "implementer", "tester", "reviewer", "release"]
        for role in roles:
            out = make_prompt(role, roles)
            assert f"You are the {role}" in out
            assert f"docs/ai/roles/{role}.md" in out
            # Mentions of other roles should not include self.
            others_section = out.split("are also active: ")[1].split(".\n")[0]
            assert role not in others_section

    def test_empty_role_name_rejected(self):
        with pytest.raises(ValueError, match="role_name"):
            make_prompt("", ["a", "b"])

    def test_empty_roster_rejected(self):
        with pytest.raises(ValueError, match="all_roles"):
            make_prompt("architect", [])

    def test_template_includes_loop_structure(self):
        """The generic prompt must include the loop instructions (find/take/do/move/repeat)."""
        out = make_prompt("architect", ["architect", "implementer"])
        assert "Find work items" in out
        assert "exit immediately with code 0" in out
        assert "Repeat from step 1" in out

    def test_template_mentions_parallelism(self):
        out = make_prompt("architect", ["architect", "implementer"])
        assert "parallel" in out
        assert "concurrently" in out

    def test_template_is_stable(self):
        """Catch accidental edits to the template — this is a load-bearing string."""
        # Sanity check on the template itself.
        assert "{role_name}" in GENERIC_PROMPT_TEMPLATE
        assert "{other_roles}" in GENERIC_PROMPT_TEMPLATE
        assert "docs/ai/roles/{role_name}.md" in GENERIC_PROMPT_TEMPLATE

    def test_runtime_contract_requires_gh_cli_writebacks(self):
        assert "gh` CLI" in RUNTIME_CONTRACT
        assert "Do not use GitHub app connectors" in RUNTIME_CONTRACT
        assert "remove stale state labels" in RUNTIME_CONTRACT
        assert "`blocked`" in RUNTIME_CONTRACT
        assert "`pr-open`" in RUNTIME_CONTRACT
        assert "open PR already" in RUNTIME_CONTRACT
        assert "`agent-approved`" in RUNTIME_CONTRACT
        assert "GitHub refuses self-review" in RUNTIME_CONTRACT

    def test_invocation_contract_requires_immediate_execution(self):
        assert "work order for this run" in INVOCATION_CONTRACT
        assert "Start immediately" in INVOCATION_CONTRACT
        assert "do not ask the" in INVOCATION_CONTRACT

    def test_build_role_prompt_wraps_custom_prompt(self):
        out = build_role_prompt("reviewer", ["reviewer"], "CUSTOM ROLE BODY")
        assert "Agentry Runtime Contract" in out
        assert "Agentry Invocation" in out
        assert "CUSTOM ROLE BODY" in out
        assert "GitHub app connectors" in out
