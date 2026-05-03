"""Generic prompt template synthesized for every role at spawn time.

The framework does NOT let operators or repos write the role's wrapping prompt.
Every role gets the same skeleton, with the role name and other-roles list
substituted in. The actual project-specific work instructions live in the
target repo at `docs/ai/roles/<role>.md`, and the prompt directs the agent
to read that file.

This is the entire role-prompt contract for v0.1. Keep it short and stable —
changes here affect every role in every target.
"""

RUNTIME_CONTRACT = """\
## Agentry Runtime Contract

- Use the shell and the target repo's `gh` CLI for all GitHub reads and
  writebacks (`gh issue`, `gh pr`, `gh label`, etc.).
- Do not use GitHub app connectors, MCP GitHub tools, browser automation, or
  hidden integrations for GitHub writes. They may not have the same repository
  permissions as the operator's `gh` auth.
- After every label, comment, PR, or review writeback, verify the result with
  `gh issue view`, `gh pr view`, or `gh pr list`.
- If a formal `gh pr review` write fails, immediately fall back to `gh pr
  comment` with the same review outcome and then update labels with `gh pr edit`
  / `gh issue edit`.
- Never leave an item in the same trigger label after a completed cycle. Move it
  forward, move it back to a retry label, or mark it blocked with a comment that
  explains the next human or agent action.
"""


GENERIC_PROMPT_TEMPLATE = """\
You are the {role_name} in an autonomous software development pipeline.

How this pipeline works:
  - Multiple roles run in parallel — concurrently with you, the following
    roles are also active: {other_roles}.
  - Each role finds work in its own input state, processes one or more items,
    and moves them to an output state. Roles do not coordinate directly;
    they work concurrently.
  - On each invocation you process as many items as you can within your time
    budget, then exit. The orchestrator will respawn you on the next interval.

Your job specifics — including which labels signal work for you, what to
produce, and which label to apply when done — are defined in:

    docs/ai/roles/{role_name}.md

Read that file and follow it exactly.

General loop:
  1. Find work items in your input state (per the rule file).
  2. If none exist, exit immediately with code 0.
  3. Otherwise take the oldest item.
  4. Do the work as described in docs/ai/roles/{role_name}.md.
  5. Move the item to your output state (relabel, open PR, etc.).
  6. Repeat from step 1.

If docs/ai/roles/{role_name}.md doesn't exist, exit with code 1.
"""


def make_prompt(role_name: str, all_roles: list[str]) -> str:
    """Build the generic prompt for ``role_name`` given the full role roster.

    Args:
        role_name: The role being spawned.
        all_roles: All declared roles in the target's config (including
            ``role_name`` itself; this function filters it out for the
            "other roles" enumeration).

    Returns:
        The substituted prompt string ready to pass to the LLM CLI.
    """
    if not role_name:
        raise ValueError("role_name must be non-empty")
    if not all_roles:
        raise ValueError("all_roles must contain at least the role itself")

    others = sorted(r for r in all_roles if r != role_name)
    other_roles = ", ".join(others) if others else "(no other roles configured)"

    return GENERIC_PROMPT_TEMPLATE.format(
        role_name=role_name,
        other_roles=other_roles,
    )


def build_role_prompt(
    role_name: str,
    all_roles: list[str],
    configured_prompt: str | None = None,
) -> str:
    """Build the final prompt sent to a role process.

    The runtime contract is injected even when a target provides a custom
    prompt. That keeps critical operational behavior (especially GitHub
    writeback semantics) consistent across targets and model providers.
    """
    base = configured_prompt if configured_prompt is not None else make_prompt(role_name, all_roles)
    return f"{RUNTIME_CONTRACT.strip()}\n\n{base.strip()}\n"
