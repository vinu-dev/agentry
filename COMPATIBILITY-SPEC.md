# Skynet Agentry — Compatibility Specification

Status: **v0.0a-2 (draft, pre-implementation)**

This document defines the contract that any target repository must satisfy to be operated on by Skynet Agentry. It is the source of truth for `skynet doctor`. The companion JSON Schema (artifact v0.0a-3) provides machine-checkable validation of the same contract.

The architecture this contract supports is described in [`docs/architecture.md`](docs/architecture.md).

---

## 1. Purpose

Skynet Agentry is a generic framework. It can operate on any repository that conforms to this Compatibility Specification.

Conformance is verified by `skynet doctor` before any agent dispatches a task. A non-conforming target is rejected. There is no partial mode, no "best effort" — either the target conforms to a level (§2) or it does not.

Conformance is per-repository, per-version. A target conforming to spec v0.4 may not conform to spec v0.5. That is expected and managed via the version handshake (§3).

---

## 2. Compatibility Levels

The spec defines three levels. Higher levels enable more agent capabilities but require more target structure.

| Level | What it enables | Required structure |
|-------|----------------|-------------------|
| **minimal** | Researcher, Architect, Implementer, basic Tester | core files only |
| **standard** | + risk-aware design, ADR review, traceability for sensitive paths | minimal + risk register + ADR support |
| **full** | + traceability matrix, hardware integration (v1+), release engineering (v1+) | standard + traceability + hardware/release config |

The level is **detected** by `skynet doctor` from the presence of optional structures listed in §5. There is no explicit `level:` field in `.skynet/config.yml`.

---

## 3. Version Handshake

`.skynet/config.yml` MUST declare the framework version range it expects:

```yaml
skynet_version: ">=0.4,<1.0"
```

