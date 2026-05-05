# Agentry

![Agentry automates multi-agent AI development workflows](docs/assets/agentry-linkedin-concept.png)

Agentry turns a GitHub repo into an automated AI product team. It runs
role-based agents such as Researcher, Architect, Implementer, Tester, Reviewer,
Release Engineer, and PM-style orchestration. Each role can use a different LLM
CLI or wrapper: Codex, Claude Code, local Llama/Ollama, or anything executable
on `PATH`.

The important part is not one agent. It is the supervised pipeline: GitHub
labels are the queue, role rules define the work, session state prevents
duplicate token burn, and the dashboard lets the operator see and stop what is
happening.

## Current Release

The current supported alpha release is `v0.1.7`. Agentry is distributed from
GitHub releases and Git refs. Target repositories pin a specific Agentry tag or
commit in their generated `agentry/start.ps1` and `agentry/start.sh`, so a
working target does not silently drift when Agentry `main` changes.

## How It Is Used

Agentry is a dependency you pull into each target repo, not a system service.
Each target gets its own `agentry/` folder and repo-local Python venv installed
from the GitHub ref pinned in that target's start script.

Run it when you want the pipeline active. Stop it with Ctrl-C, by closing the
terminal, or by rebooting. No systemd, NSSM, or hidden service is installed by
default.

```text
your-target-repo/
  agentry/
    config.yml
    start.ps1 / start.sh
    .env.example
    .gitignore
    .env       # gitignored
    .venv/     # gitignored
    logs/      # gitignored
    state/     # gitignored
  docs/ai/roles/
    researcher.md
    architect.md
    implementer.md
    tester.md
    reviewer.md
    release.md
  your-code
```

Role rule files live in `docs/ai/roles/<role>.md`, not inside `agentry/`.

## New Repository Setup

There are two setup steps: once per machine, then once per target repo.

### 1. Install machine dependencies once

Install machine dependencies once:

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

### 2. Add Agentry to the target repo

Add Agentry to a target repo:

Windows PowerShell:

```powershell
cd C:\projects\rpi-home-monitor
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex
```

Linux shell:

```bash
cd ~/projects/rpi-home-monitor
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
```

For an exact released setup, fetch the release tag instead of `main`, or pass
the release tag to the installer. Example:

```powershell
cd C:\projects\rpi-home-monitor
$script = Join-Path $env:TEMP "add-to-target.ps1"
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/v0.1.2/scripts/add-to-target.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Branch v0.1.2
```

```bash
cd ~/projects/rpi-home-monitor
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/v0.1.2/scripts/add-to-target.sh | AGENTRY_BRANCH=v0.1.2 bash
```

Then:

1. Copy `agentry/.env.example` to `agentry/.env`.
2. Set `GITHUB_TOKEN`, or ensure `gh auth status` works for the target repo.
3. Run `doctor --init-labels` once to create standard labels.
4. Run the GUI or edit `agentry/config.yml`.
5. Edit `docs/ai/roles/*.md` for project-specific rules.
6. Commit `agentry/config.yml`, `agentry/start.ps1`, `agentry/start.sh`,
   `agentry/.env.example`, `agentry/.gitignore`, `agentry/README.md`, and
   `docs/ai/roles/*.md`. Do not commit `.env`, `.venv`, logs, state, or
   worktrees.

## Configure Without Starting Agents

The generated start scripts can create/reuse the venv and run Agentry CLI
commands without starting role loops:

```powershell
.\agentry\start.ps1 configure --target . --defaults
.\agentry\start.ps1 gui --target .
```

```bash
./agentry/start.sh configure --target . --defaults
./agentry/start.sh gui --target .
```

When the repo-local venv already exists, wrapper subcommands reuse it instead
of force-reinstalling just because the pinned-ref marker is missing or stale.
That makes `status`, `doctor`, `configure`, and `gui` safe to run while the
orchestrator is live. To intentionally refresh the venv to the pinned ref, stop
Agentry first and set `AGENTRY_FORCE_INSTALL=1` for that wrapper invocation.

