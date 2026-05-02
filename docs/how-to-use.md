# Skynet Agentry — How to Use

Status: **draft, pre-implementation**

The Operator's quick guide. Five-step flow to get a target repo running autonomously.

---

## TL;DR — the five steps

```bash
# 1. Install Skynet Agentry once on this host
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
skynet service install                   # registers systemd / NSSM service

# 2. Get the target repo
git clone git@github.com:vinu-dev/rpi-home-monitor.git
cd rpi-home-monitor

# 3. Add Skynet to it (gtest-style: declare it, don't copy it)
skynet init                              # creates .skynet/config.yml + docs/ai/roles/*.md skeletons

# 4. Edit which model handles each role + write what each role does
$EDITOR .skynet/config.yml               # set `cli` per role (claude, codex, etc.)
$EDITOR docs/ai/roles/architect.md       # write project-specific instructions per role
# ... same for the other roles

# 5. Start the show
git commit -am "Add Skynet Agentry config and role rules"
git push
skynet target add --repo git@github.com:vinu-dev/rpi-home-monitor.git
skynet status                            # all role threads running
```

`skynet start` auto-detects which CLIs are installed (looks them up on PATH) and runs them with the args you configured. Discord pings as work flows through.

---

## 1. Prerequisites

- A host that runs 24/7: Ubuntu 22.04+ (recommended) or Windows 11
- Python 3.11+
- `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `gh` CLI (for `skynet init` and label management)
- At least one LLM CLI installed: `claude` (Claude Code) and/or `codex` (Codex CLI), and/or a wrapper script for a local model
- A Discord server where you can post webhooks

Optional, role-dependent:

- Local model runtime (ollama / lm-studio) if you want a role to use a local model
- WSL2 with Ubuntu (Windows hosts only) if any role's rule file calls Linux-only tools (e.g., `bitbake`)
- SSH credentials to a hardware test rig if any role's rule file accesses hardware

---

## 2. Step 1 — Install Skynet Agentry on the host

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

### Set up secrets and host config

`~/.skynet/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...                      # if using Anthropic API
OPENAI_API_KEY=sk-...                              # if using OpenAI API
GITHUB_TOKEN=ghp_...                               # fine-grained PAT
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

GitHub PAT scopes: `contents` (read+write), `issues` (read+write), `pull_requests` (read+write), `metadata` (read).

`~/.skynet/pipeline.local.toml`:

```toml
[host]
state_dir = "~/.skynet/state"

[github]
token_env = "GITHUB_TOKEN"

[notification]
discord_webhook_env = "DISCORD_WEBHOOK_URL"
```

### Authenticate subscription CLIs (optional)

If you want roles routed through your Claude Pro/Max subscription:

```bash
claude login
```

Or your ChatGPT/Codex subscription:

```bash
codex login
```

These store OAuth credentials locally that the spawned subprocesses inherit.

### Install services

```bash
skynet service install
```

On Linux: writes systemd unit at `~/.config/systemd/user/skynet.service` and enables it.
On Windows: creates an NSSM service running as your user (so OAuth creds for `claude login` / `codex login` are reachable).

```bash
skynet status

# orchestrator: running (pid 12345, 0 targets, 0 role threads)
# notifications: ok
```

---

## 3. Step 2-3 — Add Skynet to a target repo

### Clone the target

```bash
git clone git@github.com:vinu-dev/rpi-home-monitor.git
cd rpi-home-monitor
```

### Run `skynet init`

```bash
skynet init                              # default: 6-role hobby roster
# or
skynet init --template medical-device    # 11-role medical device roster
```

This creates skeleton files in the current repo:

```
.skynet/
└── config.yml                            ← agent declarations + timeouts
docs/
└── ai/
    └── roles/
        ├── researcher.md                 ← skeleton — "Replace with project-specific rules"
        ├── architect.md
        ├── implementer.md
        ├── tester.md
        ├── reviewer.md
        └── release.md
```

For `--template medical-device`, you also get `risk_analyst.md`, `code_reviewer.md`, `quality_reviewer.md`, `cybersecurity_reviewer.md`, `regulatory_reviewer.md`, `traceability_tracker.md`.

These are starting points — repo owner edits them.

---

## 4. Step 4 — Configure models and write rule files

### Pick which model handles each role

Edit `.skynet/config.yml`. Default uses `claude` everywhere. Adjust per your setup:

