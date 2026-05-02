# Skynet Agentry — How to Use

Status: **draft, pre-implementation**

This is the practical Operator's guide. It assumes you have read [`docs/architecture.md`](architecture.md) for the conceptual model and now want to actually run Skynet Agentry on a target repository.

The framework is private and pre-release; everything below describes the v0.1 experience as it will exist when the runtime ships. References to commands like `skynet init` and the `service install` flow are design contracts; they will be implemented as part of v0.1.

---

## 1. Prerequisites

A host running 24/7 (or as close to it as you can manage). One of:

- **Linux** — Ubuntu 22.04+ / Debian 12+ / Fedora 40+ / similar. systemd present. **Recommended.**
- **Windows 11** — Pro or Home (Pro recommended for Hyper-V). WSL2 with Ubuntu 24.04 installed.

Tools you will need installed on the host:

| Tool | Why | Install |
|------|-----|---------|
| Python 3.11+ | Framework runtime | `apt install python3.11` / windows installer |
| `uv` | Tool installer | `curl -LsSf https://astral.sh/uv/install.sh \| sh` / `winget install astral-sh.uv` |
| `gh` (GitHub CLI) | Repo operations | `apt install gh` / `winget install GitHub.cli` |
| `git` | Obviously | already there |
| Docker (optional, v1+) | Future hardware test isolation | — |
| `claude` CLI (optional) | Use Claude subscription via subscription routing | `npm i -g @anthropic-ai/claude-code` |
| `codex` CLI (optional) | Use OpenAI Codex subscription via subscription routing | per Codex CLI docs |
| ollama / lm-studio (optional) | Run models locally | per project docs |

Accounts you will need:

| Account | Why | Required? |
|---------|-----|-----------|
| GitHub | host for target repos | required |
| Anthropic API account | Claude API access | required (or subscription) |
| OpenAI API account | GPT-5 reviewer (different vendor rule) | required (or subscription) |
| Anthropic Pro/Max subscription | Subscription-routed Claude | optional, recommended |
| ChatGPT Plus / Codex subscription | Subscription-routed Codex | optional, recommended |
| Discord server (yours) | Notifications | required |

---

## 2. Installation

### 2.1 Linux

```bash
# Install the framework
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry

# Verify
skynet --version

# Create the config directory
mkdir -p ~/.skynet/{prompts,policies}

# Pull versioned prompts/policies that ship with the framework
skynet bootstrap
```

`skynet bootstrap` populates `~/.skynet/prompts/<role>.md` and `~/.skynet/policies/*.yml` with the framework's defaults. These are versioned; an `uv tool upgrade` updates them automatically on next run, and the framework refuses to start if its bundled prompts diverge from the on-disk copies (you'll be prompted to re-run `bootstrap`).

### 2.2 Windows

```powershell
# Install uv if you don't have it
winget install astral-sh.uv

# Install the framework
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry

# Verify
skynet --version

# Create the config directory
New-Item -ItemType Directory -Path "$env:USERPROFILE\.skynet\prompts" -Force
New-Item -ItemType Directory -Path "$env:USERPROFILE\.skynet\policies" -Force

# Pull versioned prompts/policies
skynet bootstrap
```

Windows hosts also need WSL2 with Ubuntu 24.04 for the Linux-only toolchain (bitbake, shellcheck). Verify:

```powershell
wsl -l -v                  # should show Ubuntu-24.04, version 2
wsl -- bash -c "which gh"  # confirms gh exists in WSL too
```

---

## 3. First-time setup

### 3.1 Fill in `.env`

Create `~/.skynet/.env` (Linux) or `%USERPROFILE%\.skynet\.env` (Windows). Copy from `.env.example` in the framework repo:

```bash
# REQUIRED
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GITHUB_TOKEN=ghp_...                              # fine-grained PAT, see §3.3
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# OPTIONAL — only if you'll use them
CODEX_API_KEY=
LOCAL_API_KEY=

# RESERVED for v1+ — leave blank for now
SWU_SIGNING_KEY_PATH=
KASA_USERNAME=
KASA_PASSWORD=
TAILSCALE_AUTH_KEY=
GCP_VM_SSH_KEY_PATH=
```

