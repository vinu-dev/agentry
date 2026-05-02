# Skynet Agentry — How to Use

Status: **draft, pre-implementation**

The Operator's quick guide. References v0.1 commands as they will exist when the runtime ships.

---

## 1. Prerequisites

- A host that runs 24/7: Ubuntu 22.04+ (recommended) or Windows 11
- Python 3.11+
- `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `gh` CLI authenticated, OR a GitHub fine-grained PAT
- At least one LLM CLI installed: `claude` (Claude Code) and/or `codex` (Codex CLI)
- A Discord server you can post webhooks to

Optional, role-dependent:

- Local model runtime (ollama / lm-studio) if you want a role to use a local model
- WSL2 with Ubuntu (Windows only) if any role's rule file calls Linux-only tools (e.g., `bitbake`)

---

## 2. Install

### Linux

```bash
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
skynet --version
mkdir -p ~/.skynet/state
```

### Windows

```powershell
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
skynet --version
New-Item -ItemType Directory -Path "$env:USERPROFILE\.skynet\state" -Force
```

---

## 3. First-time host setup

### 3.1 Create `~/.skynet/.env`

```
ANTHROPIC_API_KEY=sk-ant-...                      # if using Anthropic API
OPENAI_API_KEY=sk-...                              # if using OpenAI API
GITHUB_TOKEN=ghp_...                               # fine-grained PAT
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

GitHub PAT scopes: `contents` (read+write), `issues` (read+write), `pull_requests` (read+write), `metadata` (read).

### 3.2 (Optional) Authenticate subscription CLIs

If you have a Claude Pro/Max subscription and want roles routed through it:

```bash
claude login
```

Same for OpenAI Codex CLI:

```bash
codex login
```

These store OAuth credentials locally that the spawned subprocesses inherit.

### 3.3 Create `~/.skynet/pipeline.local.toml`

```toml
[host]
state_dir = "~/.skynet/state"

[github]
token_env = "GITHUB_TOKEN"

[notification]
discord_webhook_env = "DISCORD_WEBHOOK_URL"
```

### 3.4 Install services

```bash
skynet service install
```

On Linux: writes systemd unit at `~/.config/systemd/user/skynet.service` and enables it.
On Windows: creates an NSSM service running as your user (so `claude`/`codex` OAuth creds are reachable).

```bash
skynet status

# orchestrator: running (pid 12345, 6 role threads, last event 30s ago)
# targets: 0
# notifications: 0 queued
```

---

## 4. Onboard a target repo

### 4.1 Add `.skynet/config.yml`

In the target repo:

```yaml
# .skynet/config.yml
target_repo: vinu-dev/rpi-home-monitor

agents:
  researcher:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 60
    total_min: 30
    stall_min: 5
    prompt: |
      You are the Researcher. Read docs/ai/roles/researcher.md and follow it.

  architect:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 5
    prompt: |
      You are the Architect. Read docs/ai/roles/architect.md and follow it.

  implementer:
    cli: codex
    args: ["--auto-approve"]
    interval_min: 5
    total_min: 60
    stall_min: 10
    prompt: |
      You are the Implementer. Read docs/ai/roles/implementer.md and follow it.

  tester:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 10
    prompt: |
      You are the Tester. Read docs/ai/roles/tester.md and follow it.

  reviewer:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 20
    stall_min: 5
    prompt: |
      You are the Reviewer. Read docs/ai/roles/reviewer.md and follow it.

  release:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 1440      # daily
    total_min: 60
    stall_min: 15
    prompt: |
      You are the Release Engineer. Read docs/ai/roles/release.md and follow it.

sensitive_paths:
  - "**/auth/**"
  - "**/ota/**"
  - "**/pairing*"
```

### 4.2 Write `docs/ai/roles/*.md`

Six markdown files. The framework calls these "role rules." Each tells the agent what to do in this specific repo.

Example for `docs/ai/roles/architect.md`:

```markdown
# Architect

## Trigger
Find issues labeled `ready-for-design` (oldest first). If none, exit immediately.

## Steps
1. Read the issue body and any linked context
2. Read docs/architecture/ to understand the existing system
3. Read docs/ai/risk-register.md for sensitive areas to flag
4. Write a design doc to docs/ai/designs/<id>-<slug>.md including:
   - Goal (1-2 sentences)
   - Acceptance criteria
   - Architecture impact
   - Risks (cross-reference risk register)
   - Test plan
5. Commit on a fresh branch `skynet/<id>/design-<slug>`
6. Push the branch
7. Open a PR titled `[design] <issue title>` linking the issue
8. On the issue: replace label `ready-for-design` with `ready-for-implementation`
9. Exit
```

Repeat for the other 5 roles. Customize per your project's conventions.

### 4.3 Create the labels and add the target

```bash
skynet doctor --target git@github.com:vinu-dev/rpi-home-monitor.git --init-labels
# Creates the 6 labels in the target repo if they don't exist.

skynet doctor --target git@github.com:vinu-dev/rpi-home-monitor.git
# REQUIRED FILES                  ✓ all present
# AGENT CONFIG                    ✓ valid (6 roles declared)
# ROLE RULE FILES                 ✓ all 6 present
# LABELS                          ✓ all 6 created in target
# CLI BINARIES                    ✓ claude (1.0.7), codex (0.4.2)
# RESULT: PASS

skynet target add --repo git@github.com:vinu-dev/rpi-home-monitor.git
# Target added. Researcher will fire within 60 minutes.
```

