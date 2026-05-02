# Skynet Agentry — Compatibility Specification

Status: **v0.0a-final (pre-implementation)**

The contract a target repository must satisfy to be operated on by Skynet Agentry. Short, because the framework is small.

Architecture: [`docs/architecture.md`](docs/architecture.md). Practical guide: [`docs/how-to-use.md`](docs/how-to-use.md).

---

## 1. What a target repo must provide

Three things. That's it.

### 1.1 `.skynet/config.yml`

Per-target agent assignments + timeouts. See §3.

### 1.2 `docs/ai/roles/*.md`

Six markdown files — one per role. The repo owner writes these. They are the actual instructions each agent follows.

```
target-repo/
└── docs/
    └── ai/
        └── roles/
            ├── researcher.md
            ├── architect.md
            ├── implementer.md
            ├── tester.md
            ├── reviewer.md
            └── release.md
```

Without these files the agents have nothing to do. The framework prompts only point at them.

### 1.3 GitHub labels

Six labels created in the target repo (idempotent — `skynet doctor --init-labels` creates them if missing):

| Label | Where | Meaning |
|-------|-------|---------|
| `ready-for-design` | issue | Architect's input |
| `ready-for-implementation` | issue | Implementer's input |
| `ready-for-test` | issue | Tester's input |
| `tests-failed` | issue | back to Implementer |
| `ready-for-review` | PR | Reviewer's input |
| `blocked` | issue or PR | escalate to human |

Plain English. No prefix. If a target repo already uses one of these for something else, override in `.skynet/config.yml` (see §3).

---

## 2. The lifecycle

```
Researcher opens issue (no label)               ← awaiting Operator triage
        ↓ Operator labels `ready-for-design`
[issue: ready-for-design]
        ↓ Architect writes design doc, relabels `ready-for-implementation`
[issue: ready-for-implementation]
        ↓ Implementer codes on branch, relabels `ready-for-test`
[issue: ready-for-test]
        ↓ Tester runs tests
        ├─ green: opens PR labeled `ready-for-review`
        └─ red:   relabels `tests-failed` (back to Implementer)
[PR: ready-for-review]
        ↓ Reviewer
        ├─ approve: GitHub auto-merge handles the rest
        └─ block:   labels `blocked` (escalate)
[merged]
        ↓ Release Engineer (daily) checks merged commits since last tag
        └─ if release warranted: tag, build, publish GitHub Release
```

GitHub is the state machine. The orchestrator never persists state; it reads label state at every interval.

---

## 3. `.skynet/config.yml` — schema

```yaml
# Required: which target repo this config governs
target_repo: vinu-dev/rpi-home-monitor

# Optional: rename labels if there's a conflict in this target
labels:
  ready-for-design: ready-for-design          # default
  ready-for-implementation: ready-for-implementation
  ready-for-test: ready-for-test
  tests-failed: tests-failed
  ready-for-review: ready-for-review
  blocked: blocked

# Required: agent roster — exactly these 6 roles
agents:
  researcher:    { cli, args, interval_min, total_min, stall_min, prompt }
  architect:     { cli, args, interval_min, total_min, stall_min, prompt }
  implementer:   { cli, args, interval_min, total_min, stall_min, prompt }
  tester:        { cli, args, interval_min, total_min, stall_min, prompt }
  reviewer:      { cli, args, interval_min, total_min, stall_min, prompt }
  release:       { cli, args, interval_min, total_min, stall_min, prompt }

# Optional: paths that must NOT auto-merge even on approval
sensitive_paths:
  - "**/auth/**"
  - "**/ota/**"
  - "**/pairing*"
```

### Field reference

Each agent block:

| Field | Required | Default | Meaning |
|-------|----------|---------|---------|
| `cli` | yes | — | Binary name or path: `claude`, `codex`, custom path |
| `args` | yes | — | Arg list passed to the CLI |
| `interval_min` | yes | — | Sleep this many minutes between subprocess invocations |
| `total_min` | yes | — | Kill if subprocess runs longer than this |
| `stall_min` | yes | — | Kill if subprocess silent (no stdout) for this long |
| `prompt` | yes | — | Single-line prompt; should always be "You are the X. Read docs/ai/roles/X.md and follow it." |

