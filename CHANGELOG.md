# Changelog

All notable Agentry release changes are recorded here.

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

