# Skynet Agentry — Compatibility Specification

Status: **v0.0a-final (pre-implementation)**

The contract a target repository must satisfy to be operated on by Skynet Agentry. Short, because the framework is small and most of the project-specific logic lives in the target repo's role rule files.

Architecture: [`docs/architecture.md`](docs/architecture.md). Practical guide: [`docs/how-to-use.md`](docs/how-to-use.md). Example for regulated software: [`docs/examples/medical-device/`](docs/examples/medical-device/).

---

## 1. What a target repo must provide

Three things. That's it.

### 1.1 `.skynet/config.yml`

Per-target agent declarations + timeouts. Declares which roles exist for this project and which CLI/timeouts each gets. **No prompt strings** — the framework supplies a generic prompt.

### 1.2 `docs/ai/roles/<role>.md` for every declared role

One markdown file per role. The repo owner writes these. They are the actual project-specific instructions each agent follows.

For a small project, that's typically 5-7 files. For a regulated medical device project, it's 10-12+. The framework runs identically either way.

### 1.3 GitHub labels referenced by the rule files

The rule files specify which labels signal work for each role. The framework calls `skynet doctor --init-labels` to create them in the target repo if missing.

For the standard 6-role hobby roster, the labels are:
- `ready-for-design`
- `ready-for-implementation`
- `ready-for-test`
- `tests-failed`
- `ready-for-review`
- `blocked`

For an extended medical device roster, more labels exist (e.g., `ready-for-quality-review`, `ready-for-cyber-review`, `ready-for-regulatory-review`, `ready-for-traceability`). The set is whatever the repo's rule files reference.

---

## 2. The roles are extensible

Skynet Agentry doesn't bake in a fixed roster. **A target repo declares whatever roles it needs in `.skynet/config.yml`.** The framework spawns one forever-loop per declared role.

### Common starter roster (most projects)

```yaml
agents:
  researcher:    { cli: claude, ... }
  architect:     { cli: claude, ... }
  implementer:   { cli: codex, ... }
  tester:        { cli: claude, ... }
  reviewer:      { cli: claude, ... }
  release:       { cli: claude, ... }
```

6 roles. Suitable for hobby projects, small teams, internal tools.

### Extended roster — example: medical device development

```yaml
agents:
  researcher:              { cli: claude, ... }
  risk_analyst:            { cli: claude, ... }      # ISO 14971 risk analysis
  architect:               { cli: claude, ... }
  implementer:             { cli: codex, ... }
  tester:                  { cli: claude, ... }
  code_reviewer:           { cli: claude, ... }      # functional code review
  quality_reviewer:        { cli: claude, ... }      # ISO 13485 / IEC 62304
  cybersecurity_reviewer:  { cli: claude, ... }      # IEC 81001-5-1 / FDA cyber
  regulatory_reviewer:     { cli: claude, ... }      # FDA 510(k) / 21 CFR 820
  traceability_tracker:    { cli: claude, ... }      # bidirectional req → test
  release:                 { cli: claude, ... }
```

11 roles. See [`docs/examples/medical-device/`](docs/examples/medical-device/) for a complete config plus all rule files.

### Other rosters you might design

- **Open-source library**: researcher + architect + implementer + tester + reviewer + docs_writer + release
- **Embedded firmware**: researcher + architect + implementer + tester (with hardware steps in the rule file) + reviewer + release
- **Web service**: researcher + architect + implementer + tester + reviewer + security_reviewer + performance_tester + release

The framework treats any roster identically. Operator picks what fits the project.

---

## 3. The lifecycle is repo-specific

There's no single canonical lifecycle. The label progression is whatever the rule files describe.

### Standard 6-role lifecycle

```
new issue (no label)
        ↓ Operator labels `ready-for-design`
ready-for-design       → Architect → ready-for-implementation
ready-for-implementation → Implementer → ready-for-test
ready-for-test         → Tester → ready-for-review (PR) | tests-failed
ready-for-review (PR)  → Reviewer → approve | blocked
approved               → GitHub auto-merge
merged
```

### Extended medical-device lifecycle (11 roles)