Recommended defaults:

| Role | interval_min | total_min | stall_min |
|------|-------------:|----------:|----------:|
| researcher | 60 | 30 | 5 |
| architect | 5 | 30 | 5 |
| implementer | 5 | 60 | 10 |
| tester | 5 | 30 | 10 |
| reviewer | 5 | 20 | 5 |
| release | 1440 | 60 | 15 |

Operator tunes these per project.

---

## 4. Per-host `pipeline.local.toml`

Lives in `~/.skynet/pipeline.local.toml`, gitignored, per-host:

```toml
[host]
state_dir = "~/.skynet/state"          # heartbeat / log files

[github]
token_env = "GITHUB_TOKEN"             # name of env var holding PAT

[notification]
discord_webhook_env = "DISCORD_WEBHOOK_URL"

[orchestrator]
batch_notify_seconds = 60              # Discord flush window
```

---

## 5. Role rule file format

Each `docs/ai/roles/<role>.md` is a markdown document the repo owner writes. Recommended sections:

```markdown
# <Role>

## Trigger
What labels (or schedules) make this role have work to do.
"If no work, exit immediately" should always be present.

## Steps
Numbered list of what to do per work item.
Should always end with a label transition (or PR creation, or
issue closure) so the lifecycle advances.

## Constraints
Any project-specific rules: file conventions, security boundaries,
which paths require human review, etc.

## Failure modes
What to do if the work can't be completed (e.g., "label `blocked` and exit").
```

These files are the heart of customization. Two repos using the same Skynet Agentry framework can have very different agent behavior depending on what's written here.

---

## 6. `skynet doctor` validation

`skynet doctor --target <path>` checks:

1. `.skynet/config.yml` exists and parses
2. All 6 agents declared with required fields
3. All 6 role files exist at `docs/ai/roles/*.md`
4. The 6 labels exist in the target repo (or `--init-labels` creates them)
5. `cli` binaries exist on PATH (or path is absolute)

Exit codes: `0` = pass, `1` = warnings, `2` = fail.

The orchestrator runs `skynet doctor` once at startup and refuses to run any role whose prerequisites fail.

---

## 7. Sensitive paths and auto-merge

The orchestrator does **not** auto-merge — Reviewer agent does, by approving the PR (GitHub's branch-protection auto-merge handles the actual click).

If a PR's diff touches any glob in `sensitive_paths`, the Reviewer's role file should instruct it to add the `blocked` label instead of approving. This means:

- The auto-merge guard is enforced **by the role rule file**, not by the framework
- The framework's responsibility is just: dispatch the Reviewer agent, give it the diff
- The repo owner's `docs/ai/roles/reviewer.md` says: "if `git diff --name-only` matches any pattern in `.skynet/config.yml`'s `sensitive_paths`, label `blocked` and exit"

This keeps the framework dumb and the policy in the repo where it belongs.

---

## 8. Spec versioning

The spec is small enough that versioning is informal. When a breaking change happens:

- Bump the version comment at the top of this file
- Update `skynet doctor` to handle both old and new
- Provide a migration note

There's no JSON Schema file, no PEP 440 ranges, no version handshake. The framework either works against your repo or it doesn't, and `skynet doctor` tells you which.

---

## 9. Glossary

- **Operator** — the human running Skynet Agentry. Triages new issues, vetos sensitive merges, handles `blocked` items.
- **Target** — any repo with `.skynet/config.yml` + `docs/ai/roles/*.md` + the 6 labels.
- **Role rule file** — `docs/ai/roles/<role>.md`. Repo-specific instructions for one agent role.
- **Forever-loop** — the orchestrator's per-role thread that wakes the agent, waits, sleeps, repeats.

---

*End of COMPATIBILITY-SPEC.md.*
