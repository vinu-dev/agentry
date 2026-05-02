# Agentry — Architecture

Status: **v0.0a-final (pre-implementation)**

---

## 1. What it is

Agentry is a small Python daemon that runs **N forever-loops in parallel**, one per role declared by the target repo. Each loop spawns an LLM CLI subprocess (Claude Code, Codex CLI, etc.) at its own interval. The subprocess receives a generic prompt from the framework (which encodes the parallel-pipeline pattern) plus a pointer to the repo's `docs/ai/roles/<role>.md` rule file (which encodes the project-specific work). It does the work, exits. The daemon supervises: timeouts, restarts, Discord pings.

That's the whole product. ~200 lines of Python.

State lives in GitHub (issues, labels, PRs, branches). The daemon has no persistent state. Restart it any time.

**N is whatever the repo declares.** A simple side project might have 5 roles; a medical device project conforming to IEC 62304 + FDA + ISO 13485 might have 10+ roles (researcher, architect, implementer, tester, code reviewer, quality reviewer, cybersecurity reviewer, regulatory/FDA reviewer, traceability tracker, release engineer). The framework doesn't care — same code, different config.

---

## 2. The framework provides the pipeline pattern

This is non-negotiable design discipline: **the framework supplies the meta-pattern; the repo supplies the work specifics.**

### The framework's generic prompt (built into the runtime)

Every role gets the same skeleton prompt — only the role name and other-roles list are substituted:

```
You are the {role_name} in an autonomous software development pipeline.

How this pipeline works:
  - Multiple roles run in parallel — concurrently with you, the following
    roles are also active: {other_roles}.
  - Each role finds work in its own input state, processes one or more items,
    and moves them to an output state. Roles do not coordinate directly;
    they work concurrently.
  - On each invocation you process as many items as you can within your time
    budget, then exit. The orchestrator will respawn you on the next interval.

Your job specifics — including which labels signal work for you, what to
produce, and which label to apply when done — are defined in:

    docs/ai/roles/{role_name}.md

Read that file and follow it exactly.

General loop:
  1. Find work items in your input state (per the rule file).
  2. If none exist, exit immediately with code 0.
  3. Otherwise take the oldest item.
  4. Do the work as described in docs/ai/roles/{role_name}.md.
  5. Move the item to your output state (relabel, open PR, etc.).
  6. Repeat from step 1.

If docs/ai/roles/{role_name}.md doesn't exist, exit with code 1.
```

The Operator does NOT write this prompt. The framework generates it from a template at agent spawn time. The Operator only declares the role; the framework knows how to wake it.

### What the repo provides

Per role, a markdown rule file at `docs/ai/roles/<role>.md`. The repo owner writes these. They define:

- **Trigger** — which label (or schedule) signals work for this role
- **Steps** — what to do per work item, project-specific
- **Output** — which label to apply when done
- **Constraints** — sensitive paths, traceability requirements, compliance concerns
- **Failure modes** — what to do if work can't proceed

This is where the project's flavor lives. A hobby project's `architect.md` is one paragraph; a medical device's `quality_reviewer.md` references ISO 13485 clauses. Same framework runs both.

---

## 3. Roles are extensible

Different projects need different roles. The framework supports any roster a target repo declares.

### Common starter roster (rpi-home-monitor and most projects)

| # | Role | Reads | Produces |
|---|------|-------|----------|
| 1 | **researcher** | repo + web | new issues for missing features (no label, awaiting Operator triage) |
| 2 | **architect** | issues `ready-for-design` | design doc + relabel `ready-for-implementation` |
| 3 | **implementer** | issues `ready-for-implementation` (or `tests-failed`) | code on branch + relabel `ready-for-test` |
| 4 | **tester** | issues `ready-for-test` | runs tests; if green opens PR `ready-for-review`, if red `tests-failed` |
| 5 | **reviewer** | PRs `ready-for-review` | approves OR labels `blocked` |
| 6 | **release** | merged commits since last tag | tag + build + GitHub Release |

### Extended roster for regulated software (medical device example)

A medical device repo conforming to IEC 62304 + ISO 13485 + ISO 14971 + FDA 21 CFR 820 + IEC 81001-5-1 might add:

| # | Role | Reads | Produces |
|---|------|-------|----------|
| 7 | **risk_analyst** | new feature issues (no label) | risk analysis per ISO 14971; relabel `ready-for-design` after risk file updated |
| 8 | **code_reviewer** | PRs after author opens (label `ready-for-code-review`) | functional review of the diff; relabel `ready-for-quality-review` |
| 9 | **quality_reviewer** | PRs `ready-for-quality-review` | ISO 13485 / IEC 62304 conformance check; relabel `ready-for-cyber-review` |
| 10 | **cybersecurity_reviewer** | PRs `ready-for-cyber-review` | IEC 81001-5-1 + FDA cyber guidance check; SBOM diff; threat modeling impact; relabel `ready-for-regulatory-review` |
| 11 | **regulatory_reviewer** | PRs `ready-for-regulatory-review` | FDA 510(k) / 21 CFR Part 820 impact; design history file completeness; relabel `ready-for-traceability` |
| 12 | **traceability_tracker** | PRs `ready-for-traceability` | bidirectional traceability check (req → design → code → tests); relabel `ready-for-merge` |

