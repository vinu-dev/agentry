# Skynet Agentry — Compatibility Specification

Status: **v0.0a-2 (revised, pre-implementation)**

This document defines the contract that any target repository must satisfy to be operated on by Skynet Agentry. It is the source of truth for `skynet doctor`. The companion JSON Schema (artifact v0.0a-3) provides machine-checkable validation of the same contract.

The architecture this contract supports is described in [`docs/architecture.md`](docs/architecture.md). The Operator's practical guide is in [`docs/how-to-use.md`](docs/how-to-use.md).

This is a revised version of v0.0a-2. Changes from the previous draft:

- `providers:` block added — Operator may declare custom providers (OpenAI-compatible, Anthropic-compatible, Claude CLI subscription routing, Codex CLI subscription routing) referenced by name throughout the config
- `defaults:` block added — common settings inherited by every role unless overridden, with `primary`, `fallbacks`, and per-role failure-handling defaults
- Each role gains `primary`/`fallbacks` (replacing the flat `model`/`provider` pair), enabling fallback chains
- Per-role `on_rate_limit` / `on_capability_exceeded` / `on_stall` overrides
- Per-role `prompt_extras`, `tool_allowlist`, `max_tokens_per_call`, `timeout_seconds`, `max_retries`
- Provider types: `openai_compatible`, `anthropic_compatible`, `claude_cli`, `codex_cli`
- Subscription routing semantics documented (§9 of the schema reference)

---

## 1. Purpose

Skynet Agentry is a generic framework. It can operate on any repository that conforms to this Compatibility Specification.

Conformance is verified by `skynet doctor` before any agent dispatches a task. A non-conforming target is rejected.

Conformance is per-repository, per-version. A target conforming to spec v0.4 may not conform to spec v0.5; that is expected and managed via the version handshake (§3).

---

## 2. Compatibility Levels

The spec defines three levels. Higher levels enable more agent capabilities but require more target structure.

| Level | What it enables | Required structure |
|-------|----------------|-------------------|
| **minimal** | Researcher, Architect, Implementer, basic Tester | core files only |
| **standard** | + risk-aware design, ADR review, traceability for sensitive paths | minimal + risk register + ADR support |
| **full** | + traceability matrix, hardware integration (v1+), release engineering (v1+) | standard + traceability + hardware/release config |

The level is **detected** by `skynet doctor` from the presence of optional structures listed in §5.

---

## 3. Version Handshake

`.skynet/config.yml` MUST declare:

```yaml
skynet_version: ">=0.4,<1.0"
```

