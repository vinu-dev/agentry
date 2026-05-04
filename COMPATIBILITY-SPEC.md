# Agentry Compatibility Specification

This is the contract a target repository must satisfy to be operated by
Agentry.

Agentry is deliberately small: it starts configured role CLIs, supervises them,
writes logs/session state, exposes local status/config controls, and relies on
GitHub plus role rule files for the product workflow.

## 1. Target Layout

A target repo can run Agentry when it contains:

```text
agentry/
  config.yml
  start.ps1
  start.sh
  .env.example
  .gitignore
  README.md
docs/ai/roles/
  <role>.md
```

`scripts/add-to-target.ps1` and `scripts/add-to-target.sh` create the standard
layout. Targets may commit:

- `agentry/config.yml`
- `agentry/start.ps1`
- `agentry/start.sh`
- `agentry/.env.example`
- `agentry/.gitignore`
- `agentry/README.md`
- `docs/ai/roles/*.md`

Targets must not commit:

```text
agentry/.env
agentry/.venv/
agentry/logs/
agentry/state/
agentry/worktrees/
```

The generated `agentry/.gitignore` covers those local paths.

## 2. Config Schema

`agentry/config.yml` is a YAML mapping:

```yaml
target_repo: owner/repo
mode: pipeline
isolate_worktrees: true

automation:
  auto_merge: false
  stop_when_queue_empty: false

research:
  allow_create_issues: false
  max_open_ready_for_design: 3

labels:
  logical-name: actual-github-label

agents:
  role_name:
    enabled: true
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "gpt-5.4"]
    interval_min: 5
    total_min: 30
    stall_min: 30
    max_sessions: 1
    token_budget: 25000
    checkin_response_seconds: 90
    trigger:
      issue_labels: ["ready-for-design"]
      pr_labels: []
    prompt: |
      Optional full role prompt. If omitted, Agentry uses the generic prompt.

sensitive_paths:
  - "**/auth/**"
  - "**/.github/workflows/**"
```

Required top-level fields:

- `target_repo`: GitHub repo in `owner/repo` form.
- `agents`: one or more roles.

Optional top-level fields:

- `mode`: `manual`, `pipeline`, or `autonomous`. Default is `pipeline`.
- `isolate_worktrees`: run each role in its own git worktree when possible.
  Existing role worktrees must be clean before reuse; dirty worktrees are
  skipped with a preparation error.
- `automation`: operator-level controls. `auto_merge` and
  `stop_when_queue_empty` are configuration flags for current/future workflows.
- `research`: controls whether Researcher may create new GitHub issues.
- `labels`: target-specific label names to create with `doctor --init-labels`.
- `sensitive_paths`: policy globs for role rule files to consult.

Required per-role fields:

- `cli`: binary name or absolute path.
- `interval_min`: minutes between role invocations.
- `total_min`: max subprocess runtime.
- `stall_min`: max silence on stdout before watchdog action.

Optional per-role fields:

- `enabled`: when false, the role is ignored.
- `args`: list of CLI args passed before stdin prompt.
- `run_on_start`: when false, wait `interval_min` before first run.
- `max_sessions`: must be `1` in this release.
- `token_budget`: soft per-run budget recorded in session state.
- `checkin_response_seconds`: wait time for a STATUS reply in stream-JSON mode.
  Fresh stream-JSON activity during that window is treated as progress even when
  the agent cannot answer with `STATUS:` immediately.
- `trigger`: cheap GitHub label gates checked before starting an LLM process.
- `prompt`: full prompt sent to the CLI over stdin. If absent, Agentry builds a
  generic prompt pointing the role at `docs/ai/roles/<role>.md`.

Role names must be non-empty and must not contain spaces or `/`.

## 3. Run Modes

| Mode | Behavior |
|------|----------|
| `manual` | No role loops are started. Useful for inspection and safe pause. |
| `pipeline` | Default. Existing GitHub labels move through the pipeline. Researcher is blocked from creating new issues. |
| `autonomous` | Pipeline plus Researcher, but only when `research.allow_create_issues: true` and researcher is enabled. |

## 4. Role Rule Files

Each declared role should have:

```text
docs/ai/roles/<role>.md
```

For the standard roles, Agentry falls back to bundled role files if the target
does not provide one. Custom roles beyond the bundled roster must provide their
own rule file.

A good role file describes:

- trigger: which labels, schedule, or repo state produce work
- steps: what the agent should do per item
- output: which label, PR, branch, or artifact advances the lifecycle
- constraints: project conventions and sensitive areas
- failure modes: what to label or comment when the role cannot proceed

The framework does not interpret role files. The spawned CLI reads and follows
them.

