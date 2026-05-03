# Agentry - How to Use

Status: **v0.1 alpha**

Agentry is installed per target repository. You drop an `agentry/` folder into
the repo, configure roles, add secrets locally, and run the foreground start
script when you want the agent pipeline active. There is no host daemon,
`agentry service install`, `agentry init`, or `agentry target add` command in
v0.1.

---

## TL;DR

### 1. Install machine dependencies once

Windows:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.ps1 | iex
```

Linux:

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

Windows:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex
```

Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
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

Edit `agentry/config.yml` to choose the CLI, args, and timeouts for each role.
Edit `docs/ai/roles/*.md` for project-specific rules.

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

Agentry runs in the foreground. Press Ctrl-C or close the terminal to stop it.

---

## Daily Operation

Use `agentry status --target .` to inspect recent role logs.

Per-role stdout logs are written to:

```text
agentry/logs/<role>/<timestamp>.log
```

Runtime state and session notes created by agents live under:

```text
agentry/state/
```

Both directories are ignored by the generated `agentry/.gitignore`.

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

---

## Troubleshooting

If a role never starts, run:

```bash
agentry doctor --target .
```

If a role starts but exits immediately, read its newest log under
`agentry/logs/<role>/`.

If a fresh venv installs the wrong Agentry version, check the ref in
`agentry/start.ps1` or `agentry/start.sh`, delete `agentry/.venv/`, and rerun
the start script.

If GitHub operations fail, verify:

- `GITHUB_TOKEN` is non-empty in `agentry/.env`
- the token is restricted to the correct target repo
- the token has contents, issues, pull request, and metadata permissions
- `gh repo view <owner>/<repo>` works if roles or `doctor --init-labels` use
  the GitHub CLI

---

## Removing Agentry

Delete `agentry/`. Optionally delete `docs/ai/roles/` if you no longer want the
role instructions in the target repo.
