# Skynet Agentry — Architecture

Status: **v0.0a-1 (draft, pre-implementation)**

This document describes the architecture of Skynet Agentry, an autonomous multi-agent product organization that operates the full software development lifecycle for any compliant target repository.

It is the first artifact in the v0.0a series:

```
v0.0a-1   docs/architecture.md             ← this document
v0.0a-2   COMPATIBILITY-SPEC.md
v0.0a-3   schemas/skynet-config.schema.json
v0.0a-4   pipeline.example.toml
v0.0a-5   .env.example
```

No code lands until the spec series is reviewed and locked.

---

## 1. Purpose

Skynet Agentry is a **headless product team in a box**. It runs continuously on a single Windows host and ships features to a target repository through a roster of specialized agents:

- a **Researcher** that finds new feature ideas
- an **Architect** that turns ideas into designs
- an **Implementer** that writes code on a branch
- a **Tester** that runs the configured test matrix
- a **PR Author** that opens pull requests
- a **PR Reviewer** that performs an independent review
- a **Release Engineer** that builds and ships releases
- a **Watchdog** that supervises everything else

It is **not**:

- a pair-programming assistant (use Claude Code, Cursor, or Copilot for that)
- a one-shot code generator (use GPT Engineer or smol-developer for that)
- a multi-agent conversation framework (use AutoGen, LangGraph, or CrewAI for that)
- a CI/CD system (it complements one; it does not replace one)

It is a tool you install once on a machine and point at a target repository. From there, it operates autonomously by default, with the **Operator** (the human running it) reserved for emergency overrides, policy changes, and onboarding new targets.

---

## 2. Two-Repo Model

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

The framework is **generic**: it knows nothing about any particular target. A target declares conformance to the **Skynet Compatibility Spec** and provides a `.skynet/config.yml` describing its build commands, test commands, sensitive paths, hardware (if any), and agent model preferences.

Target repositories contain only metadata and placeholder directories. They never copy framework source.

The **canonical reference target** is `vinu-dev/rpi-home-monitor`. Its existing `docs/ai/` operating system is the model that the Skynet Compatibility Spec generalizes from.

---

## 3. Distribution & Versioning

Skynet Agentry is distributed as a Python CLI tool. The intended install path is:

```
uv tool install skynet-agentry
# or
pipx install skynet-agentry
```

This matches the pattern of `gh`, `ruff`, and `pre-commit`: install once on a machine, use across many targets. Target repositories never bundle, vendor, or submodule the framework.

While the framework is private, `git+ssh://`-based installation works:

```
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
```

### Version handshake

The framework follows semantic versioning. A target declares the framework version range it expects:

```yaml
# .skynet/config.yml
skynet_version: ">=0.4,<1.0"
```

`skynet doctor --target <repo>` validates the declaration against the installed framework version. The orchestrator refuses to dispatch tasks to a target with an incompatible version. This is the same discipline as `cmake_minimum_required(VERSION 3.20)` in C++ projects pulling in GoogleTest via `FetchContent`.

A breaking change to the Compatibility Spec increments the major version. Additions are minor. Bug fixes are patch.

---

## 4. System Context