---

## 5. Pick which model handles each role

Per role, configurable:

```yaml
agents:
  researcher:    { cli: claude, ... }      # via Claude API key OR `claude login` subscription
  architect:     { cli: claude, ... }
  implementer:   { cli: codex, ... }       # via OpenAI Codex CLI subscription
  tester:        { cli: claude, ... }
  reviewer:      { cli: claude, ... }      # different vendor recommended
  release:       { cli: claude, ... }
```

If you want one role to use a local model:

```yaml
agents:
  reviewer:
    cli: ollama-claude-shim       # whatever wrapper script you have for ollama
    args: ["--model", "llama-3.1-70b"]
    ...
```

The framework doesn't care what the binary is — only that it accepts the args, runs the prompt, exits with a status code.

---

## 6. Daily operation

### 6.1 What you'll see

Discord pings as roles wake up:

```
[Skynet] researcher: started
[Skynet] researcher: opened issue #173 "Add audio recording"
[Skynet] researcher: exited 0 (took 4m12s)
[Skynet] architect: started, no work, exited 0
[Skynet] architect: started
[Skynet] architect: design doc committed for #173, label flipped
[Skynet] implementer: started for #173
[Skynet] implementer: tests-failed, exited 0 (Tester will requeue)
[Skynet] implementer: started for #173 (retry 1)
[Skynet] tester: green, PR #88 opened, label `ready-for-review`
[Skynet] reviewer: approved PR #88
[GitHub] PR #88 merged
```

### 6.2 Operator commands

```bash
skynet status                       # what's running, what's stuck
skynet status --target <repo>       # one target's recent activity
skynet logs                         # tail orchestrator log
skynet logs --role implementer      # tail one role's stdout

skynet pause --role implementer     # stop spawning this role until resume
skynet resume --role implementer

skynet pause                        # stop all roles
skynet resume

skynet kick --role <role>           # force-kill current subprocess; next interval starts fresh
```

### 6.3 Triaging research drafts

The Researcher opens issues with no label. You decide which to act on:

- **Worth doing now:** add label `ready-for-design`. Architect picks up within 5 min.
- **Maybe later:** add a custom label like `backlog`. Skynet ignores it.
- **Not worth it:** close the issue.

This is the only manual step in routine operation.

### 6.4 Vetoing or unsticking

- A PR has `blocked` — Reviewer flagged it as touching sensitive paths. Decide manually: review and merge, or close.
- A role keeps stalling — check `skynet logs --role <name>` for what the CLI is doing. Likely the role rule file is unclear, or the CLI is hitting an environment issue.
- An agent is misbehaving — `skynet pause --role <name>`, fix the rule file or config, `skynet resume`.

---

## 7. Tuning

If a role is too aggressive (researcher creating too many issues):

```yaml
researcher:
  interval_min: 360         # 6 hours instead of 60 minutes
```

If implementations are taking too long:

```yaml
implementer:
  total_min: 90             # raise from 60
```

If a CLI is silent for legitimate reasons but currently triggering stall:

```yaml
implementer:
  stall_min: 30             # raise tolerance
```

These are operator decisions, edited in the target's `.skynet/config.yml`. The orchestrator picks up changes on the next interval.

---

## 8. Subscription routing

Both `claude` and `codex` CLIs use OAuth from their respective `login` commands. Setting these up once on the host means subprocesses run against your subscription quota instead of API tokens.

```bash
claude login              # opens a browser, do this once
codex login               # same
```

When the subscription rate-limits, the CLI exits with an error. The role pauses until next interval, when subscription is back. If you want a fallback (e.g., switch to API on rate limit), wrap the CLI in a small shell script:

```bash
#!/bin/bash
# claude-with-api-fallback
claude "$@" 2>&1 | tee /tmp/claude.log
if grep -q "rate.limit" /tmp/claude.log; then
    # Fall through to API key invocation
    claude --api-key "$ANTHROPIC_API_KEY" "$@"
fi
```

Point the role's `cli:` field at this script. Framework doesn't need to know.

---

## 9. Troubleshooting

### Orchestrator won't start

```bash
journalctl --user -u skynet -e             # Linux
# Windows: Event Viewer → Application logs
```

Common: `.env` missing, target's `skynet doctor` failing, port conflict on IPC socket.

### A role never exits cleanly

Check the role's stdout in `skynet logs --role <name>`. Most often:

- Role rule file is missing or malformed → fix `docs/ai/roles/<role>.md`
- CLI authentication failed → re-run `claude login` / `codex login`
- Target repo has no work for this role → expected; agent should `exit 0` when no work

### Service running as wrong user (Windows)

If `claude_cli` reports "not authenticated" despite `claude login` working interactively:

```powershell
nssm set skynet ObjectName .\<your-username> <your-password>
sc stop skynet && sc start skynet
```

`skynet service install` does this automatically; only relevant if debugging.

### Discord notifications not arriving

```bash
skynet notify test
```

If that fails, check `DISCORD_WEBHOOK_URL` in `.env`. Webhook URLs expire if the channel is deleted.

---

## 10. When things really go wrong

`skynet pause` stops all dispatch. Investigate, fix, `skynet resume`. The framework holds no important state, so worst case: edit configs, restart, GitHub state picks up where it left off.

---

*End of how-to-use.md.*
