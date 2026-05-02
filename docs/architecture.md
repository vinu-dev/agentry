# Skynet Agentry — Architecture

Status: **v0.0a-1 (revised, pre-implementation)**

This document is the architectural source of truth for Skynet Agentry — an autonomous multi-agent product organization framework. Companion documents:

| Document | Purpose |
|----------|---------|
| `docs/architecture.md` (this file) | Architecture and design |
| `docs/how-to-use.md` | Operator's practical guide |
| `docs/v0.1-plan.md` | Concrete build plan for v0.1 |
| `COMPATIBILITY-SPEC.md` | Contract for target repositories |
| `schemas/skynet-config.schema.json` | Machine-checkable schema |
| `pipeline.example.toml` | Per-PC config template |
| `.env.example` | Secrets template |

---

## 1. Purpose

**Skynet Agentry is an orchestrator + watchdog pair** that runs continuously on a single host, rents AI worker agents from cloud and local providers, assigns them roles (Researcher, Architect, Implementer, Tester, PR Author, Reviewer, Release Engineer), and drives every task to completion despite stalls, rate limits, capability gaps, and crashes.

The agents themselves are commodity workers — Claude today, GPT-5 today, a local Llama tomorrow, whatever model the Operator assigns. **The orchestrator is the value.** It turns stochastic, fragile, cost-incurring AI calls into deterministic, supervised, completed tasks, with the Operator (the human running it) reserved for emergency overrides, policy changes, and onboarding new targets.

It is **not**:

- a pair-programming assistant — use Claude Code, Cursor, or Copilot
- a one-shot code generator — use GPT Engineer or smol-developer
- a multi-agent conversation framework — use AutoGen, LangGraph, or CrewAI as substrates
- a CI/CD system — it complements one, doesn't replace one

It is a **headless contractor**: install once on a host, point it at a target repository, it ships features.

---

## 2. Mental Model — The Contractor Metaphor

> Skynet Agentry is a contractor you hire once. You give it a job description (`.skynet/config.yml`). It hires gig workers from the AI spot market — Anthropic, OpenAI, your local Llama. It supervises them, fires the ones that don't work, calls in backups. You get a Discord ping when something interesting happens. Sensitive changes get a 24-hour hold so you can veto; everything else just ships.
>
> The **orchestrator** is the contractor's PM.
> The **watchdog** is the contractor's HR — handles workers who don't show up.
> The **agents** are gig workers who do one task and leave.
> The **target repo** is the project the contractor is hired to ship.

This metaphor is load-bearing for the architecture: cost optimization, fault tolerance, model diversity, and operator ergonomics all flow from "hire-and-supervise" rather than "single-process-with-tools."

---

## 3. Two-Repo Model

Skynet Agentry is one of two repositories at runtime:

```
   ┌─────────────────────────┐          ┌──────────────────────────┐
   │  Skynet Agentry         │          │     Target repo          │
   │  (the framework)        │  acts on │  (e.g. rpi-home-monitor) │
   │                         │ ───────→ │                          │
   │  - orchestrator         │          │  - .skynet/config.yml    │
   │  - watchdog             │          │  - docs/ai/              │
   │  - agent runners        │          │  - docs/ai/plans/   ←────┼── researcher writes here
   │  - hardware drivers     │          │  - docs/ai/designs/ ←────┼── architect writes here
   │  - skynet CLI           │          │  - docs/history/specs/   │
   │  - service installers   │          │  - docs/ai/risk-register │
   └─────────────────────────┘          └──────────────────────────┘
       installed once per host             cloned per task by orchestrator
```

The framework is **generic**: it knows nothing about any particular target. A target declares conformance to the **Skynet Compatibility Spec** and provides a `.skynet/config.yml` describing its build commands, test commands, sensitive paths, hardware (if any), provider declarations, and per-role model assignments.

Target repositories contain only metadata and placeholder directories. They never copy framework source.

The **canonical reference target** is `vinu-dev/rpi-home-monitor`. Its existing `docs/ai/` operating system is the model the Skynet Compatibility Spec generalizes from.

---

## 4. Distribution & Platform Support

### 4.1 Distribution as a CLI tool

Skynet Agentry follows the GoogleTest distribution pattern: it is installed as a CLI tool, never copied into target repositories.

```bash
# On Linux
uv tool install skynet-agentry
# or
pipx install skynet-agentry

# On Windows (PowerShell)
uv tool install skynet-agentry

# While the framework is private, install via SSH:
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
```

Updates: `uv tool upgrade skynet-agentry`. No git pull, no bootstrap re-run on every host.

Same target repo works across multiple operator hosts simultaneously; each operator runs their own orchestrator instance pointing at the same target. No coordination between hosts is required at the framework level (operator coordination happens via GitHub: branch naming, label transitions, PRs).

### 4.2 Linux-first, Windows-supported

Skynet Agentry is **Linux-first**: systemd is the primary service supervisor, native shell tooling (`gh`, `git`, `pytest`, `bitbake`, `ssh`) is invoked directly, paths use POSIX conventions, file locking and process management follow Unix semantics.

**Windows is a supported secondary platform**. NSSM serves as the equivalent of systemd; WSL2 hosts the Linux-only toolchain (`bitbake`, `shellcheck`); Windows-native tooling is used where it suffices (`git`, `gh`, `python`).