```
                          ┌────────────────────────┐
                          │ Anthropic API (Claude) │  ← implementer, architect, researcher
                          └────────────┬───────────┘
                                       │
                          ┌────────────▼───────────┐
                          │ OpenAI API (GPT-5)     │  ← reviewer (different vendor on purpose)
                          └────────────┬───────────┘
                                       │
   ┌──────────┐  ┌──────────────────────────────────────┐  ┌─────────────────┐
   │ Operator │─→│                                      │─→│ GitHub          │
   │ (rare    │  │       Windows 11 host                │  │ - target repo   │
   │  inputs, │  │       (always on, NSSM services)     │  │ - issues / PRs  │
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

External dependencies:

- **Anthropic API** — primary model provider for Researcher, Architect, Implementer.
- **OpenAI API** — independent model provider for Reviewer. Multi-vendor by design (see §10).
- **GitHub** — target repo hosting. Used via `gh` CLI; no GitHub Actions or Projects.
- **GCP VM** *(optional)* — Yocto sstate-cache mirror and build offload for embedded targets.
- **Hardware test rig** *(optional, v1+)* — Raspberry Pi devices reachable over the network and serial.
- **Discord webhook** — single observability channel in v0.

The Operator is involved at three points only:

1. Onboarding: running `skynet init` against a new target.
2. Emergency: pausing or unlocking the system after a policy block.
3. Drift correction: opening framework-improvement issues manually.

Routine operation requires no Operator input.

---

## 5. Windows Host Runtime

```
┌─ Windows 11 Host ──────────────────────────────────────────────────────┐
│                                                                        │
│  ┌─ NSSM Services (autostart, two-tier supervision) ─────────────────┐│
│  │                                                                    ││
│  │   ┌────────────────────┐        ┌──────────────────────┐          ││
│  │   │ skynet-watchdog    │──sup──→│ skynet-orchestrator  │          ││
│  │   │  heartbeat poll    │        │  scheduler (cron)    │          ││
│  │   │  restart actions   │        │  task dispatcher     │          ││
│  │   │  escalation        │        │  state I/O           │          ││
│  │   └────────────────────┘        └──────────┬───────────┘          ││
│  └──────────────────────────────────────────────┼────────────────────┘│
│                                                 │ spawn                │
│                                                 ▼                      │
│  ┌─ Agent worker pool (one subprocess per active task) ──────────────┐│
│  │                                                                    ││
│  │  research  architect  implementer  tester  pr-author  reviewer    ││
│  │     │          │           │          │         │          │      ││
│  │     └──────────┴───────────┴──────────┴─────────┴──────────┘      ││
│  │                            │                                       ││
│  │  each: cwd = workspace/<task-id>/<target-clone>/                  ││
│  │        + path-allowlist tool wrapper                              ││
│  └────────────────────────────────────────────────────────────────────┘│
│                                                                        │
│  ┌─ State (on disk) ──────────────────────────────────────────────────┐│
│  │   state/skynet.db          tasks, events, heartbeats, budget       ││
│  │   state/heartbeats/*.json  live (30s updates from each agent)      ││
│  │   state/logs/<task-id>/    per-task logs                           ││
│  │   workspace/<task-id>/     per-task git clones (gitignored)        ││
│  │   ~/.skynet/prompts/       versioned, read-only to agents          ││
│  │   ~/.skynet/policies/      versioned, read-only to agents          ││
│  └────────────────────────────────────────────────────────────────────┘│
│                                                                        │
│  ┌─ WSL2 toolchain (called via wrappers) ─────────────────────────────┐│
│  │   pytest   ruff   gh   ssh   bitbake   shellcheck                  ││
│  └────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────┘
```

Two long-running Windows Services, registered via **NSSM** (Non-Sucking Service Manager):

- `skynet-orchestrator` — owns the schedule, the task DB, and dispatches agent subprocesses.
- `skynet-watchdog` — supervises the orchestrator and all agent workers. Two-tier supervision means the watchdog itself runs under NSSM, so it cannot be a single point of failure.

Agents are **short-lived subprocesses**, one per active task. They have no shared memory with the orchestrator; communication is by sqlite state and heartbeat files.

WSL2 hosts the Linux toolchain (`pytest`, `bitbake`, `gh`, `ssh`). Agents invoke it via wrappers that pre-validate command and path safety.

---

## 6. Task Lifecycle

Every task moves through a fixed state machine. State transitions are persisted to sqlite atomically; checkpoints make every state resumable after a process crash.

```
                       ┌──────────────────┐
                       │  research-draft  │
                       └────────┬─────────┘
                                │ Operator or auto-promote
                                ▼
                       ┌──────────────────┐
                       │     designed     │
                       └────────┬─────────┘
                                │ Architect writes design doc
                                ▼
                       ┌──────────────────┐
                       │   agent-ready    │
                       └────────┬─────────┘
                                │ Orchestrator dispatches to Implementer
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
        Reviewer:        │        │    │
        approves         │        │    │ Reviewer requests changes
                         ▼        ▼    ▼
              ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │   approved   │  │ tests-failed │  │review-failed │
              └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                     │                 │                 │
                     │ Path policy     │ Implementer     │ Implementer
                     │ resolves        │ retries (max 3) │ retries (max 3)
                     ▼                 │                 │
              ┌──────────────┐         │                 │
              │    merged    │         └─→ in-progress ←─┘
              └──────────────┘                  │
                                                │ if cap exceeded
                                                ▼
                                       ┌──────────────────┐
                                       │   quarantined    │
                                       └──────────────────┘
                                            (Operator)
```

### States

- **research-draft** — Researcher has produced a candidate idea as a GitHub issue with the `skynet/research-draft` label. Awaiting promotion.
- **designed** — Operator (or an auto-promote rule) advances the issue. Architect writes a design document to `docs/ai/designs/` in the target repo.
- **agent-ready** — Design is committed and labeled. The orchestrator can pick it up.
- **in-progress** — Implementer has a branch and is producing code + unit tests.
- **pr-open** — PR is open, all configured tests have run.
- **approved** — Reviewer has approved. Path policy is evaluated next.
- **tests-failed** — One of the configured tests failed. Loops back to in-progress, with a retry counter.
- **review-failed** — Reviewer requested changes. Loops back to in-progress.
- **merged** — Auto-merge has completed (after path-policy resolution and any required hold window).
- **quarantined** — Watchdog detected an anomaly (repeated failure, stuck loop, budget breach, suspicious agent behavior). Locked until the Operator inspects.

The retry counter for `tests-failed` and `review-failed` is bounded (default: 3 each, configurable). Exceeding the cap escalates the task to `quarantined`.

---

## 7. Trust Boundaries

Skynet Agentry enforces **four** trust boundaries between the framework runtime and agent workers:

```
┌─ TRUSTED ZONE: framework runtime ───────────────────────────────────────┐
│                                                                         │
│   ┌─ orchestrator ──┐    ┌─ watchdog ──┐                               │
│   │  full FS read   │    │  full read  │                               │
│   │  state writes   │    │             │                               │
│   └─────────────────┘    └─────────────┘                               │
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
│   ─ allowed: per-agent shell allowlist (e.g. tester gets pytest, ruff) │
│   ─ rejected: anything outside the allowlist                            │
│                                                                         │
│   Boundary 3 — Network                                                  │
│   ─ allowed: configured LLM provider, github.com API for the target    │
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

Enforcement happens at three layers, regardless of boundary:

1. **Subprocess env** — the orchestrator exports `TARGET_REPO`, `TASK_ID`, `ALLOWED_PATHS`, `DAILY_BUDGET_REMAINING` once at spawn.
2. **Tool wrapper** — every Read, Write, Bash, and HTTP call is gated by an allowlist before reaching the LLM tool layer. Rejected calls do not produce silent failures; they raise structured errors that the agent must handle.
3. **Audit log + watchdog** — every rejected call is logged. More than 3 rejected calls within 60 seconds triggers a Discord notification and moves the task to `quarantined`.

The budget boundary deserves special note: cost is a safety property, not just an operational concern. An agent that cannot fail-stop on cost will run away. The watchdog enforces cost as strictly as it enforces process liveness.

---

## 8. Agent Roles

Each agent is a stateless function from `(task-id, state, prompt)` to `(new-state, side-effects)`. State lives in sqlite; prompts live in `~/.skynet/prompts/<role>.md`; side-effects are git ops and notification events.

| Role | Trigger | Reads | Writes | Default model |
|------|---------|-------|--------|---------------|
| **Researcher** | hourly cron | target's `docs/ai/`, web search, competitor sites | GitHub issue with `skynet/research-draft` | Claude Sonnet 4.6 |
| **Architect** | issue promoted to `designed` | issue body, target's `docs/ai/`, ADRs | `docs/ai/designs/<task-id>-*.md` | Claude Opus 4.7 |
| **Implementer** | issue at `agent-ready` | design doc, target codebase | branch `skynet/<task-id>/<slug>`, unit tests | Claude Sonnet 4.6 |
| **Tester** | implementation complete | branch, target's test config | test results in sqlite, logs | Claude Sonnet 4.6 (light; mostly tool execution) |
| **PR Author** | tests green | branch, design doc | GitHub PR | Claude Sonnet 4.6 |
| **PR Reviewer** | PR open | PR diff, design doc, target's `docs/ai/` | review comment, approval | **GPT-5 (different vendor)** |
| **Release Engineer** | merged + milestone | merged commits, release notes template | Yocto build artifacts, GitHub Release | Claude Sonnet 4.6 *(v1+)* |
| **Watchdog** | continuous | heartbeat files, sqlite | restart actions, Discord pings | deterministic (no LLM) |

The **Reviewer is required to be from a different vendor** than the Implementer. This is enforced in the config schema: a config that places implementer and reviewer on the same vendor is rejected by `skynet doctor`. The reason is structural — a Claude reviewer reviewing Claude code shares the same training distribution and biases. Real review needs a real second opinion.

The **Watchdog is deterministic**, not LLM-driven. It uses fixed rules to detect liveness, restart agents, escalate. An LLM watchdog would be a single point of stochastic failure.

---

## 9. State Model

All state lives in `state/skynet.db` (sqlite). The schema is intentionally small.

```sql
-- One row per task, the unit of work
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,           -- e.g. SKY-2026-000123
  target_repo     TEXT NOT NULL,              -- target git remote URL
  target_branch   TEXT,                       -- branch the agent created
  kind            TEXT NOT NULL,              -- research | design | implement | test | review | release
  state           TEXT NOT NULL,              -- see lifecycle in §6
  retries         INTEGER NOT NULL DEFAULT 0,
  parent_id       TEXT REFERENCES tasks(id),
  checkpoint_json TEXT,                       -- agent-specific resumption data
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

-- Append-only event log
CREATE TABLE events (
  ts        INTEGER NOT NULL,
  task_id   TEXT NOT NULL REFERENCES tasks(id),
  agent     TEXT,
  type      TEXT NOT NULL,                    -- state-change, error, audit-reject, etc.
  payload   TEXT                              -- JSON
);

-- Live heartbeat from each running agent worker
CREATE TABLE heartbeats (
  agent       TEXT PRIMARY KEY,               -- agent worker process identity
  task_id     TEXT,
  last_seen   INTEGER NOT NULL,
  iteration   INTEGER NOT NULL,
  tokens_used INTEGER NOT NULL,
  status      TEXT NOT NULL                   -- alive | rate-limited | context-full | crashed
);

-- Daily cost ledger (budget boundary)
CREATE TABLE budget (
  date        TEXT NOT NULL,                  -- YYYY-MM-DD
  agent       TEXT NOT NULL,
  tokens_in   INTEGER NOT NULL DEFAULT 0,
  tokens_out  INTEGER NOT NULL DEFAULT 0,
  dollars     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (date, agent)
);

-- Atomic task ID allocator (year-prefixed monotonic)
CREATE TABLE task_counters (
  year   INTEGER PRIMARY KEY,
  n      INTEGER NOT NULL DEFAULT 0
);
```

### Crash recovery

On startup, the orchestrator:

1. Reads all tasks not in a terminal state (`merged`, `quarantined`).
2. For each, reads `checkpoint_json` and resumes the agent from that checkpoint.
3. Re-establishes heartbeat tracking; tasks with stale heartbeats are restarted by the watchdog under its normal recovery rules.

There is **no in-memory state** that survives a process restart. Every decision is persisted before it is acted upon.

### Task IDs

Format: `SKY-<year>-<6-digit-monotonic>` — e.g. `SKY-2026-000123`. Allocated atomically via the `task_counters` table.

The same ID flows through:

- issue title prefix: `[SKY-2026-000123] ...`
- branch name: `skynet/SKY-2026-000123/<slug>`
- PR title prefix: `[SKY-2026-000123] ...`
- design doc filename: `docs/ai/designs/SKY-2026-000123-<slug>.md`
- log directory: `state/logs/SKY-2026-000123/`
- workspace clone: `workspace/SKY-2026-000123/<target>/`

Trace-back from any artifact to its full task history is therefore one grep away.

---

## 10. Policy Model

Auto-merge is governed by a **path-policy table** declared in the target's `.skynet/config.yml`.

### Policies

- **`hard`** — merge immediately when all checks pass (CI green, Reviewer approves).
- **`soft`** — merge after a hold window (default 24h) unless an Operator vetoes, all checks pass, and a Discord notification was emitted at hold start.
- **`none`** — never auto-merge. Operator must intervene.

### Configuration shape

```yaml
auto_merge:
  default_policy: "soft"
  hold_hours: 24
  path_policies:
    "docs/**":               "hard"
    "tests/**":              "hard"
    "app/*/auth/**":         "none"
    "**/ota/**":             "none"
    "**/pairing*":           "none"
    "swupdate/**":           "none"
    "hardware/**":           "none"
    "prompts/**":            "none"   # framework-target meta-rule