## 5. GitHub Auth

At least one GitHub auth path must work:

- `GITHUB_TOKEN` is set in `agentry/.env`, or
- `gh` is authenticated and can reach `target_repo`.

For unattended operation, `GITHUB_TOKEN` is recommended. Use a fine-grained PAT
restricted to the target repo with:

- contents: read/write
- issues: read/write
- pull requests: read/write
- metadata: read

`agentry doctor --target .` fails if neither auth path is available.

## 6. Labels

`agentry doctor --target . --init-labels` creates:

- bundled standard lifecycle labels
- bundled standard failure labels
- any label names listed in `agentry/config.yml` under `labels`

The standard labels are:

- `ready-for-design`
- `ready-for-implementation`
- `ready-for-test`
- `tests-failed`
- `ready-for-review`
- `agent-approved`
- `blocked`
- `merge-conflict`
- `needs-rebase`
- `needs-hardware-verification`

Non-standard role files may use more labels. Add those names to the config
`labels` mapping so doctor can create them for fresh repos.

## 7. Start Scripts And Versioning

Each target runs Agentry through:

```text
agentry/start.ps1
agentry/start.sh
```

With no arguments, the scripts create/reuse `agentry/.venv/`, run doctor, then
start foreground role loops.

With arguments, the scripts create/reuse the venv and invoke the repo-local
Agentry CLI without starting role loops:

```powershell
.\agentry\start.ps1 gui --target .
.\agentry\start.ps1 configure --target . --defaults
.\agentry\start.ps1 stop --target . --all
```

```bash
./agentry/start.sh gui --target .
./agentry/start.sh configure --target . --defaults
./agentry/start.sh stop --target . --all
```

On first run, the script installs Agentry from the GitHub ref embedded in the
script. The add-to-target scripts stamp this ref from the selected Agentry
branch when possible, so a target repo does not silently float to mutable
`main`.

Operators may override the install ref intentionally:

```bash
AGENTRY_INSTALL_REF=<branch-tag-or-commit> ./agentry/start.sh
```

After changing the install ref, delete `agentry/.venv/` and rerun the start
script to recreate the environment.

## 8. Runtime Logs And State

Agentry writes subprocess logs to:

```text
agentry/logs/<role>/<timestamp>.log
```

Agentry writes role session records to:

```text
agentry/state/sessions/<role>.json
```

Session records include role state, PID, timestamps, log path, exit reason,
duration, token usage, and token budget status.

Role prompts may also write continuity notes under:

```text
agentry/state/
```

GitHub remains the source of truth for issues, PRs, labels, branches, and
review state. Local state should only help supervision and role continuity.

## 9. Stop And Crash Recovery

Agentry is foreground by default. Press Ctrl-C, close the terminal, or reboot to
stop it. No background service keeps running unless the operator creates one.

Stop commands:

```bash
agentry stop --target . ROLE
agentry stop --target . --all
```

Stop is conservative. Agentry kills a PID only when the corresponding session is
still marked `running` and the PID is alive. Completed or stale records are not
used to kill processes.

On the next start after a crash or reboot, old `running` records whose PIDs no
longer exist are marked `stale`, then the role may run again.

## 10. Cross-Platform Expectations

Agentry supports Windows and Linux.

- Use `agentry/start.ps1` on Windows.
- Use `agentry/start.sh` on Linux.
- CLI names are resolved with npm shim fallbacks, so `npx`/`npx.cmd` and similar
  copied configs work across platforms.
- Hardware or OS-specific tools belong in project role files and target setup,
  not in Agentry core.

## 11. Extensibility

Agentry does not bake in a fixed roster. Any repo may declare any number of
roles in `agentry/config.yml`.

Common software repos may use:

```text
researcher -> architect -> implementer -> tester -> reviewer -> release
```

Regulated or security-heavy repos can add roles such as:

```text
risk_analyst
quality_reviewer
cybersecurity_reviewer
regulatory_reviewer
traceability_tracker
security_reviewer
docs_writer
performance_tester
```

The framework behavior is the same for every roster: one supervised loop per
enabled role allowed by the current run mode.

## 12. Doctor Expectations

`agentry doctor --target .` checks:

1. target config loads and validates
2. role rule files exist, target-specific or bundled
3. configured CLIs are discoverable on `PATH`
4. `agentry/.env` exists
5. GitHub auth is available through `GITHUB_TOKEN` or `gh`
6. `gh` can reach the configured target repo, when available

Exit code:

- `0`: pass
- `2`: fail

Warnings are printed for optional or recoverable gaps, such as a missing CLI
that only affects one role.