Total: 11 roles for a medical device project (the original 6 minus `reviewer` since `code_reviewer` replaces it, plus 6 specialized reviewers/trackers).

The example in [`docs/examples/medical-device/`](examples/medical-device/) shows full config + all 11 rule files with realistic content.

### Lifecycle for the medical-device roster

```
new issue (no label)
        ↓ Operator labels `ready-for-risk-analysis`
ready-for-risk-analysis      → risk_analyst writes risk file → ready-for-design
ready-for-design              → architect writes design doc → ready-for-implementation
ready-for-implementation      → implementer codes → ready-for-test
ready-for-test                → tester runs tests → ready-for-code-review (or tests-failed)
ready-for-code-review         → code_reviewer reviews → ready-for-quality-review
ready-for-quality-review      → quality_reviewer checks ISO 13485 → ready-for-cyber-review
ready-for-cyber-review        → cybersecurity_reviewer checks → ready-for-regulatory-review
ready-for-regulatory-review   → regulatory_reviewer checks FDA → ready-for-traceability
ready-for-traceability        → traceability_tracker validates links → ready-for-merge
ready-for-merge               → GitHub auto-merge (per branch protection)
merged
        ↓ release_engineer (daily) → tag + build + GitHub Release if warranted
```

11 stages. 11 labels. 11 rule files. **The framework code is identical to the simpler hobby-project case.**

---

## 4. Configuration

### `.agentry/config.yml` in the target repo

```yaml
target_repo: vinu-dev/rpi-home-monitor

agents:
  researcher:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 60
    total_min: 30
    stall_min: 5

  architect:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 5

  implementer:
    cli: codex
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
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 20
    stall_min: 5

  release:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 1440
    total_min: 60
    stall_min: 15

# Optional — paths the Reviewer's rule file should treat as block-worthy
sensitive_paths:
  - "**/auth/**"
  - "**/ota/**"
  - "**/pairing*"
```

**No `prompt` field.** The framework supplies the prompt; the Operator only configures CLI + args + timeouts + sensitive paths.

For a medical device repo, just declare more roles:

```yaml
agents:
  researcher:              { cli: claude, ... }
  risk_analyst:            { cli: claude, ... }      # NEW
  architect:               { cli: claude, ... }
  implementer:             { cli: codex, ... }
  tester:                  { cli: claude, ... }
  code_reviewer:           { cli: claude, ... }      # was "reviewer"; renamed for clarity
  quality_reviewer:        { cli: claude, ... }      # NEW
  cybersecurity_reviewer:  { cli: claude, ... }      # NEW
  regulatory_reviewer:     { cli: claude, ... }      # NEW
  traceability_tracker:    { cli: claude, ... }      # NEW
  release:                 { cli: claude, ... }
```

11 roles instead of 6. Same framework, same code, different config.

### Per-host `pipeline.local.toml`

Unchanged from before — paths, GitHub token env, Discord webhook env.

---

## 5. The orchestrator (the entire daemon)

```python
GENERIC_PROMPT = """\
You are the {role} in an autonomous software development pipeline.

How this pipeline works:
  - Multiple roles run in parallel — concurrently with you, the following
    roles are also active: {other_roles}.
  - Each role finds work in its own input state, processes one or more items,
    and moves them to an output state. Roles do not coordinate directly;
    they work concurrently.
  - On each invocation you process as many items as you can within your time
    budget, then exit.

Your job specifics are defined in `docs/ai/roles/{role}.md`. Read that file
and follow it exactly.

General loop:
  1. Find work items in your input state (per the rule file).
  2. If none exist, exit immediately with code 0.
  3. Otherwise take the oldest item.
  4. Do the work as described in docs/ai/roles/{role}.md.
  5. Move the item to your output state.
  6. Repeat from step 1.

If docs/ai/roles/{role}.md doesn't exist, exit with code 1.
"""

def role_loop(role, cfg, all_roles):
    other_roles = [r for r in all_roles if r != role]
    prompt = GENERIC_PROMPT.format(role=role, other_roles=", ".join(other_roles))

    while True:
        proc = Popen([cfg["cli"], *cfg["args"], prompt],
                     cwd=workspace_for(cfg["target_repo"]),
                     stdout=PIPE, stderr=STDOUT, text=True)

        last_output = time.time()
        start = time.time()

        while proc.poll() is None:
            line = read_nonblocking(proc.stdout, timeout=1)
            if line:
                last_output = time.time()
                log_line(role, line)

            if time.time() - last_output > cfg["stall_min"] * 60:
                proc.kill()
                discord(f"{role}: stalled (silent {cfg['stall_min']}m)")
                break
            if time.time() - start > cfg["total_min"] * 60:
                proc.kill()
                discord(f"{role}: total timeout ({cfg['total_min']}m)")
                break

        if proc.returncode and proc.returncode != 0:
            discord(f"{role}: exited {proc.returncode}")

        time.sleep(cfg["interval_min"] * 60)


config = load_config()
all_roles = list(config.agents.keys())
for role, cfg in config.agents.items():
    threading.Thread(target=role_loop, args=(role, cfg, all_roles), daemon=True).start()

while True:
    time.sleep(3600)
```