```
new issue (no label)
        ↓ Operator labels `ready-for-risk-analysis`
ready-for-risk-analysis     → Risk Analyst → ready-for-design
ready-for-design            → Architect → ready-for-implementation
ready-for-implementation    → Implementer → ready-for-test
ready-for-test              → Tester → ready-for-code-review | tests-failed
ready-for-code-review       → Code Reviewer → ready-for-quality-review
ready-for-quality-review    → Quality Reviewer → ready-for-cyber-review
ready-for-cyber-review      → Cybersecurity Reviewer → ready-for-regulatory-review
ready-for-regulatory-review → Regulatory Reviewer → ready-for-traceability
ready-for-traceability      → Traceability Tracker → ready-for-merge
ready-for-merge             → GitHub auto-merge
merged
        ↓ Release Engineer (daily) → tag + build + GitHub Release
```

Each transition is encoded in the corresponding role's `docs/ai/roles/<role>.md` file. The framework doesn't know what comes next; the rule files chain via labels.

---

## 4. `.skynet/config.yml` — schema

```yaml
# Required: which target repo this config governs
target_repo: vinu-dev/rpi-home-monitor

# Optional: rename labels in this target if there's a naming conflict
labels:
  ready-for-design: ready-for-design          # default — usually omit this block
  # ... only override entries you need to rename

# Required: agent roster — declare any number of roles
agents:
  <role-name>:
    cli: <binary-name-or-path>                # e.g. "claude", "codex", "ollama-shim"
    args: [<list of CLI args>]                # e.g. ["-p", "--dangerously-skip-permissions"]
    interval_min: <int>                       # sleep N min between subprocess invocations
    total_min: <int>                          # kill if running longer than N min
    stall_min: <int>                          # kill if silent (no stdout) for N min
  <other-role-name>:
    ...

# Optional: paths the Reviewer's rule file should treat as block-worthy
sensitive_paths:
  - "**/auth/**"
  - "**/ota/**"
  - "**/pairing*"
```

### Field reference

Per role:

| Field | Required | Meaning |
|-------|----------|---------|
| `cli` | yes | Binary name or absolute path. Looked up on PATH if name only. |
| `args` | yes | List passed to the CLI before the framework's prompt |
| `interval_min` | yes | Sleep this many minutes between subprocess invocations |
| `total_min` | yes | Kill if subprocess runs longer than this |
| `stall_min` | yes | Kill if subprocess silent (no stdout) for this long |

**No `prompt` field** — the framework generates the prompt from a built-in template, substituting the role name and the list of other roles in the config.

### Recommended defaults

| Role | interval_min | total_min | stall_min | Notes |
|------|------------:|----------:|----------:|-------|
| researcher | 60 | 30 | 5 | hourly cron |
| risk_analyst | 5 | 30 | 5 | (medical) |
| architect | 5 | 30 | 5 | |
| implementer | 5 | 60 | 10 | |
| tester | 5 | 60 | 15 | longer if hardware steps |
| code_reviewer | 5 | 20 | 5 | |
| quality_reviewer | 5 | 30 | 5 | (medical, larger context) |
| cybersecurity_reviewer | 5 | 30 | 5 | (medical) |
| regulatory_reviewer | 5 | 30 | 5 | (medical) |
| traceability_tracker | 10 | 30 | 5 | (medical) |
| reviewer | 5 | 20 | 5 | (hobby) |
| release | 1440 | 60 | 15 | daily |

Operator tunes per project.

---

## 5. Per-host `pipeline.local.toml`

```toml
[host]
state_dir = "~/.skynet/state"

[github]
token_env = "GITHUB_TOKEN"

[notification]
discord_webhook_env = "DISCORD_WEBHOOK_URL"

[orchestrator]
batch_notify_seconds = 60
```

---

## 6. Role rule file format

Each `docs/ai/roles/<role>.md` is a markdown document the repo owner writes. Required structure:

```markdown
# <Role Name>

## Trigger
What labels (or schedules) make this role have work to do. Always end with
"if no work, exit immediately."

## Steps
Numbered list of what to do per work item. Should always end with a label
transition (or PR creation, or issue closure) so the lifecycle advances.

## Constraints (optional)
Any project-specific rules: file conventions, security boundaries, paths
requiring human review, regulatory compliance references.

## Failure modes
What to do if work can't be completed (e.g., "label `blocked` and exit").

## References (optional)
Links to standards (ISO 13485 §8.4, IEC 62304 §5.5, FDA 21 CFR 820.30, etc.),
internal docs, prior decisions.
```

The framework prompt instructs the agent to **read this file and follow it exactly**. Everything project-specific lives here.

---

## 7. The framework's generic prompt

