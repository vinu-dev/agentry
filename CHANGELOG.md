# Changelog

All notable Agentry release changes are recorded here.

## v0.1.1 - 2026-05-05

Token-governance and deterministic review-gating release.

### Added

- `context` config block for bounded per-run work packets, candidate limits,
  log-tail guidance, and diff-size guidance.
- Generated `agentry/state/workpackets/<role>.md` files before role spawn so
  agents start from compact queue/session context instead of rediscovering it
  with broad scans.
- `trigger.pr_check_gate` for PR-triggered roles. The standard Reviewer now
  uses `settled`, which avoids launching an LLM while all matching PR checks
  are still pending, queued, or running.
- GitHub helper functions for bounded issue/PR candidate discovery and coarse
  PR check-state classification.

### Changed

- Standard Reviewer prompts now read the work packet first, use bounded log
  tails, inspect PR file lists before diffs, and avoid full diffs above the
  configured line guidance.
- Work packets are written with an exact byte cap on Windows and Linux.

### Notes

- Token budgets remain warnings, not automatic kill triggers. This release
  prevents avoidable launches and oversized context; it does not kill active
  roles just because a budget is exceeded.
- If GitHub check state is unavailable because of a transient CLI/API failure,
  the PR gate allows the role to run rather than deadlocking the queue.

## v0.1.0 - 2026-05-05

First supported alpha release.

### Added

- Per-target `agentry/` installation model with repo-local virtualenvs.
- Windows and Linux target start scripts.
- Standard six-role workflow: Researcher, Architect, Implementer, Tester,
  Reviewer, and Release.
- GitHub-label queue model for issues and pull requests.
- Role supervision with session files, stdout logs, timeout handling, and
  conservative stop behavior.
- Stream-JSON check-ins for CLIs that keep stdin open.
- Usage-limit backoff for known CLI limit messages.
- Isolated per-role git worktrees with dirty-worktree protection.
- Wrapper subcommands that reuse an existing venv for `status`, `doctor`,
  `configure`, and `gui` instead of reinstalling into a live environment.
- Tester PR body-file creation to avoid shell quoting problems.
- Reviewer clean-rebase repair before approval.
- Merge train support for high-conflict shared paths through
  `merge_sensitive_paths` and `merge-train-waiting`.
- Local dashboard for status, logs, stop controls, and common configuration.
- Standard and regulated-software examples.

### Release Notes

This release is intended for supervised operation. It does not install a
background service, and it does not publish to PyPI yet. Target repositories pin
Agentry by Git tag or commit in their generated start scripts.