| Concern | Linux | Windows |
|---------|-------|---------|
| Service supervision | systemd unit files | NSSM service definitions |
| Linux toolchain | native | WSL2 |
| Service account | systemd `User=` directive | NSSM "Log on as" tab (must be operator user, not SYSTEM, for OAuth subscription auth) |
| Path conventions | POSIX | `pathlib` resolves both styles |
| Process kill | unix signals + process groups | `taskkill /T /F` |
| Filesystem | atomic rename, sane locking | path length, occasional file-in-use |

The codebase branches on `sys.platform` for the small set of platform-divergent concerns. Most of the framework is identical across both.

**Recommended deployment topology:**

| Topology | Setup | When |
|----------|-------|------|
| Native Linux host | systemd | Production / dedicated box |
| Linux VM on Windows host | systemd inside Hyper-V or VirtualBox; hardware passthrough | Recommended for daily-driver Windows users |
| Windows host directly | NSSM + WSL2 | Prototyping / single-machine simplicity |
| Cloud Linux VM (GCP/AWS) | systemd | Production with Tailscale-reachable hardware |

---

## 5. System Context

```
                          ┌────────────────────────┐
                          │ Anthropic API (Claude) │  ← researcher, architect, implementer,
                          └────────────┬───────────┘    tester, pr_author, fallback for reviewer
                                       │
                          ┌────────────▼───────────┐
                          │ OpenAI API (GPT-5)     │  ← reviewer (different vendor on purpose);
                          └────────────┬───────────┘    fallback for any role
                                       │
                          ┌────────────▼───────────┐
                          │ Claude Code subscription│ ← any role (subscription-routed, free
                          │  via `claude` CLI       │   up to plan cap)
                          └────────────┬───────────┘
                                       │
                          ┌────────────▼───────────┐
                          │ Codex CLI subscription  │ ← reviewer or implementer
                          │  via `codex` CLI        │   (subscription-routed)
                          └────────────┬───────────┘
                                       │
                          ┌────────────▼───────────┐
                          │ Local model runtime     │ ← any role; cheap or zero marginal cost
                          │ (ollama / lm-studio)    │
                          └────────────┬───────────┘
                                       │
   ┌──────────┐  ┌──────────────────────────────────────┐  ┌─────────────────┐
   │ Operator │─→│                                      │─→│ GitHub          │
   │ (rare    │  │       Host (Linux or Windows 11)     │  │ - target repo   │
   │  inputs, │  │       Always-on, supervised services │  │ - issues / PRs  │
   │  unlocks)│  │                                      │  └─────────────────┘
   └──────────┘  │                                      │
                 │                                      │  ┌─────────────────┐
                 │                                      │─→│ GCP VM          │
                 │                                      │  │ Yocto sstate    │
                 │                                      │  │ cache + builds  │
                 └────────────┬─────────────────────────┘  └─────────────────┘
                              │
                              │ USB-TTL serial + SSH (v1+, deferred from v0)
                              ▼
                 ┌──────────────────────────┐
                 │  Pi camera + Pi server   │
                 │  (test rig, optional)    │
                 └──────────────────────────┘

                 ┌──────────────────────┐
                 │  Discord webhook     │  ← all observability (batched, 60s flush)
                 └──────────────────────┘
```

External dependencies are **per-provider, configured by the Operator**, not hard-coded. The framework's only mandatory external is GitHub (where target repositories live) and Discord (single notification channel in v0).

---

## 6. The Orchestrator (the spine)

The orchestrator is the long-running daemon that owns scheduling, dispatch, state, and the operator-facing CLI. It is the piece that makes Skynet Agentry "Skynet Agentry."

