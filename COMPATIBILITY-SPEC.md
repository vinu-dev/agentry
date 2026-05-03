# Agentry - Compatibility Specification

Status: **v0.1 alpha**

This is the contract a target repository must satisfy to be operated by
Agentry. The framework is intentionally small: it starts configured role CLIs,
supervises them, writes logs, and relies on GitHub plus role rule files for the
actual workflow.

---

## 1. Target Layout

A target repo can run Agentry when it contains:

```text
agentry/
  config.yml
  .env
  start.ps1
  start.sh
docs/ai/roles/
  <role>.md
```

`scripts/add-to-target.ps1` and `scripts/add-to-target.sh` create the standard
layout. Targets may commit `agentry/config.yml`, start scripts, `.env.example`,
`.gitignore`, `README.md`, and `docs/ai/roles/*.md`.

Targets must not commit:

```text
agentry/.env
agentry/.venv/
agentry/logs/
agentry/state/
```

The generated `agentry/.gitignore` covers those paths.

---

## 2. Config Schema

`agentry/config.yml` is a YAML mapping:

```yaml
target_repo: owner/repo

labels:
  logical-name: actual-github-label

agents:
  role_name:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 5
    prompt: |
      Optional full role prompt. If omitted, Agentry uses the generic prompt.

sensitive_paths:
  - "**/auth/**"
  - "**/.github/workflows/**"
```

Required top-level fields:

- `target_repo`: GitHub repo in `owner/repo` form.
- `agents`: one or more roles.

Optional top-level fields:

- `labels`: target-specific label names to create with `doctor --init-labels`.
- `sensitive_paths`: policy globs for role rule files to consult.

Required per-role fields:

- `cli`: binary name or absolute path.
- `args`: list of CLI args passed before stdin prompt.
- `interval_min`: minutes between role invocations.
- `total_min`: max subprocess runtime.
- `stall_min`: max silence on stdout before the subprocess is killed.

Optional per-role fields:

- `prompt`: full prompt sent to the CLI over stdin. If absent, Agentry builds a
  generic prompt that points the role at `docs/ai/roles/<role>.md`.

Role names must be non-empty and must not contain spaces or `/`.

---

## 3. Role Rule Files

Each declared role should have:

```text
docs/ai/roles/<role>.md
```

For the standard six roles, Agentry falls back to bundled role files if the
target does not provide one. Custom roles beyond the bundled standard roster
must provide their own rule file.

A good role file describes:

- trigger: which labels, schedule, or repo state produce work
- steps: what the agent should do per item
- output: which label, PR, branch, or artifact advances the lifecycle
- constraints: project conventions and sensitive areas
- failure modes: what to label or comment when the role cannot proceed

The framework does not interpret role files. The spawned CLI reads and follows
them.

---

## 4. GitHub Auth

At least one GitHub auth path must work:

- `GITHUB_TOKEN` is set in `agentry/.env`, or
- `gh` is authenticated and can reach `target_repo`.

For unattended operation, `GITHUB_TOKEN` is recommended. Use a fine-grained PAT
restricted to the target repo with:

- contents: read/write
- issues: read/write
- pull requests: read/write
- metadata: read

`agentry doctor --target .` fails if neither auth path is available.

---

## 5. Labels

`agentry doctor --target . --init-labels` creates:

- bundled standard lifecycle labels
- bundled standard failure labels
- any label names listed in `agentry/config.yml` under `labels`

The standard labels are:

- `ready-for-design`
- `ready-for-implementation`
- `ready-for-test`
- `tests-failed`
- `ready-for-review`
- `blocked`
- `merge-conflict`
- `needs-rebase`
- `needs-hardware-verification`

Non-standard role files may use more labels. Add those names to the config
`labels` mapping so doctor can create them for fresh repos.

---

## 6. Start Scripts and Versioning

Each target runs Agentry through:

```text
agentry/start.ps1
agentry/start.sh
```

On first run, the script creates `agentry/.venv/` and installs Agentry from the
GitHub ref embedded in the script. The add-to-target scripts stamp this ref
from the selected Agentry branch when possible, so a target repo does not
silently float to whatever is currently on `main`.

Operators may override the install ref intentionally:

```bash
AGENTRY_INSTALL_REF=<branch-tag-or-commit> ./agentry/start.sh
```

After changing the install ref, delete `agentry/.venv/` and rerun the start
script to recreate the environment.

---

## 7. Runtime Logs and State

Agentry writes subprocess logs to:

```text
agentry/logs/<role>/<timestamp>.log
```

Role prompts may write continuity state under:

```text
agentry/state/
```

GitHub remains the source of truth for issues, PRs, labels, branches, and
review state. Local state should only help a role continue its own work.

---

## 8. Extensibility

Agentry does not bake in a fixed roster. Any repo may declare any number of
roles in `agentry/config.yml`.

Common software repos may use:

```text
researcher -> architect -> implementer -> tester -> reviewer -> release
```

Regulated or security-heavy repos can add roles such as:

```text
risk_analyst
quality_reviewer
cybersecurity_reviewer
regulatory_reviewer
traceability_tracker
security_reviewer
docs_writer
performance_tester
```

The framework behavior is the same for every roster: one supervised loop per
declared role.

---

## 9. Doctor Expectations

`agentry doctor --target .` checks:

1. target config loads and validates
2. role rule files exist, target-specific or bundled
3. configured CLIs are discoverable on `PATH`
4. `agentry/.env` exists
5. GitHub auth is available through `GITHUB_TOKEN` or `gh`
6. `gh` can reach the configured target repo, when available

Exit code:

- `0`: pass
- `2`: fail

Warnings are printed for optional or recoverable gaps, such as a missing CLI
that only affects one role.