```

### Resolution algorithm

For each PR, the orchestrator computes the changed-paths set with `git diff --name-only` and resolves a single effective policy:

1. For every changed file, find the matching path policy (longest-glob wins).
2. If no path policy matches, use `default_policy`.
3. The **most-restrictive policy wins**: if any file resolves to `none`, the PR is `none`. If any to `soft` (and none to `none`), the PR is `soft`. Otherwise `hard`.

This is enforced before the Reviewer is even invoked on PRs touching `none` paths — saves a Reviewer call and protects against a confused review.

### "docs/tests-only" verification

A PR claiming to be docs-only must pass an **allowlist check**: every changed path matches one of the `hard` glob rules. If any path falls outside, the PR drops to `default_policy`. This prevents agents from sneaking product-code changes into a "docs PR."

### Framework PRs

Any PR opened against the Skynet Agentry framework repo itself (as opposed to a target) is treated as `policy: none` unconditionally, regardless of the path-policy table. Framework changes always go through Operator review until v1.

---

## 11. Notification Model

Single channel in v0: **Discord webhook**, batched.

### Why batched

A chatty agent can hit Discord's per-webhook rate limit (30 messages per minute). Throttled silence looks identical to "everything is fine" — a critical observability failure. The notifier therefore:

- accumulates events in a queue
- flushes every 60 seconds
- emits at most one message per flush, formatted as a digest
- forces an immediate flush only for `quarantined`, `budget-cap-hit`, and `audit-reject-burst` events

### Event taxonomy

```
task-lifecycle:
  task.created
  task.state-changed
  task.merged
  task.quarantined