That's the orchestrator. Works for 6 roles or 12 roles — number is dynamic.

---

## 6. Process supervision

Two timeouts per role:

- **`stall_min`** — kill if subprocess produces no stdout for X minutes
- **`total_min`** — kill if subprocess runs longer than Y minutes

Either fires → kill, log, Discord ping, sleep, next interval.

If host process dies: systemd / NSSM restarts it. Threads come back up. GitHub state is unchanged so work resumes naturally.

---

## 7. Notifications

Discord webhook. The orchestrator posts:

- agent.started
- agent.exited (with return code)
- agent.stalled (with how long silent)
- agent.timed_out

Optional batching (every 60s) to stay under Discord's per-webhook rate limit.

---

## 8. Platform support

**Linux-first, Windows-supported.**

- Linux: systemd unit file, runs forever as a user service
- Windows: NSSM service, runs as the Operator's user account (so OAuth credentials for `claude login` / `codex login` are reachable)
- Same Python codebase; only the service installer branches on `sys.platform`

WSL2 is needed on Windows for any role that calls Linux-only tooling (e.g., `bitbake` for Yocto release in rpi-home-monitor's case). The CLIs themselves (`claude`, `codex`) work natively on Windows.

---

## 9. Hardware integration — per repo rules

The framework provides **no special hardware tooling**. Hardware access is the repo's concern, defined in its role rule files.

If a repo's `docs/ai/roles/tester.md` says:

> 1. SSH to the test rig at `192.168.1.50`
> 2. Flash the build artifact via `scp` + `swupdate-cli`
> 3. Wait for boot via serial (`socat /dev/ttyUSB0,b115200`)
> 4. Run smoke test via `journalctl -u app.service`
> 5. Capture results, report back

…then the Tester agent (Claude Code, Codex CLI, etc.) follows those steps using its built-in tools — `ssh`, `scp`, `socat`, shell, curl. The framework just spawns the subprocess and supervises it with timeouts.

Operator's responsibility (host setup, not framework code):

- SSH credentials reachable (e.g., `~/.ssh/id_rsa` accessible to the orchestrator's user)
- Test rig on a network the host can reach (LAN, Tailscale, VPN — whatever)
- Required CLIs installed (`swupdate-cli`, `socat`, `lsusb`, etc.)
- `total_min` set generous enough for flash + boot + smoke (often 30-60 min)

This means:

- **v0.1 supports hardware integration today** — for any repo whose role files include hardware steps
- No special framework code for hardware: no ssh wrapper, no flash driver, no smart-plug controller
- A medical device example can include IEC 62304 Class C hardware verification steps; an embedded systems repo can include flash+smoke; a pure-software repo has no hardware steps. Same framework, different rule files

If a hardware step requires power-cycling a rig (e.g., to recover from a bricked flash), the rule file declares the smart-plug API call directly: `curl http://kasa-plug.local/cmd?action=cycle`. No framework involvement.

---

## 10. v0.1 scope

What ships:

- Orchestrator daemon (~200 lines Python)
- N forever-loops in parallel (declared by config)
- Per-role timeouts
- Generic prompt template (framework-provided)
- Discord notifier
- systemd unit + NSSM XML generators
- Tiny CLI: `agentry start / stop / status / doctor / target add`
- The medical device example as documentation

Not in v0.1 (deferred):

- Babysitter LLM (v0.2+) — reads agent stdout, decides "still working / kill / send 'continue'"
- Telegram / email notifiers (v0.2+) — Discord-only for v0.1
- Multi-target parallelism (v1+) — concurrent dispatch across multiple target repos
- Anything else not on this page

Hardware integration is **not** deferred — see §9. Any role whose rule file includes hardware steps works today using the agent's built-in shell tools.

When v0.1 ships and a target's role files are written, the system runs.

---

## 11. The mental model

> Agentry is a contractor's PM running N alarm clocks. Every interval, an alarm goes off and a worker (LLM CLI) wakes up, reads the repo's instructions for its role, does the work, exits. If a worker doesn't come back on time, the PM kills it and lets the next alarm wake a fresh one. The PM has no memory beyond the alarm schedule and a one-paragraph generic prompt. Everything else is in the repo or in GitHub. Number of alarms is whatever the repo declares — 6 for a hobby project, 11 for a medical device.

That's it.