```yaml
target_repo: vinu-dev/rpi-home-monitor

agents:
  researcher:
    cli: claude                              # uses claude CLI
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 60
    total_min: 30
    stall_min: 5

  architect:
    cli: claude                              # Opus is great for architecture
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 5

  implementer:
    cli: codex                               # Codex via OpenAI subscription
    args: ["--auto-approve"]
    interval_min: 5
    total_min: 60
    stall_min: 10

  tester:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 10

  reviewer:
    cli: claude                              # different vendor than implementer recommended
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 20
    stall_min: 5

  release:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 1440      # daily
    total_min: 60
    stall_min: 15

sensitive_paths:
  - "**/auth/**"
  - "**/ota/**"
  - "**/pairing*"
```

### Mix and match across roles

```yaml
agents:
  researcher:    { cli: claude, ... }            # Claude API or subscription
  architect:     { cli: claude, ... }
  implementer:   { cli: codex, ... }             # OpenAI Codex subscription
  tester:        { cli: ollama-llama,  ... }     # local Llama via wrapper
  reviewer:      { cli: claude, ... }
  release:       { cli: claude, ... }
```

The framework doesn't care what binary is — only that it accepts args and a prompt, runs, and exits. A wrapper script around ollama works the same as `claude`:

```bash
#!/usr/bin/env bash
# /usr/local/bin/ollama-llama
exec ollama run llama-3.1-70b "$@"
```

### Write each role's rule file

This is where the project-specific work lives. Example for `docs/ai/roles/architect.md`:

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

Same shape for the other roles. Customize per project conventions.

For a medical device project, role files are denser and reference specific standards:

```markdown
# Quality Reviewer

## Trigger
Find PRs labeled `ready-for-quality-review`. If none, exit.

## Steps per PR
1. Check ISO 13485 §8.4 conformance:
   - Design output traces to design input (verify via traceability matrix)
   - Software unit verification records present (per IEC 62304 §5.5.5)
2. Check IEC 62304 software safety classification:
   - Class A/B/C correctly tagged in issue
   - Documentation matches class requirements
3. ...
```

See [`docs/examples/medical-device/`](examples/medical-device/) for full examples.

---

## 5. Step 5 — Start

```bash
git commit -am "Add Skynet Agentry config and role rules"
git push

skynet doctor --target git@github.com:vinu-dev/rpi-home-monitor.git --init-labels
# Creates the labels referenced by your rule files
# Validates: config valid, all role files present, all CLIs on PATH

skynet target add --repo git@github.com:vinu-dev/rpi-home-monitor.git
# Orchestrator now spawns one thread per declared role

skynet status

# orchestrator: running (pid 12345, 1 target, 6 role threads)
#   role threads:
#     researcher    next-spawn-in: 42m   last-exit: 0
#     architect     next-spawn-in: 3m    last-exit: 0 (no work)
#     implementer   next-spawn-in: 4m    last-exit: 0 (no work)
#     tester        next-spawn-in: 2m    last-exit: 0 (no work)
#     reviewer      next-spawn-in: 1m    last-exit: 0 (no work)
#     release       next-spawn-in: 23h   last-exit: 0
```

You're done with setup. The system runs.

---

## 6. Daily operation

### What you'll see

Discord pings as roles wake up:

```
[Skynet] researcher: started
[Skynet] researcher: opened issue #173 "Add audio recording"
[Skynet] researcher: exited 0 (took 4m12s)
[Skynet] architect: started, no work, exited 0
[Skynet] architect: started for #173
[Skynet] architect: design doc committed for #173, label flipped
[Skynet] implementer: started for #173
[Skynet] tester: tests-failed for #173, label flipped
[Skynet] implementer: started for #173 (retry 1)
[Skynet] tester: green, PR #88 opened, label `ready-for-review`
[Skynet] reviewer: approved PR #88
[GitHub] PR #88 merged
```

### Operator commands

```bash
skynet status                       # what's running, what's stuck
skynet logs                         # tail orchestrator log
skynet logs --role implementer      # tail one role's stdout

skynet pause --role implementer     # stop spawning this role until resume
skynet resume --role implementer

skynet pause                        # stop all roles
skynet resume

skynet kick --role <role>           # force-kill current subprocess; next interval starts fresh
```

### Triaging research drafts

The Researcher opens issues with no label. You decide which to act on:

- **Worth doing now:** add the label your project uses for "next stage" (e.g., `ready-for-design` or `ready-for-risk-analysis` for medical projects). The next role picks up within 5 min.
- **Maybe later:** add a custom label like `backlog`. Skynet ignores it.
- **Not worth it:** close the issue.

This is the only manual step in routine operation.

### Vetoing or unsticking