agent-events:
  agent.started
  agent.heartbeat-stale
  agent.restarted
  agent.crashed

policy-events:
  policy.hold-started        ← soft route, 24h timer begins
  policy.hold-completed      ← merged after hold
  policy.veto-received       ← Operator stopped a hold
  policy.sensitive-blocked   ← none policy hit

budget-events:
  budget.warning             ← 75% of daily cap
  budget.exhausted           ← 100%, all agents pause

audit-events:
  audit.reject               ← single rejected tool call
  audit.reject-burst         ← >3 in 60s, agent quarantined

operator-events:
  operator.unlock            ← someone called `skynet unlock`
  operator.pause / resume
```

Future versions add Telegram and email notifiers behind a `Notifier` interface. The interface is defined now even though only Discord is implemented in v0.

---

## 12. v0 Milestones

```
v0.0a-1   docs/architecture.md             ← this document
v0.0a-2   COMPATIBILITY-SPEC.md            ← target repo contract
v0.0a-3   schemas/skynet-config.schema.json
v0.0a-4   pipeline.example.toml            ← per-PC config template
v0.0a-5   .env.example

v0.0b     rpi-home-monitor compliance scaffold (PR to target)
                    add .skynet/config.yml + docs/ai/plans/ + docs/ai/designs/
                    add docs/ai/risk-register.md
                    declare skynet_version