Format follows [PEP 440 version specifiers](https://peps.python.org/pep-0440/) for ranges.

`skynet doctor` resolves the installed framework version against this range. Mismatch produces exit code 2 and the orchestrator refuses to dispatch tasks until either the framework or the target is updated.

The framework version is reported by `skynet --version`.

---

## 4. Required Files (minimal level)

A minimal conforming target MUST contain:

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
│       │   └── .gitkeep        ← empty placeholder, Researcher writes here
│       └── designs/
│           └── .gitkeep        ← empty placeholder, Architect writes here
└── (target's own source / tests / build files)
```

The `docs/ai/*.md` files MUST exist but MAY be brief. They define the operating posture for agents working on this target. `skynet init` produces working defaults.

The `main` branch MUST have GitHub branch protection enabled: cannot push directly, requires PR. This is the target owner's responsibility; `skynet doctor` reports it as a WARNING (not ERROR) because it cannot be verified without `admin:repo` scope on the target.

---

## 5. Optional Files (standard / full levels)

```
<target-root>/
├── docs/
│   ├── ai/
│   │   ├── engineering-standards.md   [recommended for any project]
│   │   ├── execution-rules.md         [recommended for any project]
│   │   └── risk-register.md           [REQUIRED for standard level]
│   ├── history/
│   │   ├── specs/                     [feature spec records, standard+]
│   │   └── adr/                       [architecture decisions, standard+]
│   ├── exec-plans/                    [resumable multi-session work]
│   └── traceability/                  [REQUIRED for full level]
├── .skynet/
│   ├── hooks/                         [optional extension points, see §12]
│   │   ├── pre-implementation.sh
│   │   ├── pre-pr.sh
│   │   └── pre-merge.sh
│   └── prompt-extras/                 [per-target prompt context]
│       ├── researcher.md
│       └── architect.md
└── (other target files)
```

`docs/ai/risk-register.md` is the persistent map of danger zones the agents read on every task. It documents what areas of the codebase carry elevated risk (auth, OTA, pairing, hardware, etc.) and why. The Architect agent reads it before producing a design; the path-policy table (§11) typically aligns with it.

---

## 6. `.skynet/config.yml` — Schema

REQUIRED fields are marked. Unspecified optional fields take the defaults documented inline.

```yaml
# Version handshake (REQUIRED)
skynet_version: ">=0.4,<1.0"

# Project metadata (REQUIRED)
project:
  name: "rpi-home-monitor"          # REQUIRED — used in agent prompts and PR bodies
  languages: ["python", "yocto"]    # REQUIRED — informs which prompt-extras apply
  description: ""                   # optional — surfaced in PR bodies

# Build commands (OPTIONAL — required only if release.enabled is true)
build:
  default: "./scripts/build.sh server-dev"
  prod: "./scripts/build.sh server-prod"

# Test matrix (REQUIRED — at least `test.unit`)
test:
  unit: "pytest tests/unit"               # REQUIRED
  integration: "pytest tests/integration" # optional
  contract: "pytest tests/contracts"      # optional
  e2e: "npx playwright test"              # optional
  lint: "ruff check ."                    # optional but recommended
  format: "ruff format --check ."         # optional

# Hardware test rigs (OPTIONAL, deferred to v1+)
hardware:
  enabled: false                    # MUST be false in v0; spec reserved for v1
  rigs: []

# Release configuration (OPTIONAL, deferred to v1+)
release:
  strategy: "none"                  # none | github-release | yocto-swu  (v0: must be 'none')
  artifact_glob: ""
  signing_key_env: ""

# Auto-merge policies (REQUIRED)
auto_merge:
  default_policy: "soft"            # hard | soft | none — default for unmatched paths
  hold_hours: 24                    # for soft policy
  path_policies:                    # longest-glob wins; combined most-restrictive across files
    "docs/**":               "hard"
    "tests/**":              "hard"
    "**/auth/**":            "none"
    "**/ota/**":             "none"
    "**/pairing*":           "none"
    "prompts/**":            "none"

# Agent roster (REQUIRED)
agents:
  researcher:
    enabled: true
    schedule: "0 * * * *"           # cron format
    model: "claude-sonnet-4-6"
    provider: "anthropic"
    max_per_day: 5                  # budget cap on issue creation
  architect:
    enabled: true
    model: "claude-opus-4-7"
    provider: "anthropic"
  implementer:
    enabled: true
    model: "claude-sonnet-4-6"
    provider: "anthropic"
  tester:
    enabled: true
    model: "claude-sonnet-4-6"      # light usage; mostly tool execution
    provider: "anthropic"
  pr_author:
    enabled: true
    model: "claude-sonnet-4-6"
    provider: "anthropic"
  reviewer:
    enabled: true
    model: "gpt-5"
    provider: "openai"              # MUST resolve to a different vendor than implementer
  release:
    enabled: false                  # v0: must be false
    trigger: "milestone"            # milestone | merge_count:N | cron:<spec>

# Budget boundary (REQUIRED)
budget:
  daily_dollars: 50                 # cumulative across all agents
  per_task_tokens: 200000
  retry_cap: 3                      # per state, per task
  concurrent_tasks: 2               # max simultaneously in-progress

# Notification (REQUIRED)
notification:
  channel: "discord"                # discord (v0) | telegram (v1+) | email (v1+)
  webhook_env: "DISCORD_WEBHOOK_URL"

# Traceability (OPTIONAL, REQUIRED for full level)
traceability:
  enabled: false
  check_command: "python tools/traceability/check_traceability.py"
  required_for_paths:
    - "src/**/*.py"
```

### Multi-vendor enforcement (hard rule)

`skynet doctor` rejects any config in which `agents.implementer.provider` and `agents.reviewer.provider` resolve to the same vendor. Vendors are recognized as:

| `provider` value | Vendor |
|------------------|--------|
| `anthropic` | Anthropic |
| `openai` | OpenAI |
| `codex_cli` | OpenAI (via Codex CLI) |
| `local` | Local runtime (ollama, lm-studio) |

Implementer == Reviewer vendor → exit code 2, ERROR `MULTI_VENDOR_VIOLATION`.

The reason is structural, not stylistic: a Claude reviewer reviewing Claude code shares the same training distribution and biases. Independent review requires actual independence.

---

## 7. Label Vocabulary

The framework owns the `skynet/` label prefix. Target repos MUST NOT use this prefix for any other purpose. Other prefixes (e.g. `bug`, `enhancement`) are unrestricted.

| Label | Lifecycle state | Created by |
|-------|----------------|-----------|
| `skynet/research-draft` | research-draft | Researcher |
| `skynet/designed` | designed | Operator (or auto-promote rule) |
| `skynet/agent-ready` | agent-ready | Architect |
| `skynet/in-progress` | in-progress | Implementer |
| `skynet/pr-open` | pr-open | PR Author |
| `skynet/tests-failed` | tests-failed | Tester |
| `skynet/review-failed` | review-failed | Reviewer |
| `skynet/approved` | approved | Reviewer |
| `skynet/merged` | merged | Merge engine |
| `skynet/quarantined` | quarantined | Watchdog |
| `skynet/needs-human` | (parallel state) | Policy engine, for `none`-policy PRs |

`skynet init` creates these labels in the target repo at onboarding. Their existence is verified by `skynet doctor`.

---

## 8. Branch Naming

Branches created by the Implementer follow this pattern exactly:

```
skynet/<task-id>/<slug>
```

Where:
- `<task-id>` matches the format in §9
- `<slug>` is lowercase, hyphenated, ≤ 50 chars, derived from the issue title

Example:
```
skynet/SKY-2026-000123/add-offline-camera-heartbeat
```

The framework MUST NOT push branches outside the `skynet/` namespace. The target's existing branches are untouched.

---

## 9. Task ID Format

```
SKY-<YYYY>-<NNNNNN>
```

Where:
- `<YYYY>` is the 4-digit calendar year of task creation (UTC)
- `<NNNNNN>` is a 6-digit zero-padded monotonic counter, scoped per year

Example: `SKY-2026-000123`

The counter resets to `000001` on January 1st (UTC). The framework allocates IDs atomically via the `task_counters` sqlite table (see `docs/architecture.md §9`).

A given task ID is used as a prefix in:

| Surface | Example |
|---------|---------|
| Issue title | `[SKY-2026-000123] Add offline camera heartbeat` |
| PR title | `[SKY-2026-000123] Add offline camera heartbeat` |
| Branch name | `skynet/SKY-2026-000123/add-offline-camera-heartbeat` |
| Design doc | `docs/ai/designs/SKY-2026-000123-add-offline-camera-heartbeat.md` |
| Plan doc | `docs/ai/plans/SKY-2026-000123-add-offline-camera-heartbeat.md` |
| Commit subject | `Add offline camera heartbeat [SKY-2026-000123]` |
| Log directory (host-side) | `state/logs/SKY-2026-000123/` |
| Workspace clone | `workspace/SKY-2026-000123/<target>/` |

Tracing any artifact to its full task history is therefore one grep away.

---

## 10. Issue & PR Conventions

### Issues created by Researcher

Title:
```
[SKY-2026-000123] <short title>
```

Body MUST start with a YAML front-matter block:

```yaml
---
task-id: SKY-2026-000123
skynet-state: research-draft
skynet-agent: researcher
created-at: 2026-05-02T16:13:00Z
sources: ["https://...", "https://..."]
---
```

Followed by free-form research findings. The front matter is parsed by the orchestrator on every issue update; agents never read each other's free-form text directly.

### PRs created by PR Author

Title:
```
[SKY-2026-000123] <action verb> <object>
```

Body MUST start with:

```yaml
---
task-id: SKY-2026-000123
skynet-state: pr-open
skynet-agent: pr_author
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
2. **Change summary** — bullet list of what changed
3. **Test plan** — what was run, what passed
4. **Path-policy resolution** — which path policies applied to which files

---

## 11. Path-Policy Semantics

Defined in [`docs/architecture.md §10`](docs/architecture.md). Repeated here as the contract:

```
1. For every changed file in the PR, find the matching path policy
   (longest-glob wins; if no glob matches, default_policy applies).

2. Combine across files using most-restrictive-wins:
   - any 'none'  → effective policy = 'none'
   - else any 'soft' → effective policy = 'soft'
   - else 'hard'

3. Effective policy 'none':
   PR enters needs-human label state. No auto-merge ever.
   Operator must merge manually or close.

4. Effective policy 'soft':
   PR holds for `auto_merge.hold_hours`. Discord notification
   emitted at hold start. If no Operator veto received via
   `skynet pause <task-id>` within the window, merge proceeds.

5. Effective policy 'hard':
   PR merges immediately on Reviewer approval + green CI.
```

### "docs-only" / "tests-only" guard rule

A PR resolves to `hard` only if **every** changed path matches one of the `hard` glob rules in `path_policies`. If even one path falls outside (matching `default_policy` or a stricter rule), the effective policy drops to that.

This rule prevents an agent from sneaking product code into a "docs PR." Implementation: the resolver iterates `git diff --name-only` and rejects `hard` resolution unless all paths are explicit `hard` matches.

---

## 12. Hooks (Optional Extension Points)

Hooks are OPTIONAL shell scripts in `.skynet/hooks/` that the framework invokes at specific lifecycle points. They give a target a way to extend behavior without modifying the framework.

| Hook | Invoked when | Stdin | Exit code semantics |
|------|--------------|-------|---------------------|
| `pre-implementation.sh` | before Implementer starts | `{task, design-doc-path}` JSON | 0 = proceed, ≠0 = abort + quarantine |
| `pre-pr.sh` | before PR Author opens PR | `{task, branch, diff-summary}` JSON | 0 = proceed, ≠0 = abort, retry up to retry_cap |
| `pre-merge.sh` | before auto-merge | `{task, pr-number, effective-policy}` JSON | 0 = proceed, ≠0 = block merge, label `needs-human` |

Hooks run inside the agent's sandbox (same path / command / network / budget restrictions as the calling agent). They cannot escape the trust boundaries.

Stdin is a JSON document. Stdout is ignored unless exit code is 0 AND stdout parses as a JSON object with a top-level `modifications` field — in which case allowlisted fields may be modified:

| Allowlisted modification | Effect |
|--------------------------|--------|
| `modifications.task.title` | replaces the issue/PR title |
| `modifications.task.body_extra` | appends a section to the body |

All other modification keys are ignored with a WARNING.

---

## 13. Compliance Verification — `skynet doctor`

`skynet doctor --target <path-or-url>` runs every check defined in this spec and produces output of the form:

```
$ skynet doctor --target /path/to/myrepo

  Compatibility Spec  : v0.4
  Installed framework : 0.4.2
  Detected level      : standard

  REQUIRED FILES
    ✓ .skynet/config.yml
    ✓ docs/ai/mission-and-goals.md
    ✓ docs/ai/repo-map.md
    ✓ docs/ai/working-agreement.md
    ✓ docs/ai/plans/
    ✓ docs/ai/designs/

  CONFIG SCHEMA
    ✓ skynet_version (>=0.4,<1.0 satisfies installed 0.4.2)
    ✓ project.name = "rpi-home-monitor"
    ✓ project.languages = ["python", "yocto"]
    ✓ test.unit defined
    ✓ auto_merge.default_policy = "soft"
    ✓ multi-vendor: implementer (anthropic) ≠ reviewer (openai)
    ✓ budget caps configured

  LABELS
    ✓ skynet/research-draft   present
    ✓ skynet/designed          present
    ... (all 11 labels)

  OPTIONAL ENHANCEMENTS
    ✓ docs/ai/risk-register.md      → standard level
    ✓ docs/history/adr/             → standard level
    ✗ docs/traceability/            → full level not enabled
    ⚠ no .skynet/hooks/ found       → optional, no action needed

  WARNINGS
    ⚠ branch protection on `main` cannot be verified externally;
      Operator must enable in GitHub Settings → Branches

  RESULT: PASS (level: standard)
```

Exit codes:

| Code | Meaning | Orchestrator behavior |
|------|---------|----------------------|
| `0` | PASS | Operates at detected level |
| `1` | WARN | Operates at degraded level (some optional features disabled) |
| `2` | FAIL | Refuses to dispatch tasks |

The orchestrator runs `skynet doctor` once at startup and again on every config change. Exit code 2 anywhere puts the affected target into a `disabled` state until `doctor` passes.

---

## 14. Spec Evolution

The spec is itself versioned, independent of any framework release.

| Compatibility class | Example | Required target action |
|---------------------|---------|------------------------|
| Patch | v0.4.0 → v0.4.1 | none — clarifications only |
| Minor | v0.4 → v0.5 | none — backward-compatible additions |
| Major | v0.x → v1.0; v1.x → v2.0 | run `skynet migrate --to <new>` |

The framework MUST accept targets pinned to multiple compatible minor versions concurrently. It MUST refuse targets pinned across major version boundaries.

### Migration support

```
skynet migrate --target <path> --from 0.4 --to 0.5
```

Opens a PR against the target updating `.skynet/config.yml` and any newly required files. Migration is opt-in; it never runs automatically. The Operator triggers it after reviewing the diff.

---

## 15. Glossary

See `docs/architecture.md §Glossary`. The same terms (Operator, Target, Task, Quarantine, Path policy, Most-restrictive resolution, Compatibility Spec, Version handshake) apply identically.

---

*End of COMPATIBILITY-SPEC.md (v0.0a-2).*