### 3.2 Authenticate subscription CLIs (optional but recommended)

If you have a Claude Pro/Max subscription and want Skynet to route through it (free up to plan cap):

```bash
claude login
```

Same for ChatGPT/Codex:

```bash
codex login
```

Both store OAuth credentials locally. The orchestrator will use them via the `claude_cli` and `codex_cli` provider types.

### 3.3 GitHub PAT

Generate at <https://github.com/settings/personal-access-tokens>. Required scopes: `contents` (read+write), `issues` (read+write), `pull_requests` (read+write), `metadata` (read). Restrict to the target repo(s) you'll operate on.

Why a PAT instead of `gh auth login`: the orchestrator runs as a system service and cannot reach the interactive `gh auth` keyring. The PAT is read once at startup from `.env` and used by `gh` via the `GITHUB_TOKEN` environment variable.

### 3.4 Fill in `pipeline.local.toml`

Copy `pipeline.example.toml` from the framework repo to `~/.skynet/pipeline.local.toml`. Edit the host-specific bits:

```toml
[host]
workspace_root = "/home/vinun/skynet/workspace"   # or C:/Users/vinun/skynet/workspace
state_root = "/home/vinun/skynet/state"
env_file = "/home/vinun/.skynet/.env"

[host.wsl]                                         # Windows only
distro = "Ubuntu-24.04"

[github]
operator_handle = "vinu-dev"
strict_account_check = true

[budget]
host_daily_dollars = 100                           # cap across all targets
host_concurrent_tasks = 4
```

### 3.5 Register the services

```bash
skynet service install
```

On Linux: writes systemd units to `~/.config/systemd/user/skynet-orchestrator.service` and `~/.config/systemd/user/skynet-watchdog.service`, enables them, starts them.

On Windows: creates NSSM services `skynet-orchestrator` and `skynet-watchdog`, configures them to run as your user account (so they can read your `claude` and `codex` subscription credentials), enables auto-start, starts them.

Verify:

```bash
skynet status

# Output should look like:
#   orchestrator: running (pid 12345, uptime 2m, last task: --)
#   watchdog:     running (pid 12346, last poll: 30s ago)
#   targets:      0 active
#   budget today: $0.00 / $100.00
```

You're done with the host setup. The services will now run forever, surviving reboots.

---

## 4. Onboarding a target repository

### 4.1 Initialize the target

```bash
skynet init --target git@github.com:vinu-dev/rpi-home-monitor.git
```

This:

1. Clones the target locally.
2. Creates a branch `skynet/init/compliance-scaffold`.
3. Adds the required files: `.skynet/config.yml` (with sensible defaults), `docs/ai/plans/.gitkeep`, `docs/ai/designs/.gitkeep`, `docs/ai/risk-register.md`. If `docs/ai/` already has standard files (mission-and-goals.md etc.), they're preserved.
4. Pushes the branch.
5. Opens a PR titled `[skynet] Add Compatibility Spec scaffolding`.

You review the PR, edit `.skynet/config.yml` to your taste, and merge.

### 4.2 Configure role assignments

The default `.skynet/config.yml` from `skynet init` looks roughly like:

```yaml
skynet_version: ">=0.4,<1.0"

project:
  name: "rpi-home-monitor"
  languages: ["python", "yocto"]

defaults:
  primary:    { provider: anthropic, model: claude-sonnet-4-6 }
  fallbacks: []

agents:
  researcher:    { schedule: "0 * * * *", max_per_day: 5 }
  architect:     { primary: { provider: anthropic, model: claude-opus-4-7 } }
  implementer:   {}
  tester:        {}
  pr_author:     {}
  reviewer:      { primary: { provider: openai, model: gpt-5 } }     # different vendor (rule)
  release:       { enabled: false }

# ... rest is mostly defaults
```

Edit before merging. Common patterns:

#### Pattern A: Subscription-first cost optimization

