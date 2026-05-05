# Changelog

All notable Agentry release changes are recorded here.

## v0.1.7 - 2026-05-05

CI-pending queue guidance release.

### Fixed

- Work packets now distinguish PR-triggered roles from issue-triggered roles
  when GitHub checks are pending.
- PR-triggered roles still leave PR labels unchanged when required checks are
  pending, relying on Agentry's interval retry.
- Issue-triggered roles that open or update a PR are now told to advance the
  issue/PR queue after local validation passes and rely on downstream
  `pr_check_gate` settings to defer review until checks settle. This prevents a
  locally green Tester run from leaving an unlabeled PR invisible to reviewers.

## v0.1.6 - 2026-05-05

Research backlog guard release.

### Added

- Researcher now has an enforced cheap backlog guard. Agentry counts open
  issues with `research.backlog_labels` before launching the Researcher LLM and
  skips the run when the counted queue is at or above
  `research.max_open_ready_for_design`.
- Targets can include upstream pre-design labels in `research.backlog_labels`
  so regulated flows can count risk-intake issues as design supply without
  repeatedly waking Researcher.

### Fixed

- `research.max_open_ready_for_design` is now an operational scheduler guard,
  not only documentation. This prevents autonomous targets from burning
  Researcher tokens while the design queue is already full.

## v0.1.5 - 2026-05-05

Product-owner Researcher defaults release.

### Changed

- Standard Researcher defaults now describe the role as product-owner discovery,
  with competitor/product research as source material for small, testable
  feature candidates.
- Researcher issue bodies now require source URLs with access dates, a user
  problem, product hypothesis, MVP scope, validation idea, non-copying
  boundaries, rough scope, and out-of-scope.
- README, architecture, design, and standard example docs now explain the
  Researcher intent for new target repositories.

### Notes

- Researcher remains disabled unless the operator explicitly enables
  autonomous issue creation.

## v0.1.4 - 2026-05-05

PR-head worktree synchronization release.

### Fixed

- PR-triggered roles now refresh their isolated worktree to the selected PR
  head before the model starts, so reviewers inspect the files that are actually
  in the pull request instead of a stale `main` checkout.
- Clean existing role worktrees are refreshed to current `origin/main` before
  non-PR role runs. This prevents new issue branches from starting on a stale
  base after earlier PRs merge.

### Notes

- Dirty role worktrees are still skipped rather than reset. Operators must
  commit, move, or remove leftover local edits before Agentry reuses that
  role's worktree.

## v0.1.3 - 2026-05-05

Issue-closing PR body release.

### Changed

- Runtime and Tester prompt contracts now require issue-owned PR bodies to use
  a GitHub closing keyword such as `Closes #<id>`.
- Standard defaults and example docs explain that `pr-open` remains only while
  the PR is alive; GitHub should close the issue automatically on merge.

### Notes

- This prevents merged PRs from leaving their issues open when a role writes
  "Linked issue" instead of a closing keyword.

## v0.1.2 - 2026-05-05

Selected-candidate queue-discipline release.

### Added

- Work packets now name exactly one `Selected Candidate` before each
  label-triggered role starts.
- Prompt contract language that makes the selected candidate the single work
  item for the invocation and treats other queue rows as read-only awareness.
- Tests for trigger-priority selection and PR check-gate-aware selection.

### Changed

- Work packet candidate sections now mark the selected item explicitly.
- Documentation now describes selected-candidate behavior in the README,
  architecture, design, compatibility, watchdog, how-to-use, and example docs.

### Notes

- This release fixes a token-wasting integration behavior where a role could
  inspect or relabel more than one queued item during one run.

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
