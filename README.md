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

## Setup

Install machine dependencies once:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.sh | bash
```

Then authenticate the LLM CLIs you plan to use:

```bash
claude login
codex login
```

Add Agentry to a target repo:

```powershell
cd C:\projects\rpi-home-monitor
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex
```

```bash
cd ~/projects/rpi-home-monitor
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
```

Then:

1. Copy `agentry/.env.example` to `agentry/.env` and fill `GITHUB_TOKEN`.
2. Run the GUI or edit `agentry/config.yml`.
3. Edit `docs/ai/roles/*.md` for project-specific rules.

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

The standard pipeline prompts also treat clean local feature branches as cache,
not authority: Implementer retry paths and Tester reset the local feature branch
to `origin/feature/<id>-<slug>` before rebasing. That keeps force-pushed or
supervisor-rebased branches from being misreported as merge conflicts.
Reviewer follows the same rule for stale PRs: if a `ready-for-review` branch is
behind `origin/main`, it attempts a clean rebase and push before reviewing, and
only labels `merge-conflict` when the rebase genuinely conflicts.

When Tester opens a PR, the bundled prompt writes the multi-line PR body to a
temporary file and calls `gh pr create --body-file`. That avoids shell-specific
quoting failures on Windows and keeps validation evidence readable.

## Per-Role Model Assignment

Each role can use a different model or provider:

```yaml
target_repo: vinu-dev/rpi-home-monitor
mode: pipeline

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
- [docs/how-to-use.md](docs/how-to-use.md) - operator guide
- [docs/watchdog-and-dashboard.md](docs/watchdog-and-dashboard.md) - watchdog, stop, crash recovery, and GUI design
- [COMPATIBILITY-SPEC.md](COMPATIBILITY-SPEC.md) - target repo contract
- [docs/examples/standard/](docs/examples/standard/) - standard six-role example
- [docs/examples/medical-device/](docs/examples/medical-device/) - extended regulated-software example
