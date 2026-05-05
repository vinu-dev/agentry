# `agentry/` - Local Agentry Installation

This folder is the repo-local Agentry dependency for this target repository.
Each target repo gets its own copy.

## What Is In Here

| Path | Purpose | Commit? |
|------|---------|---------|
| `config.yml` | Role roster, model/CLI assignment, timeouts, run mode | yes |
| `start.ps1` / `start.sh` | Entry points for start, GUI, configure, stop | yes |
| `.env.example` | Secrets template | yes |
| `.gitignore` | Ignores local runtime files | yes |
| `.env` | Real secrets | no |
| `.venv/` | Repo-local Agentry Python venv | no |
| `logs/` | Per-role stdout logs | no |
| `state/` | Runtime sessions, work packets, and role continuity notes | no |
| `worktrees/` | Per-role git worktrees when enabled | no |

## Role Rules

Project-specific role rules live here:

```text
docs/ai/roles/
  researcher.md
  architect.md
  implementer.md
  tester.md
  reviewer.md
  release.md
```

Edit those files for project behavior. The prompts in `agentry/config.yml`
point at them.

If multiple PRs routinely touch the same generated docs, workflow files, or
release files, add those globs to `merge_sensitive_paths` in
`agentry/config.yml`. Reviewer will approve the oldest matching PR and park
newer ones with `merge-train-waiting` until they can rebase after the older
merge.

To reduce token burn, keep the `context` block enabled. Agentry writes bounded
work packets under `agentry/state/workpackets/` before role spawn, and the
standard Reviewer waits for PR checks to settle before launching:

```yaml
context:
  work_packets: true
  max_packet_bytes: 32000

agents:
  reviewer:
    trigger:
      pr_labels: ["ready-for-review", "merge-train-waiting"]
      pr_check_gate: settled
```

Work packets are local runtime files and should not be committed.

## Machine Setup

Run once per machine:

Windows PowerShell:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.ps1 | iex
```

Linux shell:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.sh | bash
```

Then authenticate the LLM CLIs you plan to use:

```bash
claude login
codex login
```

## Configure Without Starting Agents

```powershell
.\agentry\start.ps1 configure --target . --defaults
.\agentry\start.ps1 gui --target .
```

```bash
./agentry/start.sh configure --target . --defaults
./agentry/start.sh gui --target .
```

Default mode is `pipeline`: existing GitHub labels move through the pipeline,
but Researcher does not create new issues. Use `manual` when you want no roles
to start. Use `autonomous` only when Researcher should be allowed to create new
work.

## Start

```powershell
.\agentry\start.ps1
```

```bash
./agentry/start.sh
```

Foreground only. Ctrl-C, closing the terminal, or rebooting stops it. There is
no background service by default.

## Stop

```powershell
.\agentry\start.ps1 stop --target . --all
```

```bash
./agentry/start.sh stop --target . --all
```

Stop is conservative: Agentry kills only currently running session PIDs, not
completed or stale records.

Completed sessions clear their recorded PID before status/dashboard rendering,
so a visible PID means there is still an active role process to inspect or stop.

When `isolate_worktrees: true`, Agentry also checks existing role worktrees
before reuse. A dirty `agentry/worktrees/<role>` directory is skipped until its
leftover repo changes are committed, moved, or removed, which keeps one issue's
partial work out of the next issue's branch.

## Upgrade

The start scripts install Agentry from the Git ref pinned in the script. To
upgrade intentionally, update that ref or set `AGENTRY_INSTALL_REF`, stop any
running Agentry process that uses this venv, and rerun the wrapper with
`AGENTRY_FORCE_INSTALL=1`. Wrapper subcommands reuse an existing venv without
force-reinstalling, so `status`, `doctor`, `configure`, and `gui` are safe to
run while Agentry is live.

Prefer release tags such as `v0.1.1` for stable target repos. Use raw commits
only for short-lived platform fix testing before the next release is cut.

## Remove

Delete this `agentry/` folder. Optionally keep or delete `docs/ai/roles/`
depending on whether you want to preserve the project role documentation.