Format: [PEP 440 version specifiers](https://peps.python.org/pep-0440/).

`skynet doctor` resolves the installed framework version against this range. Mismatch → exit code 2. Orchestrator refuses to dispatch.

---

## 4. Required Files (minimal level)

```
<target-root>/
├── .skynet/
│   └── config.yml             ← see §6
├── docs/
│   └── ai/
│       ├── mission-and-goals.md
│       ├── repo-map.md
│       ├── working-agreement.md
│       ├── plans/
│       │   └── .gitkeep
│       └── designs/
│           └── .gitkeep
└── (target's own source / tests / build files)
```

`docs/ai/*.md` files MUST exist but MAY be brief; `skynet init` writes working defaults.

The `main` branch MUST have GitHub branch protection enabled. `skynet doctor` reports it as a WARNING because it cannot be verified externally without `admin:repo` scope.

---

## 5. Optional Files (standard / full levels)

```
<target-root>/
├── docs/
│   ├── ai/
│   │   ├── engineering-standards.md   [recommended]
│   │   ├── execution-rules.md         [recommended]
│   │   └── risk-register.md           [REQUIRED for standard level]
│   ├── history/
│   │   ├── specs/                     [for standard+]
│   │   └── adr/                       [for standard+]
│   ├── exec-plans/                    [for multi-session work]
│   └── traceability/                  [REQUIRED for full level]
└── .skynet/
    ├── hooks/                         [optional, see §12]
    └── prompt-extras/                 [per-target prompt context]
```

`docs/ai/risk-register.md` is the persistent map of danger zones the agents read on every task. The Architect reads it before producing a design; the path-policy table (§11) typically aligns with it.

---

## 6. `.skynet/config.yml` — Schema

REQUIRED fields are marked. Unspecified optional fields take documented defaults.

### 6.1 Top-level structure

```yaml
# Version handshake (REQUIRED)
skynet_version: ">=0.4,<1.0"

# Project metadata (REQUIRED)
project:
  name: "rpi-home-monitor"
  languages: ["python", "yocto"]
  description: ""

# Custom provider declarations (OPTIONAL)
providers:
  <provider-name>:
    type: <openai_compatible | anthropic_compatible | claude_cli | codex_cli>
    base_url: "..."             # for openai_compatible / anthropic_compatible
    api_key_env: "..."          # env var name (in .env) holding the key; "" for none
    binary_path: "..."          # for claude_cli / codex_cli; defaults to bare command name

# Defaults inherited by every role (RECOMMENDED)
defaults:
  primary: { provider: <name>, model: <id> }
  fallbacks: [{ provider: <name>, model: <id> }, ...]
  prompt_extras: ""
  tool_allowlist: ["read", "write", "bash", "gh"]
  max_tokens_per_call: 8000
  timeout_seconds: 300
  max_retries: 3
  on_rate_limit: backoff_then_fallback
  on_capability_exceeded: escalate
  on_stall: kill_retry_quarantine

# Agent roster (REQUIRED — at minimum researcher, architect, implementer, tester, pr_author, reviewer)
agents:
  researcher: { ... }
  architect: { ... }
  implementer: { ... }
  tester: { ... }
  pr_author: { ... }
  reviewer: { ... }
  release: { ... }              # optional, v1+

# Build commands (OPTIONAL — required only if release.enabled is true)
build:
  default: "..."
  prod: "..."

# Test matrix (REQUIRED — at minimum test.unit)
test:
  unit: "..."
  integration: "..."
  contract: "..."
  e2e: "..."
  lint: "..."
  format: "..."

# Hardware (OPTIONAL, v1+; v0 must keep enabled: false)
hardware:
  enabled: false
  rigs: []

# Release (OPTIONAL, v1+; v0 must keep strategy: none)
release:
  strategy: "none"
  trigger: "milestone"
  artifact_glob: ""
  signing_key_env: ""

# Auto-merge (REQUIRED)
auto_merge:
  default_policy: "soft"
  hold_hours: 24
  path_policies:
    "<glob>": <hard | soft | none>

# Budget boundary (REQUIRED)
budget:
  daily_dollars: 50
  per_task_tokens: 200000
  retry_cap: 3
  concurrent_tasks: 2

# Notification (REQUIRED)
notification:
  channel: "discord"
  webhook_env: "DISCORD_WEBHOOK_URL"

# Traceability (OPTIONAL; REQUIRED for full level)
traceability:
  enabled: false
  check_command: "..."
  required_for_paths: [...]
```

### 6.2 The `providers` block

Built-in providers (no declaration needed):

| Name | Type | Auth |
|------|------|------|
| `anthropic` | Anthropic API | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI API | `OPENAI_API_KEY` |
| `codex_cli` | Codex CLI subprocess (subscription routing) | OAuth via `codex login` |

Custom providers — declared and referenced by name:

```yaml
providers:
  my_llama:
    type: openai_compatible
    base_url: http://localhost:11434/v1
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

  my_codex:
    type: codex_cli
    binary_path: codex                       # uses `codex login` OAuth
```

**`claude_cli` and `codex_cli` types route through subscription credentials**, not API keys. Skynet invokes the CLI as a subprocess; auth is whatever `claude login` or `codex login` set up. Subscription rate limits apply.

### 6.3 The `defaults` block

Defaults are inherited by every role unless that role overrides them.

```yaml
defaults:
  primary:    { provider: claude_sub, model: claude-sonnet-4-6 }
  fallbacks: [{ provider: anthropic,  model: claude-sonnet-4-6 }]
  prompt_extras: ""
  tool_allowlist: ["read", "write", "bash", "gh"]
  max_tokens_per_call: 8000
  timeout_seconds: 300
  max_retries: 3
  on_rate_limit: backoff_then_fallback
  on_capability_exceeded: escalate
  on_stall: kill_retry_quarantine
```

Without a `defaults` block, every role must declare `primary` explicitly. With it, roles can be empty `{}` if defaults suit them.

### 6.4 The `agents` block — per-role schema

Every role takes the same shape. Required and optional fields:

```yaml
<role>:
  enabled: true                            # default: true
  primary:                                 # REQUIRED unless defaults provide it
    provider: <provider-name>              # built-in or declared in providers:
    model: <model-id>
  fallbacks:                               # OPTIONAL (default from defaults block)
    - { provider: <name>, model: <id> }
    - { provider: <name>, model: <id> }
  prompt_extras: <path>                    # OPTIONAL — appended to framework prompt
  tool_allowlist: [...]                    # OPTIONAL — overrides defaults
  max_tokens_per_call: <int>               # OPTIONAL
  timeout_seconds: <int>                   # OPTIONAL
  max_retries: <int>                       # OPTIONAL

  # Per-role failure-handling overrides (OPTIONAL)
  on_rate_limit: <backoff | fallback | backoff_then_fallback | quarantine>
  on_capability_exceeded: <escalate | fallback | quarantine>
  on_stall: <kill_retry_quarantine | quarantine>

  # Role-specific extras
  schedule: "0 * * * *"                    # researcher only — cron expression
  max_per_day: 5                           # researcher only — issue creation cap
  trigger: <milestone | merge_count:N | cron:...>   # release only
```

### 6.5 Multi-vendor enforcement

`skynet doctor` rejects any config in which `agents.implementer.primary.provider` and `agents.reviewer.primary.provider` resolve to the same vendor. Vendor normalization:

| `provider` value | Vendor |
|------------------|--------|
| `anthropic`, `claude_cli` | `anthropic` |
| `openai`, `codex_cli` | `openai` |
| Custom `openai_compatible` / `anthropic_compatible` / `local` | depends on operator-asserted vendor (declared via `vendor:` field on the provider, default = "operator-asserted") |

For custom providers, declare the underlying vendor explicitly when needed:

```yaml
providers:
  my_llama:
    type: openai_compatible
    base_url: http://localhost:11434/v1
    vendor: local                          # for multi-vendor rule purposes
```

If the implementer's vendor matches the reviewer's, `skynet doctor` exits with `MULTI_VENDOR_VIOLATION` (code 2).

---

## 7. Label Vocabulary

The framework owns the `skynet/` label prefix. Target repos MUST NOT use this prefix for any other purpose.

| Label | Lifecycle state | Created by |
|-------|----------------|-----------|
| `skynet/research-draft` | research-draft | Researcher |
| `skynet/designed` | designed | Operator (or auto-promote rule, v1+) |
| `skynet/agent-ready` | agent-ready | Architect |
| `skynet/in-progress` | in-progress | Implementer |
| `skynet/pr-open` | pr-open | PR Author |
| `skynet/tests-failed` | tests-failed | Tester |
| `skynet/review-failed` | review-failed | Reviewer |
| `skynet/approved` | approved | Reviewer |
| `skynet/merged` | merged | Merge engine |
| `skynet/quarantined` | quarantined | Watchdog |
| `skynet/needs-human` | (parallel state) | Policy engine, for `none`-policy PRs |

`skynet init` creates these labels at onboarding.

---

## 8. Branch Naming

```
skynet/<task-id>/<slug>
```

`<slug>` is lowercase, hyphenated, ≤ 50 chars, derived from the issue title.

Example: `skynet/SKY-2026-000123/add-offline-camera-heartbeat`

The framework MUST NOT push outside the `skynet/` namespace.

---

## 9. Task ID Format

```
SKY-<YYYY>-<NNNNNN>
```

- `<YYYY>` — 4-digit calendar year of task creation (UTC)
- `<NNNNNN>` — 6-digit zero-padded monotonic counter, scoped per year

Example: `SKY-2026-000123`

The counter resets to `000001` on January 1st (UTC). The framework allocates IDs atomically via the `task_counters` sqlite table (see [`docs/architecture.md §13`](docs/architecture.md)).

Task ID prefixes appear in:

| Surface | Example |
|---------|---------|
| Issue title | `[SKY-2026-000123] Add offline camera heartbeat` |
| PR title | `[SKY-2026-000123] Add offline camera heartbeat` |
| Branch | `skynet/SKY-2026-000123/add-offline-camera-heartbeat` |
| Design doc | `docs/ai/designs/SKY-2026-000123-add-offline-camera-heartbeat.md` |
| Plan doc | `docs/ai/plans/SKY-2026-000123-add-offline-camera-heartbeat.md` |
| Commit subject | `Add offline camera heartbeat [SKY-2026-000123]` |
| Log directory | `state/logs/SKY-2026-000123/` |
| Workspace | `workspace/SKY-2026-000123/<target>/` |

---

## 10. Issue & PR Conventions

### Issues created by Researcher

Title: `[SKY-2026-000123] <short title>`

Body MUST start with a YAML front-matter block:

```yaml
---
task-id: SKY-2026-000123
skynet-state: research-draft
skynet-agent: researcher
skynet-resolved-provider: claude_sub
skynet-resolved-model: claude-sonnet-4-6
created-at: 2026-05-02T16:13:00Z
sources: ["https://...", "https://..."]
---
```

Followed by free-form research findings.

### PRs created by PR Author

Title: `[SKY-2026-000123] <action verb> <object>`

Body MUST start with:

```yaml
---
task-id: SKY-2026-000123
skynet-state: pr-open
skynet-agent: pr_author
skynet-resolved-provider: codex_sub
skynet-resolved-model: gpt-5
design-doc: docs/ai/designs/SKY-2026-000123-add-offline-camera-heartbeat.md
test-results:
  unit: pass
  integration: pass
  e2e: pass
  lint: pass
auto-merge-policy: soft
hold-until: 2026-05-03T16:13:00Z
sensitive-paths-touched: []
---
```

Followed by:

1. **Goal** — 1-2 sentence statement
2. **Change summary** — bullet list
3. **Test plan** — what was run, what passed
4. **Path-policy resolution** — which path policies applied to which files

---

## 11. Path-Policy Semantics

Defined in [`docs/architecture.md §14`](docs/architecture.md). Repeated as the contract:

```
1. For every changed file in the PR, find the matching path policy
   (longest-glob wins; if no glob matches, default_policy applies).

2. Combine across files using most-restrictive-wins:
   - any 'none'  → effective policy = 'none'
   - else any 'soft' → effective policy = 'soft'
   - else 'hard'

3. Effective 'none':
   PR enters needs-human label state. No auto-merge ever.

4. Effective 'soft':
   PR holds for `auto_merge.hold_hours`. Discord notification at hold start.
   If no Operator veto via `skynet pause --task <id>` within the window,
   merge proceeds.

5. Effective 'hard':
   Merge immediately on Reviewer approval + green CI.
```

### docs-only / tests-only guard rule

A PR resolves to `hard` only if **every** changed path matches one of the `hard` glob rules. If any path falls outside, effective policy drops to `default_policy` (or stricter if other paths hit stricter rules).

---

## 12. Hooks (Optional Extension Points)

Hooks are OPTIONAL shell scripts in `.skynet/hooks/` that the framework invokes at specific lifecycle points.

| Hook | Invoked when | Stdin | Exit-code semantics |
|------|--------------|-------|---------------------|
| `pre-implementation.sh` | before Implementer starts | `{task, design-doc-path}` JSON | 0 = proceed, ≠0 = abort + quarantine |
| `pre-pr.sh` | before PR Author opens PR | `{task, branch, diff-summary}` JSON | 0 = proceed, ≠0 = abort, retry up to retry_cap |
| `pre-merge.sh` | before auto-merge | `{task, pr-number, effective-policy}` JSON | 0 = proceed, ≠0 = block merge, label `needs-human` |

Hooks run inside the agent's sandbox (same path/command/network/budget restrictions as the calling agent).

Stdin is JSON. Stdout is ignored unless exit code is 0 AND stdout parses as a JSON object with a top-level `modifications` field. Allowlisted modifications:

| Key | Effect |
|-----|--------|
| `modifications.task.title` | replaces the issue/PR title |
| `modifications.task.body_extra` | appends a section to the body |

Other keys are ignored with a WARNING.

---

## 13. Compliance Verification — `skynet doctor`

`skynet doctor --target <path-or-url>` runs every check and produces output of the form:

```
$ skynet doctor --target /path/to/myrepo

Compatibility Spec  : v0.4
Installed framework : 0.4.2
Detected level      : standard

REQUIRED FILES                                       ✓ all present
CONFIG SCHEMA                                        ✓ valid
  ✓ skynet_version (>=0.4,<1.0 satisfies installed 0.4.2)
  ✓ project.name = "rpi-home-monitor"
  ✓ project.languages = ["python", "yocto"]
  ✓ test.unit defined
  ✓ auto_merge.default_policy = "soft"
  ✓ multi-vendor: implementer (anthropic) ≠ reviewer (openai)
  ✓ budget caps configured
  ✓ providers: 2 custom declared (claude_sub, my_llama)

PROVIDERS
  ✓ anthropic       (API ping OK, model 'claude-sonnet-4-6' available)
  ✓ openai          (API ping OK, model 'gpt-5' available)
  ✓ claude_sub      (claude --version → 0.5.1, login OK)
  ✓ my_llama        (HTTP /v1/models OK, model 'llama-3.1-70b' present)

LABELS                                               ✓ 11/11 present in target

OPTIONAL ENHANCEMENTS
  ✓ docs/ai/risk-register.md           → standard level
  ✓ docs/history/adr/                  → standard level
  ✗ docs/traceability/                 → full level not enabled
  ⚠ no .skynet/hooks/ found            → optional, no action needed

WARNINGS
  ⚠ branch protection on `main` cannot be verified externally;
    Operator must enable in GitHub Settings → Branches

RESULT: PASS (level: standard)
```

Exit codes:

| Code | Meaning | Orchestrator behavior |
|------|---------|----------------------|
| `0` | PASS | Operates at detected level |
| `1` | WARN | Operates at degraded level |
| `2` | FAIL | Refuses to dispatch tasks |

The orchestrator runs `skynet doctor` once at startup and on every config change. Exit code 2 disables the affected target.

---

## 14. Spec Evolution

Spec versioning is independent of framework versioning.

| Class | Example | Target action |
|-------|---------|---------------|
| Patch | v0.4.0 → v0.4.1 | none — clarifications only |
| Minor | v0.4 → v0.5 | none — backward-compatible additions |
| Major | v0.x → v1.0 | run `skynet migrate --to <new>` |

Migration:

```
skynet migrate --target <path> --from 0.4 --to 0.5
```

Opens a PR against the target updating `.skynet/config.yml` and any newly required files. Opt-in, never automatic.

---

## 15. Glossary

See [`docs/architecture.md §20`](docs/architecture.md). Same terms apply.

---

*End of COMPATIBILITY-SPEC.md (v0.0a-2, revised).*