v0.1      runtime spine
                    orchestrator daemon (Python + APScheduler + sqlite)
                    watchdog skeleton with deterministic recovery
                    Discord notifier (batched)
                    NSSM service installers

v0.2      onboarding tooling
                    skynet init / skynet doctor
                    JSON Schema validator integration
                    rpi-home-monitor passes `skynet doctor`

v0.3      first agent round-trip
                    Researcher → Architect → Implementer
                    against a docs-only target task
                    no Tester or Reviewer yet — `skynet pr` opens by hand for inspection

v0.4      full software loop
                    Tester (configured commands only, no hardware)
                    PR Reviewer (OpenAI / GPT-5)
                    PR Author with auto-merge under path policies
                    full skynet CLI surface (status, pause, resume, kick, replay, quarantine, unlock)
```

Each milestone produces a tagged release (`v0.1.0`, `v0.2.0`, …). Tags drive `uv tool upgrade` cycles on the host.

---

## 13. Deferred v1+ Capabilities

The following are explicitly out of scope for v0. They are listed here so the v0 design does not paint them into a corner.

### Hardware integration (staged)

```
v0    no real hardware — Tester runs configured commands only
v1    read-only hardware observation:
        SSH to test rig, run `journalctl`, capture serial buffer,
        report state — no flashing, no power cycles, no writes