The dashboard shows role sessions, latest logs, token budget state, and Stop
buttons. It also writes recommended options: `manual`, `pipeline`, or
`autonomous` mode; Researcher and Release toggles; and balanced/cheap/strong
model profiles.

## Run Modes

| Mode | Behavior |
|------|----------|
| `manual` | No roles start. Good for pause/config/status. |
| `pipeline` | Default. Processes existing GitHub labels, but Researcher cannot create new issues. |
| `autonomous` | Allows Researcher only when `research.allow_create_issues: true`. |

Researcher is intended to act like a product-owner discovery role. In
autonomous mode it should look for well-sourced product opportunities,
including competitor and domain patterns, then file small, scoped issues with
source URLs and access dates, an MVP hypothesis, validation expectations, and
clear out-of-scope boundaries. It should identify capability patterns worth
adapting, not copy a competitor's proprietary UX or claims.

Agentry checks the research backlog before launching the Researcher LLM. Set
`research.max_open_ready_for_design` to the desired queue floor/guard and
`research.backlog_labels` to the issue labels that count as design supply. For
medical or regulated targets with a pre-design risk gate, include both the
Architect label and the upstream risk label, for example:

```yaml
research:
  allow_create_issues: true
  max_open_ready_for_design: 2
  backlog_labels: ["ready-for-design", "needs-risk"]
```

When the counted backlog is already at or above the guard, Agentry skips
Researcher without starting the model process.

## Start And Stop

Start foreground agents:

```powershell
.\agentry\start.ps1
```

```bash
./agentry/start.sh
```

Stop safely:

```powershell
.\agentry\start.ps1 stop --target . --all
```

```bash
./agentry/start.sh stop --target . --all
```

Agentry records one session per role under `agentry/state/sessions/`. On restart
after a crash or reboot, old running sessions whose PIDs are gone are marked
`stale` and do not block new work.

When isolated role worktrees are enabled, Agentry refuses to start a role in an
existing worktree that has uncommitted or untracked repo changes. This protects
the next issue or PR from inheriting partial work from a previous role run; clean
or salvage the worktree first, then start the role again.

Clean role worktrees are refreshed before every run. Issue and schedule-driven
roles detach to the current `origin/main` base, while PR-triggered roles detach
to the selected pull request head fetched from `refs/pull/<number>/head`. That
keeps reviewers, medical gates, and merger checks aligned with the files in the
actual PR, not a stale reusable worktree.

The standard pipeline prompts also treat clean local feature branches as cache,
not authority: Implementer retry paths and Tester reset the local feature branch
to `origin/feature/<id>-<slug>` before rebasing. That keeps force-pushed or
supervisor-rebased branches from being misreported as merge conflicts.
Reviewer follows the same rule for stale PRs: if a `ready-for-review` branch is
behind `origin/main`, it attempts a clean rebase and push before reviewing, and
only labels `merge-conflict` when the rebase genuinely conflicts.

The standard Reviewer also runs a small merge train for shared conflict zones.
Targets declare those paths in `merge_sensitive_paths`; the oldest matching PR
can proceed, while newer matching PRs move to `merge-train-waiting` and rebase
after the older PR merges. This keeps traceability docs, workflow files, release
files, and other shared generated artifacts from all becoming conflicted at once.

## Token Governance

Agentry avoids token burn before a role starts. Every label-triggered role first
uses cheap GitHub checks; if there is no matching work, no LLM process is
spawned. For PR-triggered roles, `trigger.pr_check_gate` can also wait for PR
checks:

```yaml
trigger:
  pr_labels: ["ready-for-review", "merge-train-waiting"]
  pr_check_gate: settled  # none | settled | green
```

The bundled Reviewer uses `settled`, so it does not launch just to discover
that CI is still pending. `green` is stricter and waits for passing or absent
checks. If GitHub cannot report checks because of a transient CLI/API failure,
Agentry allows the role to run rather than deadlocking the queue.

