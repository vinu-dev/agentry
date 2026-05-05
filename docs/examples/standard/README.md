# Standard Example - Agentry Roster

This is the standard six-role Agentry roster for hobby projects, small teams,
internal tools, and ordinary GitHub repositories.

For regulated software, see the [medical-device example](../medical-device/).

## The Six Roles

| Role | Watches | Produces |
|------|---------|----------|
| `researcher` | repo/web signals, only when autonomous mode allows it | new issues labeled `ready-for-design` |
| `architect` | issues labeled `ready-for-design` | spec branch + `ready-for-implementation` |
| `implementer` | issues labeled `ready-for-implementation`, `tests-failed`, or `changes-requested` | code/tests + `ready-for-test` |
| `tester` | issues labeled `ready-for-test` | issue labeled `pr-open` plus PR labeled `ready-for-review`, or issue labeled `tests-failed` |
| `reviewer` | PRs labeled `ready-for-review` or `merge-train-waiting`, after checks settle | `agent-approved`, `blocked`/`changes-requested`, or unchanged while CI is still pending |
| `release` | release-approved work, when enabled | tags, artifacts, GitHub Release |

## Lifecycle

```text
ready-for-design issue
  -> architect
  -> ready-for-implementation issue
  -> implementer
  -> ready-for-test issue
  -> tester
  -> pr-open issue
  -> ready-for-review PR
  -> reviewer (pre-gated while CI is pending; no wakeup tools)
  -> merge-train-waiting PR if an older shared-file PR must merge first
  -> agent-approved PR
```

Researcher is disabled by default. Release is disabled by default. The default
run mode is `pipeline`, which means Agentry processes existing labels but does
not create new issues by itself.

## Files In This Example

```text
docs/examples/standard/
  README.md
  agentry/
    config.yml
  docs/ai/roles/
    researcher.md
    architect.md
    implementer.md
    tester.md
    reviewer.md
    release.md
```

The example mirrors the target-repo layout created by
`scripts/add-to-target.ps1` and `scripts/add-to-target.sh`.

## Recommended Setup

From inside a real target repo, prefer the installer scripts instead of copying
this example by hand:

Windows PowerShell:

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex
```

Linux shell:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
```

Then:

1. Copy `agentry/.env.example` to `agentry/.env` and set `GITHUB_TOKEN`.
2. Run `agentry/start.ps1 configure --target . --defaults` or
   `./agentry/start.sh configure --target . --defaults`.
3. Open `agentry/start.ps1 gui --target .` or `./agentry/start.sh gui --target .`.
4. Edit `docs/ai/roles/*.md` with project-specific rules.
5. Run `agentry/start.ps1` or `./agentry/start.sh` when you want agents active.

The generated start scripts pin Agentry to the selected branch, tag, or commit
at install time. Prefer a release tag such as `v0.1.2` for stable target repos.
On Linux, that looks like:

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/v0.1.2/scripts/add-to-target.sh | AGENTRY_BRANCH=v0.1.2 bash
```

## Model Defaults

The standard config uses portable `npx` commands and optimized Codex model
tiers:

- `gpt-5.4-mini`: researcher, tester, release
- `gpt-5.4`: architect, implementer, reviewer

Targets can replace any role with Claude Code, local Llama/Ollama, or wrapper
scripts by changing that role's `cli` and `args`.

The standard config also enables bounded work packets and sets Reviewer
`trigger.pr_check_gate: settled`, so review does not spawn while all matching PR
checks are still pending. Each work packet names one `Selected Candidate`; roles
must process only that item during the current invocation.

## Merge-Sensitive Paths

Set `merge_sensitive_paths` in `agentry/config.yml` for generated docs, release
files, workflows, or other high-conflict files. Reviewer processes the oldest
matching PR first and parks newer matching PRs with `merge-train-waiting`.

## How To Extend

Add a new role under `agents:` in `agentry/config.yml`, then add the matching
`docs/ai/roles/<role>.md` file. Agentry starts one supervised loop per enabled
role allowed by the current run mode.

For extra safety-sensitive stages, copy the pattern in the
[medical-device example](../medical-device/).
