# Agentry Design

Agentry is designed to be a small supervisor around powerful coding agents, not
a second project-management brain. The durable system of record is GitHub:
issues, labels, branches, pull requests, checks, reviews, tags, and releases.

## Product Shape

Agentry turns one repository into a supervised AI product team. The operator
decides when to start it, which roles are enabled, which model or CLI each role
uses, and how much autonomy is allowed. Agentry then runs one work item per role
cycle and exits that role process cleanly.

The default experience is intentionally local:

- no hosted control plane
- no hidden daemon
- no background token burn after a reboot or closed terminal
- no global machine state beyond ordinary dependencies

## Core Design Principles

- Keep GitHub as the queue. Labels are easy to audit, easy to fix manually, and
  survive local crashes.
- Keep role prompts deterministic. A role gets one queue item, performs one
  workflow, writes labels/comments/branches, and exits.
- Keep Agentry core small. Project policy belongs in `docs/ai/roles/*.md` and
  `agentry/config.yml`, not hard-coded in framework logic.
- Prefer explicit operator gates for dangerous transitions. Researcher and
  Release are disabled by default; merge behavior stays controlled by the
  target repo and operator policy.
- Treat local state as supervision state only. Logs and sessions explain what
  happened; GitHub remains the durable workflow truth.
- Be cross-platform. Windows and Linux start scripts, process handling, npm
  shim resolution, and path behavior are first-class.

## Workflow Design

The standard workflow is:

```text
ready-for-design issue
  -> architect
  -> ready-for-implementation issue
  -> implementer
  -> ready-for-test issue
  -> tester
  -> pr-open issue + ready-for-review PR
  -> reviewer
  -> agent-approved PR
  -> release, when enabled
```

Each role watches only its configured input labels. If no matching label exists,
Agentry skips the LLM process entirely. PR-triggered roles can also wait for
checks to settle or pass before they spawn, which prevents Reviewers from
spending a full run just to discover that CI is still pending.

Before a role starts, Agentry writes a bounded work packet with trigger labels,
current GitHub candidates, recent session summaries, and context rules. The role
receives the packet path in its prompt. This makes the first model action
deterministic and small: read the packet, verify current truth, then inspect
only the files/log tails needed for one item.

## Branch And PR Design

Standard roles share one feature branch per issue, normally
`feature/<id>-<slug>`. Implementer and Tester reset clean local branches from
the pushed remote branch before rebasing. Reviewer also repairs stale PR
branches with a clean rebase on `origin/main` before approval.

When multiple PRs touch files listed in `merge_sensitive_paths`, Reviewer runs a
simple merge train. The oldest matching PR can proceed. Newer matching PRs get
`merge-train-waiting`, drop `ready-for-review`, and retry after the older PR
merges. This avoids approving a pile of PRs that all become conflicted after the
first merge.

## Runtime Design

Every role has one session file under `agentry/state/sessions/`. It records
state, PID, log path, timestamps, token usage, duration, and exit reason. A live
`running` PID blocks a duplicate role launch. A missing PID is marked `stale` on
the next start and no longer blocks progress.

Role stdout goes to `agentry/logs/<role>/<timestamp>.log`. Runtime files are
ignored by the generated `agentry/.gitignore` and should not be committed.

Token budgets are visibility controls, not hard stop rules. The design reduces
waste by preventing unnecessary launches and oversized context before the role
starts. Once a role is running, the supervisor still uses check-ins and timeout
policy rather than killing purely because a token budget was exceeded.

## Release Design

Agentry releases are GitHub tags/releases. Target repositories do not float to
mutable `main`; their start scripts pin a specific tag or commit. To upgrade a
target, update the pinned ref in `agentry/start.ps1` and `agentry/start.sh`,
stop any running Agentry process, and run the wrapper with
`AGENTRY_FORCE_INSTALL=1`.