- A PR has `blocked` — Reviewer (or another reviewer role for medical) flagged it. Decide manually.
- A role keeps stalling — check `skynet logs --role <name>`. Likely the rule file is unclear or the CLI is hitting an environment issue.
- An agent is misbehaving — `skynet pause --role <name>`, fix the rule file, `skynet resume`.

---

## 7. Adding more roles for specialized projects

For projects with extra compliance, security, or quality concerns, declare additional roles in `.skynet/config.yml` and write their rule files in `docs/ai/roles/`. The framework spawns one thread per declared role automatically.

### Medical device example (11 roles)

See [`docs/examples/medical-device/`](examples/medical-device/) for a complete example with:

- `risk_analyst` — ISO 14971 risk analysis on every new feature
- `quality_reviewer` — ISO 13485 / IEC 62304 conformance
- `cybersecurity_reviewer` — IEC 81001-5-1 + FDA cyber guidance
- `regulatory_reviewer` — FDA 510(k) / 21 CFR 820 impact
- `traceability_tracker` — bidirectional req → design → code → tests verification

The framework runs identically — just more threads.

### Other specialized rosters

- **Open-source library**: + `docs_writer` role for API docs, + `changelog_curator` role
- **Web service**: + `security_reviewer` for OWASP-style review, + `performance_tester` for load tests
- **Embedded firmware**: tester rule file includes hardware flash + smoke + serial scrape

---

## 8. Subscription routing

Both `claude` and `codex` CLIs use OAuth from their respective `login` commands. Setting these up once on the host means subprocesses run against your subscription quota instead of API tokens.

```bash
claude login              # opens a browser, do this once
codex login               # same
```

When the subscription rate-limits, the CLI exits with an error. The role pauses until the next interval, when subscription is back. If you want a fallback (e.g., switch to API on rate limit), wrap the CLI in a small shell script:

```bash
#!/usr/bin/env bash
# claude-with-api-fallback
claude "$@" 2>&1 | tee /tmp/claude.log
if grep -q "rate.limit" /tmp/claude.log; then
    claude --api-key "$ANTHROPIC_API_KEY" "$@"
fi
```

Point the role's `cli:` field at this script. The framework doesn't need to know.

---

## 9. Hardware integration

If a role's rule file calls hardware (SSH to a Pi, flash via SWUpdate, scrape serial), the agent does it using its built-in shell tools. The framework doesn't need to know.

Operator setup:

- SSH credentials reachable to the orchestrator user (`~/.ssh/id_rsa` permissions correct)
- Test rig on a network the host can reach
- Required CLIs installed (`socat`, `swupdate-cli`, `lsusb`, etc.)
- Generous `total_min` for the role doing the hardware work (often 30-60 min for flash + boot + smoke)

Example `docs/ai/roles/tester.md` snippet:

```markdown
## Hardware verification (if PR touches embedded code)

If the diff touches `app/camera/` or `meta-home-monitor/`, run hardware smoke:

1. Build SWU: `./scripts/build.sh camera-dev`
2. SCP to test rig: `scp build/output.swu pi@192.168.1.51:/tmp/`
3. SSH and flash: `ssh pi@192.168.1.51 'sudo swupdate -i /tmp/output.swu'`
4. Wait for boot: `socat /dev/ttyUSB0,b115200 -` (capture for 60s)
5. SSH and check: `ssh pi@192.168.1.51 'systemctl status camera-streamer.service'`
6. If green, label `ready-for-review`. If red, label `tests-failed`.
```

---

## 10. Troubleshooting

### Orchestrator won't start

```bash
journalctl --user -u skynet -e             # Linux
# Windows: Event Viewer → Application logs
```

Common: `.env` missing, `skynet doctor` failing for a target, port conflict on IPC socket.

### A role's CLI not found

```
Error: agent 'implementer' uses cli 'codex' which is not on PATH
Install: npm install -g @openai/codex
```

`skynet doctor` checks every CLI before spawning. Install missing CLIs and re-run.

### Role exits non-zero immediately

Usually the rule file is missing:

```
researcher: docs/ai/roles/researcher.md not found, exit 1
```

Create or edit the rule file in the target repo.

### Service running as wrong user (Windows)

If `claude` CLI reports "not authenticated" despite `claude login` working interactively:

```powershell
nssm set skynet ObjectName .\<your-username> <your-password>
sc stop skynet && sc start skynet
```

`skynet service install` does this automatically; only relevant for debugging.

### Discord notifications not arriving

```bash
skynet notify test
```

If that fails, check `DISCORD_WEBHOOK_URL` in `.env`. Webhook URLs expire if the channel is deleted.

---

*End of how-to-use.md.*