```
┌─ skynet-orchestrator ────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌─ Boot sequence (once at startup) ──────────────────────────────────────┐│
│  │  1. Read pipeline.local.toml (host-level config)                       ││
│  │  2. Load .env from configured path                                     ││
│  │  3. Open state/skynet.db, run migrations                               ││
│  │  4. For each target in `targets`: clone or fetch, run skynet doctor    ││
│  │  5. Refuse to start if any target fails doctor                         ││
│  │  6. Start scheduler, dispatcher, supervisor coroutines                 ││
│  │  7. Emit notification: "orchestrator started, N targets active"        ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─ Scheduler ────────────┐    ┌─ Task Dispatcher ──────────────────────┐  │
│  │ APScheduler            │───→│ - polls task queue (sqlite)            │  │
│  │ - hourly cron          │    │ - resolves agent assignment from config│  │
│  │ - on-event triggers    │    │ - looks up provider + model + fallback │  │
│  │ - GitHub label-watcher │    │ - checks budget, concurrency limits    │  │
│  └────────────────────────┘    │ - spawns agent worker subprocess       │  │
│                                │ - writes initial heartbeat row         │  │
│                                └──────────────┬─────────────────────────┘  │
│                                               │                             │
│  ┌─ Provider Registry ─────────┐              │                             │
│  │ AnthropicProvider           │←─ resolve ──┤                             │
│  │ OpenAIProvider              │              │                             │
│  │ CodexCLIProvider            │              │                             │
│  │ ClaudeCLIProvider           │              │                             │
│  │ OpenAICompatibleProvider    │              │                             │
│  │ AnthropicCompatibleProvider │              │                             │
│  │ (custom providers from yml) │              │                             │
│  └─────────────────────────────┘              ▼                             │
│                                ┌─ Tool Layer (sandboxed) ────────────────┐ │
│  ┌─ State Manager ─────────┐   │                                          │ │
│  │ sqlite repo             │   │  ┌────────────────────────────────────┐ │ │
│  │ - tasks, events         │   │  │ ToolWrapper                        │ │ │
│  │ - heartbeats, budget    │   │  │  - path allowlist                  │ │ │
│  │ - task_counters (IDs)   │   │  │  - command allowlist (per agent)  │ │ │
│  │ - checkpoints           │   │  │  - sensitive-path detector        │ │ │
│  └─────────────────────────┘   │  │  - audit log                       │ │ │
│                                │  │  - budget tracker                  │ │ │
│  ┌─ Notifier (Discord) ────┐   │  └────────────────────────────────────┘ │ │
│  │ - batched 60s flush     │←──┴───────────────────────────────────────────┘ │
│  │ - per-event severity    │                                                 │
│  │ - rate-limit aware      │                                                 │
│  └─────────────────────────┘                                                 │
│                                                                              │
│  ┌─ Policy Engine ─────────────┐    ┌─ Heartbeat Bus ──────────────────┐  │
│  │ - parse .skynet/config.yml  │    │ - read agent heartbeats          │  │
│  │ - resolve path policies     │    │ - publish to watchdog            │  │
│  │ - most-restrictive wins     │    └──────────────────────────────────┘  │
│  │ - veto handling             │                                            │
│  └─────────────────────────────┘                                            │
│                                                                              │
│  ┌─ CLI / IPC ─────────────────────────────────────────────────────────┐   │
│  │  Unix domain socket (Linux) / named pipe (Windows)                  │   │
│  │  Handles: skynet status, pause, resume, kick, replay, quarantine    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Key properties:**

- **Stateless restart.** All state lives in sqlite. The orchestrator can crash and resume from sqlite checkpoint without losing in-flight tasks.
- **Single-writer to sqlite.** WAL mode; only the orchestrator writes. Agents communicate via heartbeat files that the orchestrator polls and writes to sqlite.
- **No agent persistence.** Agent workers are short-lived subprocesses; they have no shared memory with the orchestrator and no surviving state of their own. All durable state is the orchestrator's.
- **Schedule sources.** Three trigger types: cron (Researcher hourly), event (GitHub label change → state transition), explicit (Operator CLI command).

---

## 7. The Watchdog (the safety net)

The watchdog is a separate process, supervised by the same init system as the orchestrator (systemd or NSSM). Two-tier supervision: the watchdog supervises the orchestrator AND the agent workers; the init system supervises the watchdog. Neither component is a single point of failure.

```
┌─ skynet-watchdog ────────────────────────────────────────────────────────┐
│                                                                          │
│  ┌─ Heartbeat Poller (every 60s) ───────────────────────────────────┐  │
│  │                                                                   │  │
│  │  for each agent in state.heartbeats:                              │  │
│  │      if agent.last_seen > 5 min:           → STALLED              │  │
│  │      if agent.process.exit_code != None:    → exit-code classify  │  │
│  │      if agent.tokens_used > task_cap:       → CAPABILITY (likely) │  │
│  │      if budget.daily_dollars > host_cap:    → BUDGET-EXHAUSTED    │  │
│  │                                                                   │  │
│  │  for orchestrator:                                                │  │
│  │      if orchestrator.heartbeat > 90s:       → restart orchestrator│  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Failure Classifier ─────────────────────────────────────────────┐  │
│  │                                                                   │  │
│  │  Inputs: exit_code, last_log_line, http_status, heartbeat_age,    │  │
│  │          tokens_used, retry_count, diff_signature_history         │  │
│  │                                                                   │  │
│  │  Outputs: { CRASH | CAPABILITY_EXCEEDED | RATE_LIMITED |          │  │
│  │             STALLED | BUDGET_EXHAUSTED | NORMAL }                  │  │
│  │                                                                   │  │
│  │  All deterministic. No LLM in the watchdog loop.                  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Recovery Engine ─────────────────────────────────────────────────┐  │
│  │                                                                   │  │
│  │  CRASH               → spawn fresh agent from last checkpoint     │  │
│  │  CAPABILITY_EXCEEDED → escalate to next fallback (stronger model) │  │
│  │  RATE_LIMITED        → exponential backoff w/ jitter,             │  │
│  │                        then fallback to next provider             │  │
│  │  STALLED             → SIGTERM, wait 30s, SIGKILL,                │  │
│  │                        restart once, then quarantine              │  │
│  │  BUDGET_EXHAUSTED    → pause all agents, notify, await reset      │  │
│  │                                                                   │  │
│  │  Per-role overrides allowed via .skynet/config.yml                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Escalation Channel ──────────────────────────────────────────────┐  │
│  │                                                                   │  │
│  │  All recovery actions emit events for the Notifier to flush.      │  │
│  │  Critical events (BUDGET_EXHAUSTED, audit-reject-burst,           │  │
│  │  multiple consecutive quarantines) bypass the 60s batch and       │  │
│  │  emit immediately.                                                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Critical design choice — the watchdog is deterministic.** It uses fixed rules to detect liveness, classify failures, and take recovery actions. No LLM is in the watchdog loop, because an LLM watchdog would be a single point of stochastic failure. The framework's reliability comes from this layer being predictable.

---

## 8. Failure Handling

The orchestrator must handle four classes of failure that any AI worker can produce. Each has a deterministic recovery action, with per-role configuration.

### 8.1 CRASH

**Definition:** Subprocess died unexpectedly. PID gone, no graceful exit, possibly SIGKILL or segfault, or a Python uncaught exception that exited non-zero.

**Detection:** Heartbeat absent + process tree empty. Or: exit code observed and ≠ 0 and ≠ known recovery codes (42 = rate limit, 43 = capability exceeded, 44 = quarantine signal).