```yaml
providers:
  claude_sub:
    type: claude_cli
    binary_path: claude

  codex_sub:
    type: codex_cli
    binary_path: codex

defaults:
  primary:    { provider: claude_sub, model: claude-sonnet-4-6 }
  fallbacks: [{ provider: anthropic, model: claude-sonnet-4-6 }]    # API safety net

agents:
  researcher:    {}                                                  # claude_sub primary
  architect:
    primary:    { provider: claude_sub, model: claude-opus-4-7 }
    fallbacks: [{ provider: anthropic, model: claude-opus-4-7 }]
  implementer:   {}                                                  # subscription primary
  tester:        {}
  pr_author:     {}
  reviewer:
    primary:    { provider: codex_sub, model: gpt-5 }
    fallbacks: [{ provider: openai, model: gpt-5 }]
```

Result: every routine call goes against your subscriptions (free up to plan cap). When a cap hits, watchdog falls over to API. Maximum subscription value, guaranteed availability.

#### Pattern B: Local model for review

```yaml
providers:
  my_llama:
    type: openai_compatible
    base_url: http://localhost:11434/v1            # ollama on this host

agents:
  reviewer:
    primary:    { provider: my_llama, model: llama-3.1-70b }
    fallbacks: [{ provider: openai, model: gpt-5 }]    # if local is down
```

Local model is fast and zero-marginal-cost for routine review; cloud fallback covers when it's down or insufficient.

#### Pattern C: Different model per role

```yaml
agents:
  researcher:  { primary: { provider: claude_sub, model: claude-sonnet-4-6 } }
  architect:   { primary: { provider: anthropic, model: claude-opus-4-7 } }
  implementer: { primary: { provider: codex_sub, model: gpt-5 } }
  tester:      { primary: { provider: claude_sub, model: claude-haiku-4-5 } }   # cheaper
  pr_author:   { primary: { provider: claude_sub, model: claude-sonnet-4-6 } }
  reviewer:    { primary: { provider: my_llama, model: llama-3.1-70b } }
  release:     { primary: { provider: anthropic, model: claude-sonnet-4-6 } }
```

Six different model + provider combinations. Each role uses what's best for it.

### 4.3 Validate the config

After merging the init PR:

```bash
skynet doctor --target git@github.com:vinu-dev/rpi-home-monitor.git
```

Output:

```
Compatibility Spec  : v0.4
Installed framework : 0.4.2
Detected level      : standard

REQUIRED FILES                  ✓ all present
CONFIG SCHEMA                   ✓ valid
  ✓ multi-vendor: implementer (anthropic) ≠ reviewer (openai)
  ✓ budget caps configured
LABELS                          ✓ all 11 created in target
PROVIDERS
  ✓ claude_sub  (claude --version → 0.5.1, login OK)
  ✓ codex_sub   (codex --version → 0.3.0, login OK)
  ✓ anthropic   (API ping OK, model 'claude-sonnet-4-6' available)
  ✓ openai      (API ping OK, model 'gpt-5' available)

RESULT: PASS (level: standard)
```

If anything fails, fix the config and re-run.

### 4.4 Add to the rotation

```bash
skynet target add --repo git@github.com:vinu-dev/rpi-home-monitor.git
```

The orchestrator now schedules tasks against this target. The Researcher will start within an hour (next cron tick).

---

## 5. Day-to-day operation

### 5.1 What to expect

In the first 24 hours you'll see Discord pings like:

- *Researcher created issue #173: "[SKY-2026-000124] Add audio recording"*
- *Issue #173 labeled `skynet/research-draft`. Auto-promote in 24h unless vetoed.*

When you decide to act on an issue, label it `skynet/designed` from the GitHub UI (or use `skynet promote 173`). The pipeline takes over from there.

Throughout the day:

- *Architect committed design `SKY-2026-000124-audio-recording.md`*
- *Implementer opened branch `skynet/SKY-2026-000124/audio-recording`*
- *Tester: 3 tests failed, retrying*
- *PR #88 opened, review in progress*
- *Reviewer approved, hold-soft started, Operator can veto for 24h*
- *PR #88 merged*

You do nothing except occasionally label, occasionally veto.

### 5.2 The skynet CLI