The framework synthesizes this prompt at agent spawn time. The Operator does **not** write it; it's identical across every role and every repo:

```
You are the {role_name} in an autonomous software development pipeline.

How this pipeline works:
  - Multiple roles run in parallel — concurrently with you, the following
    roles are also active: {other_roles}.
  - Each role finds work in its own input state, processes one or more items,
    and moves them to an output state. Roles do not coordinate directly;
    they work concurrently.
  - On each invocation you process as many items as you can within your time
    budget, then exit.

Your job specifics — including which labels signal work for you, what to
produce, and which label to apply when done — are defined in:

    docs/ai/roles/{role_name}.md

Read that file and follow it exactly.

General loop:
  1. Find work items in your input state.
  2. If none, exit immediately with code 0.
  3. Otherwise take the oldest item.
  4. Do the work as described in docs/ai/roles/{role_name}.md.
  5. Move the item to your output state.
  6. Repeat from step 1.

If docs/ai/roles/{role_name}.md doesn't exist, exit with code 1.
```

`{role_name}` and `{other_roles}` are substituted from `.skynet/config.yml`. Nothing else changes.

---

## 8. `skynet doctor` validation

`skynet doctor --target <path>` checks:

1. `.skynet/config.yml` exists, parses, contains at least one agent
2. Every declared agent has all required fields (cli, args, interval_min, total_min, stall_min)
3. Every declared agent has a corresponding `docs/ai/roles/<role>.md` file present and non-empty
4. Every CLI binary in the config exists on PATH (or absolute path is valid)
5. The labels referenced in role files exist in the target repo on GitHub (or `--init-labels` creates them)

Exit codes: `0` = pass, `1` = warnings, `2` = fail.

The orchestrator runs `skynet doctor` once at startup and refuses to spawn any role whose prerequisites fail.

---

## 9. Sensitive paths and auto-merge

The orchestrator does **not** auto-merge — the Reviewer (or whichever role the project designates as "final approver") does, by approving the PR. GitHub's branch-protection auto-merge handles the actual click.

If a PR's diff touches any glob in `sensitive_paths`, the Reviewer's rule file should instruct it to add the `blocked` label instead of approving. This means:

- The auto-merge guard is enforced **by the role rule file**, not by the framework
- The framework's responsibility is just: dispatch the agent, give it the diff
- The repo owner's `docs/ai/roles/reviewer.md` (or `docs/ai/roles/regulatory_reviewer.md`, etc.) says: "if `git diff --name-only` matches any pattern in `.skynet/config.yml`'s `sensitive_paths`, label `blocked` and exit"

This keeps the framework dumb and the policy in the repo where it belongs.

---

## 10. Hardware integration — per repo, no special framework support

Hardware access is the repo's concern, defined in role rule files (typically `tester.md`). The framework provides no special hardware tooling — it just spawns LLM CLI subprocesses which already have access to ssh, scp, curl, socat, and shell commands.

If a repo's `tester.md` includes hardware steps (SSH to a Pi, flash via SWUpdate, scrape serial console, etc.), the agent (Claude Code, Codex CLI) will execute them using its built-in tools. Set `total_min` generous enough to allow flash + boot + smoke (often 30-60 minutes).

The Operator is responsible for host setup: SSH credentials, network reachability, required CLIs (`socat`, `swupdate-cli`, `lsusb`, etc.) installed on the host.

---

## 11. Spec versioning

Informal. When a breaking change happens:

- Bump the version comment at the top of this file
- Update `skynet doctor` to handle both old and new
- Provide a migration note

There's no JSON Schema file, no PEP 440 ranges, no version handshake. The framework either works against your repo or it doesn't, and `skynet doctor` tells you which.

---

## 12. Glossary

- **Operator** — the human running Skynet Agentry. Triages new issues, vetos sensitive merges, handles `blocked` items.
- **Target** — any repo with `.skynet/config.yml` + `docs/ai/roles/*.md` + the labels referenced by those rule files.
- **Role rule file** — `docs/ai/roles/<role>.md`. Repo-specific instructions for one agent role.
- **Forever-loop** — the orchestrator's per-role thread that wakes the agent, waits, sleeps, repeats.
- **Generic prompt** — the framework-synthesized prompt that wraps every role invocation, encoding the parallel-pipeline pattern. Same across all roles and projects.

---

*End of COMPATIBILITY-SPEC.md.*