Before a role starts, Agentry writes a bounded work packet under
`agentry/state/workpackets/<role>.md` and injects its absolute path into the
prompt. The packet includes trigger labels, exactly one `Selected Candidate`,
bounded read-only queue context, recent session summaries, and context rules.
It is local runtime state and should not be committed.

```yaml
context:
  work_packets: true
  candidate_limit: 20
  max_packet_bytes: 32000
  log_tail_lines: 120
  diff_max_lines: 1000
```

Role prompts should read the work packet first, process only the selected
candidate, tail logs instead of reading full historical logs, inspect PR file
lists before diffs, and use targeted diffs for large PRs. Other candidates in
the packet are queue awareness, not permission to process a second item. Token
budgets remain warnings recorded in session state; they are not automatic kill
triggers.

When Tester opens a PR, the bundled prompt writes the multi-line PR body to a
temporary file and calls `gh pr create --body-file`. That avoids shell-specific
quoting failures on Windows and keeps validation evidence readable. The body
must include a GitHub closing keyword such as `Closes #<issue-number>` so the
issue closes automatically after merge instead of lingering with `pr-open`.

## Upgrade A Target Repo

To upgrade a target to a released Agentry version:

1. Stop Agentry for that target repo.
2. Update the pinned ref in `agentry/start.ps1` and `agentry/start.sh` to the
   release tag or commit.
3. Commit the pin update in the target repo.
4. Refresh the target venv intentionally:

Windows:

```powershell
$env:AGENTRY_FORCE_INSTALL = "1"
.\agentry\start.ps1 status --target .
Remove-Item Env:\AGENTRY_FORCE_INSTALL
```

Linux:

```bash
AGENTRY_FORCE_INSTALL=1 ./agentry/start.sh status --target .
```

Wrapper subcommands without `AGENTRY_FORCE_INSTALL=1` are safe health checks:
they reuse the existing venv instead of reinstalling into a live supervisor.

## Per-Role Model Assignment

Each role can use a different model or provider:

```yaml
target_repo: vinu-dev/rpi-home-monitor
mode: pipeline

research:
  allow_create_issues: false
  max_open_ready_for_design: 3
  backlog_labels: ["ready-for-design"]

agents:
  researcher:
    enabled: false
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "gpt-5.4-mini"]
    interval_min: 1440
    total_min: 30
    stall_min: 30
    token_budget: 20000

  implementer:
    cli: npx
    args: ["--yes", "@openai/codex", "exec", "-m", "gpt-5.4"]
    interval_min: 5
    total_min: 60
    stall_min: 60
    token_budget: 60000
```

Change `cli` and `args` per role for Claude Code, Codex, local models, or
custom wrappers.

## Watching What It Does

Per-role logs:

```text
agentry/logs/<role>/<timestamp>.log
```

Commands:

```bash
agentry status --target .
agentry gui --target .
agentry stop --target . --all
```

If `DISCORD_WEBHOOK_URL` is set in `agentry/.env`, lifecycle events are also
sent to Discord.

## Removing Agentry

Delete `agentry/`. Optionally delete `docs/ai/roles/` if you no longer want the
role instructions.

## License

See [LICENSE](LICENSE).

## More

- [docs/architecture.md](docs/architecture.md) - design and architecture
- [docs/design.md](docs/design.md) - product and workflow design principles
- [docs/how-to-use.md](docs/how-to-use.md) - operator guide
- [docs/release.md](docs/release.md) - Agentry release process
- [docs/watchdog-and-dashboard.md](docs/watchdog-and-dashboard.md) - watchdog, stop, crash recovery, and GUI design
- [CHANGELOG.md](CHANGELOG.md) - release history
- [COMPATIBILITY-SPEC.md](COMPATIBILITY-SPEC.md) - target repo contract
- [docs/examples/standard/](docs/examples/standard/) - standard six-role example
- [docs/examples/medical-device/](docs/examples/medical-device/) - extended regulated-software example