```bash
skynet status                         # high-level: services, targets, budget
skynet status --target <repo>          # per-target status
skynet status --task <task-id>         # one task's full state

skynet logs <task-id>                  # full structured log
skynet logs <task-id> --follow         # tail live

skynet pause                           # pause all dispatch (in-flight tasks finish)
skynet pause --target <repo>           # pause one target
skynet pause --task <task-id>          # pause one task (e.g. veto a soft-hold)
skynet resume [...]                    # opposite of pause

skynet kick <agent>                    # restart a specific agent worker
skynet replay <task-id>                # restart a task from a chosen state
skynet quarantine <task-id>            # stop all retries, mark needs-human

skynet config get <path>               # e.g. agents.implementer.primary.model
skynet config set <path> <value>
skynet config show --role implementer  # resolved (post-defaults, post-overrides) view
skynet config providers list

skynet doctor --target <repo>          # validate compliance
skynet unlock <policy>                 # operator override (requires auth token)
```

### 5.3 Vetoing a soft-hold PR

When a PR enters `policy: soft`, the Discord notification includes a link and a deadline. To veto:

```bash
skynet pause --task SKY-2026-000124
```

The orchestrator removes the auto-merge schedule and labels the PR `skynet/needs-human`. You then merge or close it manually.

### 5.4 Changing a model assignment

Mid-stride model swap:

```bash
# CLI (simple values)
skynet config set agents.implementer.primary.provider codex_sub
skynet config set agents.implementer.primary.model gpt-5

# OR edit .skynet/config.yml in the target repo and merge the change
```

Either way, the orchestrator picks up the change on the next task dispatch. In-flight tasks keep their captured config.

### 5.5 Adding a new provider

Edit the target's `.skynet/config.yml`, add to `providers:` block, reference in agent assignments, push. Re-run `skynet doctor` — if it passes, the orchestrator picks it up on next dispatch.

```yaml
providers:
  vllm_box:                                         # NEW
    type: openai_compatible
    base_url: http://192.168.1.20:8000/v1
    api_key_env: VLLM_API_KEY

agents:
  implementer:
    primary:    { provider: vllm_box, model: deepseek-coder-33b }   # NEW
    fallbacks: [{ provider: anthropic, model: claude-sonnet-4-6 }]
```

Don't forget to add the API key to `~/.skynet/.env`.

---

## 6. Common situations

### 6.1 Subscription rate limit hit

Discord: *agents.implementer hit RATE_LIMITED on claude_sub. Backing off 30s, then falling back to anthropic.*

Action needed: **none.** The orchestrator handles it. Watch the budget with `skynet status` if you're worried about API spend.

### 6.2 Local model crashed (OOM, etc.)

Discord: *agents.reviewer CRASH detected (my_llama). Restarting once...* (later) *...crashed again. Falling back to openai.*

Action needed: **none for the task**, but you might want to restart your local model runtime so the next task uses it again:

```bash
sudo systemctl restart ollama          # or however you run yours
```

### 6.3 Task stuck in `quarantined`

Discord: *task SKY-2026-000124 quarantined after retry-cap exceeded.*

Inspect:

```bash
skynet logs SKY-2026-000124
```

Decide:

- **Try again:** `skynet replay SKY-2026-000124 --from agent-ready` (restart from a clean state)
- **Give up:** `skynet quarantine SKY-2026-000124 --close` (closes the issue, deletes the branch)
- **Take it manually:** read the work product so far and finish it yourself

### 6.4 Budget exhausted

Discord (immediate, bypasses batch): *BUDGET EXHAUSTED — daily $100 cap reached. All agents paused until 00:00 UTC.*

Action needed: either wait for reset, or override:

```bash
skynet unlock budget --token <your-token>
```

The unlock token is set up during `skynet service install` and stored in a file readable only by you. The agents can never read it. Without it, no override is possible.

### 6.5 Audit-reject burst

Discord (immediate): *agents.implementer audit-reject-burst (4 in 60s). Task SKY-2026-000124 quarantined.*

This means the agent tried to write outside its workspace 4+ times in one minute. Likely causes:

