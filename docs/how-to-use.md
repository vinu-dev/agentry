# Agentry - How to Use

Agentry is installed per target repository. You drop an `agentry/` folder into
the repo, configure roles, add secrets locally, and run the foreground start
script when you want the agent pipeline active. There is no host daemon,
service installer, `agentry init`, or `agentry target add` command.

---

## TL;DR - New Repo Setup

### 1. Install machine dependencies once

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

### 2. Add Agentry to one target repo

Run this from inside the target repository:

Windows PowerShell:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex
```

Linux shell:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
```

To install from an exact release tag instead of `main`:

Windows PowerShell:

```powershell
$script = Join-Path $env:TEMP "add-to-target.ps1"
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/v0.1.0/scripts/add-to-target.ps1 -OutFile $script
powershell -NoProfile -ExecutionPolicy Bypass -File $script -Branch v0.1.0
```

Linux shell:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/v0.1.0/scripts/add-to-target.sh | AGENTRY_BRANCH=v0.1.0 bash
```

This writes:

```text
agentry/
  config.yml
  start.ps1
  start.sh
  .env.example
  .gitignore
  README.md
docs/ai/roles/
  researcher.md
  architect.md
  implementer.md
  tester.md
  reviewer.md
  release.md
```

Existing files are preserved unless you pass `-Force` on Windows or set
`AGENTRY_FORCE=1` on Linux.

### 3. Configure secrets and roles

Copy the local secrets template:

Windows:

```powershell
Copy-Item agentry\.env.example agentry\.env
notepad agentry\.env
```

Linux:

```bash
cp agentry/.env.example agentry/.env
$EDITOR agentry/.env
```

Set `GITHUB_TOKEN` at minimum. `DISCORD_WEBHOOK_URL`, `ANTHROPIC_API_KEY`, and
`OPENAI_API_KEY` are optional.

If you prefer GitHub CLI auth for local supervised runs, `gh auth status` must
work for the target repo. For unattended operation, use a repo-scoped
`GITHUB_TOKEN`.

Use the configuration wizard or dashboard to choose run mode, model profile,
and which roles are allowed to run:

Windows:

```powershell
.\agentry\start.ps1 configure --target . --defaults
.\agentry\start.ps1 gui --target .
```

Linux:

```bash
./agentry/start.sh configure --target . --defaults
./agentry/start.sh gui --target .
```

You can also edit `agentry/config.yml` directly to choose the CLI, args, and
timeouts for each role. Edit `docs/ai/roles/*.md` for project-specific rules.

The default run mode is `pipeline`: Agentry processes existing GitHub labels
but does not let Researcher create new issues. Use `manual` to keep every role
quiet, or `autonomous` plus `research.allow_create_issues: true` when you want
Researcher to add new work.

### 4. Validate

The repo-local `agentry` CLI is created on first start under `agentry/.venv/`.
The start scripts run doctor automatically before spawning agents. After the
first setup, you can also run doctor directly:

Windows:

```powershell
.\agentry\.venv\Scripts\agentry.exe doctor --target .
```

Linux:

```bash
./agentry/.venv/bin/agentry doctor --target .
```

To create the standard GitHub labels:

Windows:

```powershell
.\agentry\.venv\Scripts\agentry.exe doctor --target . --init-labels
```

Linux:

```bash
./agentry/.venv/bin/agentry doctor --target . --init-labels
```

The doctor checks:

- target config loads and validates
- every declared role has a rule file, target-specific or bundled
- every configured CLI is on `PATH`
- `agentry/.env` exists
- `GITHUB_TOKEN` is set
- `gh` can reach the configured target repo, when `gh` is installed

After the first successful doctor run, commit the generated target files:

```text
agentry/config.yml
agentry/start.ps1
agentry/start.sh
agentry/.env.example
agentry/.gitignore
agentry/README.md
docs/ai/roles/*.md
```

Do not commit:

```text
agentry/.env
agentry/.venv/
agentry/logs/
agentry/state/
agentry/worktrees/
```

### 5. Start

Windows:

```powershell
.\agentry\start.ps1
```

Linux:

```bash
./agentry/start.sh
```

The first run creates `agentry/.venv/` and installs Agentry from the pinned
GitHub ref stamped into the start script. Later runs reuse the venv. Set
`AGENTRY_INSTALL_REF` only when you intentionally want to test or upgrade to a
specific branch, tag, or commit.

When you run a CLI subcommand through the wrapper, such as `status`, `doctor`,
`configure`, or `gui`, the wrapper reuses an existing `agentry/.venv/` and does
not force-reinstall only because the local install-ref marker is missing or
stale. This keeps status and health checks safe while Agentry is already
running. To intentionally refresh the venv to the pinned ref, stop Agentry first
and set `AGENTRY_FORCE_INSTALL=1` for that wrapper invocation.

Agentry runs in the foreground. Press Ctrl-C or close the terminal to stop it.
Rebooting the computer stops it too; there is no background service unless you
create one yourself.

---

## Upgrade An Existing Target

Target repositories should pin a released Agentry tag or commit. To upgrade:

1. Stop Agentry for that target.
2. Update the pinned ref in both start scripts.
3. Commit the pin update and any target-specific config changes.
4. Refresh the local venv intentionally.

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

Then run doctor through the wrapper:

```powershell
.\agentry\start.ps1 doctor --target . --init-labels
```

```bash
./agentry/start.sh doctor --target . --init-labels
```

Use a release tag such as `v0.1.0` for normal upgrades. Use a raw commit only
when deliberately testing an unreleased platform fix.

---

## Daily Operation

Use `agentry status --target .` to inspect role sessions, run mode, recent
logs, active PIDs, and token-budget state. Completed sessions do not display
old PIDs; a PID in status means Agentry still believes that role is running.
From a fresh target where the venv may not exist yet, use the start script
wrapper:

```powershell
.\agentry\start.ps1 status --target .
```

```bash
./agentry/start.sh status --target .
```

Use `agentry stop --target . ROLE` to stop one running role, or
`agentry stop --target . --all` to stop all recorded running sessions. The stop
path is conservative: completed or stale session files are not used to kill old
PIDs.

If `isolate_worktrees: true`, Agentry starts each role from
`agentry/worktrees/<role>`. Before reusing one of those worktrees, it checks
`git status --porcelain`; a dirty worktree is reported as a worktree preparation
error and the role is skipped until the operator commits, moves, or removes the
leftover changes. This is intentional, because partial work from one issue must
not leak into the next issue's branch.

Clean local branches inside role worktrees are still treated as disposable role
state. The standard Implementer retry path and Tester workflow reset their local
feature branch from `origin/feature/<id>-<slug>` before rebasing so they validate
the pushed branch, not an older local copy.

The standard Tester prompt also writes PR descriptions to a temporary file and
uses `gh pr create --body-file`. If you customize that role, keep the same
pattern for multi-line markdown; passing long PR bodies directly through
`--body` is fragile across Windows PowerShell and POSIX shells.

Use `agentry gui --target .` for a local status/configuration dashboard at
`http://127.0.0.1:4783`, or launch it through the start script wrapper shown
above.

Per-role stdout logs are written to:

```text
agentry/logs/<role>/<timestamp>.log
```

Runtime state and session notes created by agents live under:

```text
agentry/state/
```

Both directories are ignored by the generated `agentry/.gitignore`.

Role session records live under:

```text
agentry/state/sessions/<role>.json
```

If Agentry crashes or the computer restarts, old `running` records whose PIDs no
longer exist are marked `stale` on the next start and do not block progress.

---

## Role Model

The standard target config runs six roles:

- `researcher`
- `architect`
- `implementer`
- `tester`
- `reviewer`
- `release`

Each role is a loop:

1. Agentry builds the role prompt from `agentry/config.yml`.
2. Agentry spawns the configured CLI in the target repo.
3. The CLI reads `docs/ai/roles/<role>.md`.
4. The CLI does one cycle of work and exits.
5. Agentry logs the run, reports notifications, sleeps, and starts the next
   cycle later.

The framework owns process supervision. GitHub issues, labels, PRs, branches,
and the role rule files own the product workflow.

For repos where many PRs update the same generated docs or release files, add
those globs to `merge_sensitive_paths` in `agentry/config.yml`. The standard
Reviewer approves only the oldest open PR touching those paths and parks newer
ones with `merge-train-waiting` until they can rebase on the merged result.

---

## Troubleshooting

If a role never starts, run:

```bash
agentry doctor --target .
```

If a role starts but exits immediately, read its newest log under
`agentry/logs/<role>/`.

If a fresh venv installs the wrong Agentry version, check the ref in
`agentry/start.ps1` or `agentry/start.sh`, stop any Agentry process using that
venv, then rerun the wrapper with `AGENTRY_FORCE_INSTALL=1`. If the venv is
already corrupted, delete `agentry/.venv/` and rerun the start script.

If GitHub operations fail, verify:

- `GITHUB_TOKEN` is non-empty in `agentry/.env`
- the token is restricted to the correct target repo
- the token has contents, issues, pull request, and metadata permissions
- `gh repo view <owner>/<repo>` works if roles or `doctor --init-labels` use
  the GitHub CLI

If tokens are being consumed unexpectedly:

- run `agentry status --target .`
- open `agentry gui --target .`
- use `agentry stop --target . --all`
- switch `mode: manual` in `agentry/config.yml` or through the GUI
- check whether Researcher is enabled only in `autonomous` mode

For the detailed watchdog/session design, see
[`docs/watchdog-and-dashboard.md`](watchdog-and-dashboard.md).

---

## Removing Agentry

Delete `agentry/`. Optionally delete `docs/ai/roles/` if you no longer want the
role instructions in the target repo.