v1.x  active hardware tests, allowlisted scripts only:
        flash an SWU bundle the framework signed itself,
        run a smoke script declared in `.skynet/config.yml`,
        smart-plug power cycle on hang (per-rig allowlist)
v2+   multi-rig orchestration, hardware load balancing
```

The staging means even when hardware lands, it lands as **observation first**. This is the same discipline as "log first, alert second, act third" in production-systems engineering.

### Release engineering

Yocto-based release builds (`./scripts/build.sh server-prod`, SWU signing, GitHub Release publishing) are deferred to v1. The Release Engineer agent role is defined now so the lifecycle includes it, but no implementation lands in v0.

### Multi-target operation

v0 supports one active target at a time. Multi-target parallelism (one orchestrator, several targets) is v2+. The state model is built to support it (`tasks.target_repo` is per-row), but the scheduler logic is single-target until the path is exercised.

### Self-improvement of the framework

Even when v1 introduces hardware actions, the framework operating on its own source code (Skynet Agentry as a target of itself) remains an Operator-only workflow. Auto-merge to `main` of the framework repo is `policy: none` permanently.

### Public release

Public PyPI publication and a non-`skynet` brand name are deferred until the framework has shipped real features against rpi-home-monitor for at least one quarter. Until then, `skynet-agentry` is private and `git+ssh` installable.

---

## Glossary

- **Operator** — the human running Skynet Agentry. Responsible for emergency overrides, policy changes, and onboarding. Not involved in routine task flow.
- **Target** — any repository that Skynet Agentry operates on. Must conform to the Skynet Compatibility Spec.
- **Task** — a unit of work, identified by a `SKY-<year>-<n>` ID, moving through the lifecycle in §6.
- **Quarantine** — terminal state for tasks the watchdog suspects are unsafe to continue. Locked until Operator review.
- **Path policy** — a per-glob rule (`hard`/`soft`/`none`) that determines auto-merge behavior for PRs touching matching paths.
- **Most-restrictive resolution** — the rule that combines path policies across a multi-file PR by taking the strictest.
- **Compatibility Spec** — the contract a target repo must satisfy to be operated on by Skynet Agentry. Defined in `COMPATIBILITY-SPEC.md`.
- **Version handshake** — the check `skynet doctor` performs to ensure the installed framework version satisfies the target's declared `skynet_version` range.

---

*End of architecture.md (v0.0a-1).*