- A bug in a tool wrapper (rare, would affect all tasks)
- Prompt injection from researched content (most common)
- Misconfigured allowlist for that role

Inspect logs, decide if it's a one-off or systemic.

### 6.6 You want to update the framework

```bash
uv tool upgrade skynet-agentry

# After upgrade, restart services to pick up new code
sudo systemctl --user restart skynet-orchestrator skynet-watchdog

# Re-run bootstrap to refresh prompts/policies
skynet bootstrap
```

The framework follows semver. Patch and minor updates are safe. Major updates may require running:

```bash
skynet migrate --target <repo> --from 0.x --to 0.y
```

…which opens a PR on the target updating its `.skynet/config.yml` to the new schema.

---

## 7. Troubleshooting

### Orchestrator won't start

```bash
sudo systemctl --user status skynet-orchestrator
journalctl --user -u skynet-orchestrator -e
```

Common causes:

- `.env` file missing or unreadable
- Sqlite DB locked by another process (check for stale `.db-shm` files)
- Target's `skynet doctor` fails (orchestrator refuses to start with broken targets)

### Agent never spawns

Check `skynet status --target <repo>`. If you see tasks but no agent activity:

- Budget exhausted? `skynet config get budget`
- Concurrency cap hit? `skynet status` shows active task count
- Provider unreachable? Try `skynet doctor --target <repo>`

### Service running as wrong user (Windows)

Symptom: `claude_cli` provider reports "not authenticated" even though `claude login` succeeded interactively.

NSSM by default runs services as `LocalSystem`. The service can't read your user's OAuth credentials. Fix:

```powershell
# Stop services
sc stop skynet-orchestrator
sc stop skynet-watchdog

# Configure to run as your user
nssm set skynet-orchestrator ObjectName .\<your-username> <your-password>
nssm set skynet-watchdog ObjectName .\<your-username> <your-password>

# Start again
sc start skynet-orchestrator
sc start skynet-watchdog
```

`skynet service install` does this automatically; this is only relevant if you're debugging an existing install.

### Discord notifications not arriving

```bash
# Manual ping test
skynet notify test
```

If that fails, check `DISCORD_WEBHOOK_URL` in `.env`. Discord webhook URLs expire if the channel is deleted; regenerate via Server Settings → Integrations → Webhooks.

### Task IDs collide / weird counter behavior

If the sqlite DB is corrupted, task IDs may behave strangely. Recovery:

```bash
skynet pause                                                # stop dispatch
sqlite3 ~/skynet/state/skynet.db "VACUUM;"                  # rebuild
sqlite3 ~/skynet/state/skynet.db ".schema task_counters"    # verify schema
skynet resume
```

If you genuinely lost the DB, `skynet recover` rebuilds task state from GitHub labels and PRs. In-flight checkpoints are lost (those tasks restart from `agent-ready`).

---

## 8. Operator hygiene

A few habits that pay off:

- **Read your daily Discord digest.** It's the cheapest way to stay aware of what's shipped, what's stuck, and how much you're spending.
- **Review weekly.** Open the target repo's GitHub view, scan merged PRs, see what the system has shipped this week. Spot patterns (stuck on the same kind of bug? prompts may need updates).
- **Treat the budget as a feature.** Set it tight at first ($10-20/day) until you trust the system. Raise it when you're comfortable.
- **Use the soft-hold window.** It's the cheap insurance against bad merges. 24 hours is enough to catch most things, low enough to not slow shipping.
- **Don't over-tune the roster too quickly.** Start with the defaults `skynet init` produces. Watch one target run for two weeks. Then optimize.

---

## 9. Where to get help

- **Architecture questions:** [`docs/architecture.md`](architecture.md)
- **Compatibility / target onboarding:** [`COMPATIBILITY-SPEC.md`](../COMPATIBILITY-SPEC.md)
- **Build plan / what's coming:** [`docs/v0.1-plan.md`](v0.1-plan.md)
- **Schema reference:** [`schemas/skynet-config.schema.json`](../schemas/skynet-config.schema.json)
- **Operator quick reference:** this document

---

*End of how-to-use.md.*