**Recovery:** Read last sqlite checkpoint, spawn fresh agent subprocess from that checkpoint. Increment retries counter. If retries exceed `budget.retry_cap`, escalate to STALLED quarantine path.

### 8.2 CAPABILITY_EXCEEDED

**Definition:** The agent declares it cannot complete the task with its current model. Examples:
- Model says explicitly "I cannot do this" (parsed from output)
- Repeated failures with the same diff signature (3× same patch rejected)
- Output is detectably wrong (test output reveals confusion, not just bug)

**Detection:** Three signals, any of which triggers:
1. Exit code 43 (set when the agent self-declares incapable)
2. Diff-signature hash repeated 3× across review-failed cycles
3. Test failures with same root cause across 3 retries

**Recovery:** Escalate to the next entry in the role's fallback chain — typically a stronger model. If implementer is on `sonnet`, escalate to `opus`. If reviewer is on a local model, escalate to OpenAI. If the chain is exhausted, quarantine.

### 8.3 RATE_LIMITED

**Definition:** Provider returned a rate-limit response, or subscription daily/window cap hit, or budget cap reached.

**Detection:**
- HTTP 429 from cloud provider
- Subscription CLI returns rate-limit indicator (Claude Code: "you've reached your message limit")
- Internal budget tracker says daily $ cap hit
- Internal counter says max_per_day exceeded for Researcher

**Recovery:** Exponential backoff with jitter (start 30s, double per attempt, cap 30min). After 3 backoff attempts on the same provider, fall back to the next provider in the chain. If chain is exhausted AND budget is the cause, pause until budget resets (next day UTC).

This is also the cost-optimization mechanism: subscription-first config lets the orchestrator drain free credits before paying API tokens.

### 8.4 STALLED

**Definition:** Agent is not making progress. Subprocess alive but no token output, no heartbeat update, possibly stuck on a tool call that's hanging.

**Detection:** Heartbeat `last_action` more than 5 minutes ago, OR no token output in 3 minutes despite alive process.

**Recovery:** SIGTERM (graceful kill). Wait 30s. If still alive, SIGKILL. Restart fresh from checkpoint. If the same task stalls twice, quarantine — do not retry further. Notify operator.

### 8.5 Per-role overrides

Each role's `.skynet/config.yml` block may override defaults:

```yaml
agents:
  reviewer:
    on_rate_limit: backoff_then_fallback        # default
    on_capability_exceeded: quarantine          # don't escalate, just stop
    on_stall: kill_retry_quarantine             # default
```

Default policy table:

| Role | on_rate_limit | on_capability_exceeded | on_stall |
|------|--------------|------------------------|----------|
| Researcher | backoff_then_fallback | escalate (Sonnet→Opus) | kill_retry_quarantine |
| Architect | backoff_then_fallback | escalate | kill_retry_quarantine |
| Implementer | backoff_then_fallback | escalate | kill_retry_quarantine |
| Tester | backoff_then_fallback | quarantine (don't escalate — Tester is lightweight) | kill_retry_quarantine |
| PR Author | backoff_then_fallback | quarantine | kill_retry_quarantine |
| Reviewer | backoff_then_fallback | quarantine | kill_retry_quarantine |
| Release Engineer | backoff_then_fallback | escalate | kill_retry_quarantine |

---

## 9. Provider Abstraction

The provider layer is the heart of model flexibility. The Operator decides which model handles which role; the orchestrator stays out of the way.

### 9.1 Built-in providers

Three are built-in and require no declaration:

| Name | Type | Auth | Use case |
|------|------|------|----------|
| `anthropic` | Anthropic API | `ANTHROPIC_API_KEY` | Cloud Claude, pay-per-token |
| `openai` | OpenAI API | `OPENAI_API_KEY` | Cloud GPT, pay-per-token |
| `codex_cli` | Codex CLI subprocess | OAuth via `codex login` | OpenAI/ChatGPT subscription routing |

### 9.2 Custom providers

Operator-declared, top of `.skynet/config.yml`:

```yaml
providers:
  my_llama:
    type: openai_compatible
    base_url: http://localhost:11434/v1     # ollama
    api_key_env: ""                          # blank = no key

  vllm_box:
    type: openai_compatible
    base_url: http://192.168.1.20:8000/v1
    api_key_env: VLLM_API_KEY

  team_proxy:
    type: anthropic_compatible
    base_url: http://internal-proxy.example.com
    api_key_env: TEAM_PROXY_KEY

  claude_sub:
    type: claude_cli
    binary_path: claude                      # uses `claude login` OAuth

  codex_sub:
    type: codex_cli
    binary_path: codex                       # uses `codex login` OAuth
```

Provider types:

| Type | Wire protocol | Auth |
|------|---------------|------|
| `openai_compatible` | OpenAI Chat Completions API shape | API key (or none for local) |
| `anthropic_compatible` | Anthropic Messages API shape | API key |
| `claude_cli` | Subprocess wrapper around `claude -p` | OAuth (`claude login`) |
| `codex_cli` | Subprocess wrapper around `codex` | OAuth (`codex login`) |

**`claude_cli` and `codex_cli` route through subscription credentials**, not API keys. This means every API call goes against your Pro/Max subscription quota instead of incurring per-token charges. The subscription has rate limits (Claude Pro: ~45 msgs / 5 hrs; Max 5×: ~225; Max 20×: ~900) — when those hit, the watchdog detects RATE_LIMITED and falls back to whatever's next in the role's chain (typically the API-key version of the same model).

### 9.3 Subscription + API hybrid (cost optimization)

The recommended pattern:

```yaml
providers:
  claude_sub:
    type: claude_cli
    binary_path: claude

defaults:
  primary:    { provider: claude_sub, model: claude-sonnet-4-6 }
  fallbacks: [{ provider: anthropic,  model: claude-sonnet-4-6 }]   # API as safety net

agents:
  researcher:    {}                             # uses defaults → subscription primary
  implementer:   {}                             # same — exhaust sub before paying API
  # ...
```

Result: every routine call goes against the subscription (free up to plan cap). When the cap hits, the orchestrator transparently switches to the API for the rest of the window. When the next subscription window opens, it switches back. Operator gets maximum value from the subscription and still has guaranteed availability.

### 9.4 Multi-vendor enforcement

The framework enforces **one** rule on provider selection: implementer's vendor MUST differ from reviewer's vendor. Vendors normalize:

| `provider` value | Vendor |
|------------------|--------|
| `anthropic`, `claude_cli` | `anthropic` |
| `openai`, `codex_cli` | `openai` |
| `local`, `openai_compatible` (default) | depends on model — operator-asserted |

Reason is structural: a Claude-on-Claude review shares training distribution and biases. Real review needs real independence. `skynet doctor` rejects configs that violate this.

---

## 10. Agent Roles

Seven roles. Each is a stateless function from `(task, prompt, tools)` to `(state-change, side-effects)`. Prompts live in `~/.skynet/prompts/<role>.md`; side-effects are git operations and event emission.

| Role | Trigger | Reads | Writes | Default model |
|------|---------|-------|--------|---------------|
| **Researcher** | hourly cron, max_per_day cap | target's `docs/ai/`, web search, competitor sources | GitHub issue with `skynet/research-draft` | Claude Sonnet 4.6 |
| **Architect** | issue promoted to `designed` | issue body, target's `docs/ai/`, `risk-register.md`, ADRs | `docs/ai/designs/<task-id>-*.md` | Claude Opus 4.7 |
| **Implementer** | issue at `agent-ready` | design doc, target codebase, test config | branch `skynet/<task-id>/<slug>`, code + unit tests | Claude Sonnet 4.6 |
| **Tester** | implementation complete | branch, target's test config | test results to sqlite, logs | Claude Sonnet 4.6 (light) |
| **PR Author** | tests green | branch, design doc, test results | GitHub PR with structured front-matter | Claude Sonnet 4.6 |
| **PR Reviewer** | PR open | PR diff, design doc, target's `docs/ai/`, `risk-register.md` | review comment, approval/changes-requested | **GPT-5 (different vendor)** |
| **Release Engineer** | merged + milestone (v1+) | merged commits, build config | Yocto build artifacts, GitHub Release | Claude Sonnet 4.6 |

Plus the meta-agent:

| Role | Type | Driven by |
|------|------|-----------|
| **Watchdog** | deterministic (no LLM) | Fixed rules — see §7 |

The agent prompts live in `~/.skynet/prompts/<role>.md` (versioned with the framework). A target may add `.skynet/prompt-extras/<role>.md` to provide project-specific context — the orchestrator concatenates it onto the framework prompt before invoking the agent.

---

## 11. Task Lifecycle

```
                       ┌──────────────────┐
                       │  research-draft  │
                       └────────┬─────────┘
                                │ Operator label flip OR auto-promote rule
                                ▼
                       ┌──────────────────┐
                       │     designed     │
                       └────────┬─────────┘
                                │ Architect writes design doc, commits
                                ▼
                       ┌──────────────────┐
                       │   agent-ready    │
                       └────────┬─────────┘
                                │ Orchestrator dispatches Implementer
                                ▼
                       ┌──────────────────┐
                       │   in-progress    │
                       └────────┬─────────┘
                                │ Implementer + Tester complete
                                ▼
                       ┌──────────────────┐
                       │     pr-open      │
                       └─┬────────┬────┬──┘
                         │        │    │
                         ▼        ▼    ▼
              ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │   approved   │  │ tests-failed │  │review-failed │
              └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                     │                 │                 │
                     │ Path policy     │                 │
                     │ resolves        │ Implementer retries (capped)
                     ▼                 │                 │
              ┌──────────────┐         └─→ in-progress ←─┘
              │    merged    │                  │
              └──────────────┘                  │ retry cap exceeded
                                                ▼
                                       ┌──────────────────┐
                                       │   quarantined    │
                                       └──────────────────┘
                                            (Operator)
```

Every state transition is persisted to sqlite atomically; checkpoints make every state resumable after a process crash.

---

## 12. Trust Boundaries

Four enforcement boundaries between the framework runtime and agent workers:

```
┌─ TRUSTED ZONE: framework runtime ───────────────────────────────────────┐
│                                                                         │
│   orchestrator (full FS, state writes)                                  │
│   watchdog     (full FS read)                                           │
│                                                                         │
│   ~/.skynet/prompts/      ← versioned, immutable at agent runtime      │
│   ~/.skynet/policies/     ← versioned, immutable at agent runtime      │
│   state/skynet.db         ← orchestrator only                          │
│   ~/.skynet/.env          ← API keys, never leave the framework        │
│                                                                         │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ spawn subprocess with restricted env
                               ▼
┌─ UNTRUSTED ZONE: agent worker ──────────────────────────────────────────┐
│                                                                         │
│   cwd = workspace/<task-id>/<target-clone>/                            │
│                                                                         │
│   Boundary 1 — Path                                                     │
│   ─ allowed: read/write inside cwd                                      │
│   ─ rejected: anything outside cwd, prompts/, policies/, state/         │
│                                                                         │
│   Boundary 2 — Command                                                  │
│   ─ allowed: per-agent shell allowlist                                  │
│     (Implementer: gh git ruff pytest; Tester: pytest playwright;        │
│      Reviewer: gh git; Researcher: curl gh; ...)                       │
│   ─ rejected: anything outside the allowlist                            │
│                                                                         │
│   Boundary 3 — Network                                                  │
│   ─ allowed: configured LLM provider, github.com API for the target,   │
│     web search hosts (Researcher only, allowlisted)                    │
│   ─ rejected: arbitrary outbound HTTP                                   │
│                                                                         │
│   Boundary 4 — Budget                                                   │
│   ─ daily-spend cap (cumulative across all agents)                      │
│   ─ per-task token cap                                                  │
│   ─ retry cap per state                                                 │
│   ─ concurrent-task cap                                                 │
│   ─ research-issues-per-day cap                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

Three enforcement layers:

1. **Subprocess env** — the orchestrator exports `TARGET_REPO`, `TASK_ID`, `ALLOWED_PATHS`, `DAILY_BUDGET_REMAINING`, `WORKSPACE_ROOT` once at spawn.
2. **Tool wrapper** — every Read, Write, Bash, and HTTP call is gated by an allowlist before reaching the LLM tool layer. Rejected calls raise structured errors; the agent must handle them or they count toward audit-reject-burst.
3. **Audit log + watchdog** — every rejected call is logged. More than 3 rejections within 60 seconds triggers an immediate Discord notification and quarantines the task.

---

## 13. State Model

All state lives in `state/skynet.db` (sqlite, WAL mode). Schema is intentionally small.

```sql
-- One row per task
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,           -- e.g. SKY-2026-000123
  target_repo     TEXT NOT NULL,              -- target git remote URL
  target_branch   TEXT,                       -- branch the agent created
  kind            TEXT NOT NULL,              -- research | design | implement | ...
  state           TEXT NOT NULL,              -- see lifecycle in §11
  retries         INTEGER NOT NULL DEFAULT 0,
  parent_id       TEXT REFERENCES tasks(id),
  checkpoint_json TEXT,                       -- agent-specific resumption data
  assigned_role   TEXT,                       -- which role currently holds this task
  resolved_provider TEXT,                     -- which provider was actually used last
  resolved_model  TEXT,                       -- which model was actually used last
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

-- Append-only event log
CREATE TABLE events (
  ts        INTEGER NOT NULL,
  task_id   TEXT NOT NULL REFERENCES tasks(id),
  agent     TEXT,
  type      TEXT NOT NULL,                    -- state-change, error, audit-reject, ...
  payload   TEXT                              -- JSON
);

-- Live heartbeat from each running agent worker
CREATE TABLE heartbeats (
  agent       TEXT PRIMARY KEY,
  task_id     TEXT,
  pid         INTEGER,
  last_seen   INTEGER NOT NULL,
  iteration   INTEGER NOT NULL,
  tokens_used INTEGER NOT NULL,
  status      TEXT NOT NULL                   -- alive | rate-limited | context-full | crashed
);

-- Daily cost ledger (budget boundary)
CREATE TABLE budget (
  date        TEXT NOT NULL,                  -- YYYY-MM-DD
  agent       TEXT NOT NULL,
  provider    TEXT NOT NULL,
  tokens_in   INTEGER NOT NULL DEFAULT 0,
  tokens_out  INTEGER NOT NULL DEFAULT 0,
  dollars     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (date, agent, provider)
);

-- Atomic task ID allocator (year-prefixed monotonic)
CREATE TABLE task_counters (
  year   INTEGER PRIMARY KEY,
  n      INTEGER NOT NULL DEFAULT 0
);
```

Crash recovery: on startup, the orchestrator reads all tasks not in a terminal state (`merged`, `quarantined`), reads their `checkpoint_json`, and resumes the agent from that checkpoint. There is **no in-memory state** that survives a process restart.

Task IDs follow `SKY-<year>-<6-digit-monotonic>` — see COMPATIBILITY-SPEC.md §9.

---

## 14. Policy Model

Auto-merge is governed by a path-policy table in the target's `.skynet/config.yml`.

### Policies

- **`hard`** — merge immediately on green CI + Reviewer approval.
- **`soft`** — merge after a hold window (default 24h) unless the Operator vetoes via `skynet pause <task-id>`.
- **`none`** — never auto-merge. Operator must intervene.

### Resolution algorithm

1. For every changed file in the PR, find the matching path policy (longest-glob wins; default applies if no glob matches).
2. Combine across files using **most-restrictive wins**: any `none` → `none`; else any `soft` → `soft`; else `hard`.
3. PR labeled and held according to effective policy.

### docs-only / tests-only guard

A PR resolves to `hard` only if **every** changed path matches one of the `hard` glob rules. This prevents agents from sneaking product code into a "docs PR."

---

## 15. Configuration Model

Two-layer configuration:

### 15.1 Target-level (`.skynet/config.yml`)

Committed in the target repo. Default for every Operator working on it.

```yaml
skynet_version: ">=0.4,<1.0"

project:
  name: "rpi-home-monitor"
  languages: ["python", "yocto"]

providers:
  my_llama:
    type: openai_compatible
    base_url: http://localhost:11434/v1
  claude_sub:
    type: claude_cli
    binary_path: claude

defaults:
  primary:    { provider: claude_sub, model: claude-sonnet-4-6 }
  fallbacks: [{ provider: anthropic,  model: claude-sonnet-4-6 }]
  on_rate_limit: backoff_then_fallback
  on_capability_exceeded: escalate
  on_stall: kill_retry_quarantine

agents:
  researcher:    { schedule: "0 * * * *", max_per_day: 5 }
  architect:
    primary:    { provider: claude_sub, model: claude-opus-4-7 }
    fallbacks: [{ provider: anthropic,  model: claude-opus-4-7 }]
  implementer:   {}                              # uses defaults
  tester:        {}
  pr_author:     {}
  reviewer:
    primary:    { provider: openai, model: gpt-5 }
    fallbacks: [{ provider: codex_cli, model: gpt-5 }]
  release:
    enabled: false                               # v0: off

test:
  unit: "pytest tests/unit"
  e2e: "npx playwright test"

auto_merge:
  default_policy: "soft"
  hold_hours: 24
  path_policies:
    "docs/**": hard
    "tests/**": hard
    "**/auth/**": none
    "**/ota/**": none

budget:
  daily_dollars: 50
  per_task_tokens: 200000
  retry_cap: 3
  concurrent_tasks: 2

notification:
  channel: discord
  webhook_env: DISCORD_WEBHOOK_URL
```

### 15.2 Host-level (`pipeline.local.toml`)

On each Operator's host. May override per-role assignments and other host-specific concerns. Gitignored.

```toml
[role_overrides.implementer]
provider = "anthropic"          # this op doesn't have Claude Code subscription
model = "claude-sonnet-4-6"

[role_overrides.reviewer]
provider = "openai"             # no local model on this PC
model = "gpt-5"
```

### 15.3 Resolution order

`host override` → `target default` → `framework default`. Per-role, per-field.

The orchestrator computes the effective config at task dispatch time and stores it in `tasks.checkpoint_json`. Config changes mid-task do not affect in-flight tasks.

---

## 16. Notification Model

Single channel in v0: **Discord webhook**, batched.

The notifier accumulates events for 60 seconds, then flushes a digest. Critical events (`quarantined`, `budget-cap-hit`, `audit-reject-burst`) bypass the batch and emit immediately.

Event taxonomy:

```
task-lifecycle:    task.created, task.state-changed, task.merged, task.quarantined
agent-events:      agent.started, agent.heartbeat-stale, agent.restarted, agent.crashed
provider-events:   provider.fallback-engaged, provider.rate-limited
policy-events:     policy.hold-started, policy.hold-completed, policy.veto-received,
                   policy.sensitive-blocked
budget-events:     budget.warning, budget.exhausted
audit-events:      audit.reject, audit.reject-burst
operator-events:   operator.unlock, operator.pause, operator.resume
```

A `Notifier` interface is defined now for v1+ extension to Telegram, email, etc.

---

## 17. Operator Workflow

The full lifecycle from "fresh host" to "tasks shipping autonomously."

### 17.1 Day 0 — Install (one time per host)

```bash
# Linux
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry

# Add secrets
$EDITOR ~/.skynet/.env
#   ANTHROPIC_API_KEY=...
#   OPENAI_API_KEY=...
#   GITHUB_TOKEN=...
#   DISCORD_WEBHOOK_URL=...

# Tell Skynet about this host
$EDITOR ~/.skynet/pipeline.local.toml

# Register the orchestrator + watchdog as systemd services (Linux)
skynet service install            # creates and enables systemd units

# (Windows: same command creates NSSM services)
```

The two services start automatically. They survive reboots.

### 17.2 Day 1 — Onboard a target repo

```bash
skynet init --target git@github.com:vinu-dev/rpi-home-monitor.git
```

This opens a PR on the target adding `.skynet/config.yml` (with sensible defaults), `docs/ai/plans/`, `docs/ai/designs/`, `docs/ai/risk-register.md`. The Operator reviews the PR, edits the config to assign roles to models:

```yaml
agents:
  researcher:  { primary: { provider: claude_sub, model: claude-sonnet-4-6 } }
  architect:   { primary: { provider: claude_sub, model: claude-opus-4-7 } }
  implementer: { primary: { provider: codex_sub,  model: gpt-5 } }
  tester:      { primary: { provider: claude_sub, model: claude-sonnet-4-6 } }
  reviewer:    { primary: { provider: my_llama,   model: llama-3.1-70b },
                 fallbacks: [{ provider: openai,  model: gpt-5 }] }
  pr_author:   { primary: { provider: claude_sub, model: claude-sonnet-4-6 } }
```

Merges. Then:

```bash
skynet target add --repo git@github.com:vinu-dev/rpi-home-monitor.git
```

Orchestrator validates with `skynet doctor`. Target enters rotation.

### 17.3 Day 2 — Watching it work

A typical day. The Operator does nothing but read Discord pings.

| Time | What happens | Who's working |
|------|--------------|---------------|
| 09:00 | Researcher wakes, opens issue `[SKY-2026-000124] Add audio recording` | Claude Sonnet (subscription) |
| 09:02 | Discord: *new research draft #173* | — |
| 12:00 | Operator (briefly) labels it `skynet/designed` | — |
| 12:01 | Architect writes design doc, opens tiny PR, auto-merges (docs-only = `hard`) | Claude Opus (subscription) |
| 12:30 | Implementer reads design, branches, writes code | GPT-5 (Codex subscription) |
| 13:15 | Tester runs pytest, 3 fail. Implementer fixes. Green on retry 2 | GPT-5, Claude Sonnet |
| 14:00 | PR Author opens PR. Reviewer (local Llama) approves. Path policy = `soft` → 24h hold | local Llama |
| 16:30 | GPT-5 hits subscription rate limit. Watchdog: classify RATE_LIMITED → fallback to OpenAI API | Watchdog → OpenAI API |
| 18:00 | Local Llama crashes (OOM). Watchdog: CRASH → restart, crash again → fallback to GPT-5 | Watchdog → GPT-5 |
| Day 3, 14:00 | Hold expires, no veto → auto-merge. Discord: *PR #88 merged* | — |

Operator-time: ~30 seconds (one label flip).

### 17.4 Day 30 — Operator changes their mind about a model

```bash
skynet config set agents.reviewer.primary.provider openai
skynet config set agents.reviewer.primary.model gpt-5
```

Or edits `.skynet/config.yml` directly. Orchestrator picks it up on next task.

### 17.5 When something goes wrong

```bash
skynet status                          # what's running, what's stuck
skynet logs SKY-2026-000124            # full log of one task
skynet replay SKY-2026-000124          # restart from any past state
skynet quarantine SKY-2026-000124      # stop retries, mark needs-human
skynet unlock <policy>                 # operator override (requires auth token)
```

Watchdog escalations come via Discord:

- **`quarantined`** — task hit retry cap. Inspect logs, decide.
- **`budget.exhausted`** — daily $ cap hit. Pause until tomorrow OR `skynet unlock budget`.
- **`audit-reject-burst`** — agent tried to write outside its workspace 4× in 60s. Killed, quarantined.

---

## 18. v0 Milestones

```
v0.0a  spec series:    architecture, compatibility-spec, schema, pipeline.toml, env  (DONE)
v0.0b  rpi-home-monitor compliance  (deferred — not on critical path)

v0.1   FULL OPERATOR-USABLE SYSTEM
       - orchestrator + watchdog as systemd services
       - all 7 agent roles with default prompts
       - provider abstraction with built-in + custom + claude_cli + codex_cli
       - fallback chains across providers
       - 4 failure modes deterministically handled
       - sqlite state with checkpoint resume
       - path-policy auto-merge with most-restrictive resolution
       - Discord notifier (batched)
       - skynet CLI (init, doctor, status, pause, resume, kick, replay, quarantine, unlock)
       - Linux primary, Windows secondary

v1.0+  hardware integration (staged: read-only → active scripts)
       Yocto release engineering
       multi-target parallel operation
       Telegram + email notifiers
```

v0.1 is the first version where Skynet Agentry actually works end-to-end. v0.0a-v0.0b are scaffolding.

---

## 19. Deferred v1+ Capabilities

### Hardware integration (staged)

```
v0     no real hardware — Tester runs configured commands only
v1     read-only hardware observation:
         SSH to test rig, run journalctl, capture serial buffer,
         report state — no flashing, no power cycles, no writes
v1.x   active hardware tests, allowlisted scripts only:
         flash an SWU bundle the framework signed itself,
         run a smoke script declared in .skynet/config.yml,
         smart-plug power cycle on hang (per-rig allowlist)
v2+    multi-rig orchestration, hardware load balancing
```

### Release engineering (v1+)

Yocto-based release builds, SWU signing, GitHub Release publishing. Release Engineer agent role is reserved in the lifecycle now; no implementation in v0.

### Multi-target operation (v2+)

v0.1 supports multiple targets in serial. Multi-target *parallelism* (concurrent tasks across targets) is v2+.

### Self-improvement of the framework

Skynet Agentry operating on its own source code remains an Operator-only workflow. Auto-merge to `main` of the framework repo is `policy: none` permanently.

### Public release

Public PyPI publication and a non-`skynet` brand name are deferred until the framework has shipped real features against rpi-home-monitor for at least one quarter. Until then, `skynet-agentry` is private and `git+ssh` installable.

---

## 20. Glossary

- **Operator** — the human running Skynet Agentry. Responsible for emergency overrides, policy changes, and onboarding. Not involved in routine task flow.
- **Target** — any repository that Skynet Agentry operates on. Must conform to the Compatibility Spec.
- **Task** — a unit of work, identified by a `SKY-<year>-<n>` ID, moving through the lifecycle in §11.
- **Quarantine** — terminal state for tasks the watchdog suspects are unsafe to continue. Locked until Operator review.
- **Path policy** — a per-glob rule (`hard`/`soft`/`none`) determining auto-merge behavior.
- **Most-restrictive resolution** — combining path policies across a multi-file PR by taking the strictest.
- **Compatibility Spec** — the contract a target repo must satisfy. Defined in `COMPATIBILITY-SPEC.md`.
- **Version handshake** — `skynet doctor`'s check that the installed framework version satisfies the target's declared `skynet_version` range.
- **Provider** — a configured way to call a model: built-in (`anthropic`, `openai`, `codex_cli`) or custom (`openai_compatible`, `anthropic_compatible`, `claude_cli`, `codex_cli`-as-custom).
- **Fallback chain** — ordered list of `(provider, model)` pairs tried in sequence when the primary fails. Defined per role in `.skynet/config.yml`.
- **Subscription routing** — routing a model call through `claude` or `codex` CLI binaries (using OAuth credentials) rather than API keys, to consume subscription quota instead of paying per-token.
- **Two-tier supervision** — the watchdog supervises the orchestrator and agents; the init system (systemd or NSSM) supervises the watchdog. Neither is a single point of failure.

---

*End of architecture.md (v0.0a-1, revised).*
