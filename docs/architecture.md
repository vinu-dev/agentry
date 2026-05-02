# Skynet Agentry — Architecture

Status: **v0.0a-final (pre-implementation)**

This is the lean version. Earlier drafts overengineered. The actual system is small.

---

## 1. What it is

Skynet Agentry is a small Python daemon that runs **6 forever-loops in parallel**, one per role. Each loop spawns an LLM CLI subprocess (Claude Code, Codex CLI, etc.) at its own interval, the subprocess does its job using the rules defined in the target repo, and exits. The daemon supervises: timeouts, restarts, Discord pings.

That's the whole product.

State lives in GitHub (issues, labels, PRs, branches). The daemon has no persistent state. Restart it any time.

---

## 2. The 6 roles

| # | Role | Trigger | Reads | Produces |
|---|------|---------|-------|----------|
| 1 | **Researcher** | hourly cron | repo + web | new GitHub issues (no label, awaiting Operator) |
| 2 | **Architect** | every 5 min | issues `ready-for-design` | design doc on a branch + relabel `ready-for-implementation` |
| 3 | **Implementer** | every 5 min | issues `ready-for-implementation` (or `tests-failed`) | code on a branch + relabel `ready-for-test` |
| 4 | **Tester** | every 5 min | issues `ready-for-test` | runs tests; if green opens PR with `ready-for-review`, if red labels `tests-failed` |
| 5 | **Reviewer** | every 5 min | PRs `ready-for-review` | approve OR `blocked` |
| 6 | **Release Engineer** | daily cron | merged commits since last tag | tag + build + release artifact + GitHub Release |

Each role gets its own model assignment. Operator picks: Claude for research, Codex for implementation, local Llama for review, etc.

---

## 3. The labels (plain English, no prefix)

| Label | Where | Meaning |
|-------|-------|---------|
| `ready-for-design` | issue | Architect's input |
| `ready-for-implementation` | issue | Implementer's input (also re-applied if tests fail or review requests changes) |
| `ready-for-test` | issue | Tester's input |
| `tests-failed` | issue | back to Implementer |
| `ready-for-review` | PR | Reviewer's input |
| `blocked` | issue or PR | escalate to human |

6 labels. No prefix. Plain English. Renamable per-target if there's a conflict (rare).

---

## 4. The orchestrator (the entire daemon)

```python
from subprocess import Popen, TimeoutExpired
import threading, time

def role_loop(name, cfg):
    while True:
        proc = Popen([cfg["cli"], *cfg["args"]],
                     cwd=workspace_for(cfg["target_repo"]),
                     stdout=PIPE, stderr=STDOUT, text=True)

        last_output = time.time()
        start = time.time()

        while proc.poll() is None:
            line = read_nonblocking(proc.stdout, timeout=1)
            if line:
                last_output = time.time()
                log_line(name, line)

            if time.time() - last_output > cfg["stall_min"] * 60:
                proc.kill()
                discord(f"{name}: stalled (silent {cfg['stall_min']}m)")
                break
            if time.time() - start > cfg["total_min"] * 60:
                proc.kill()
                discord(f"{name}: total timeout ({cfg['total_min']}m)")
                break

        if proc.returncode and proc.returncode != 0:
            discord(f"{name}: exited {proc.returncode}")

        time.sleep(cfg["interval_min"] * 60)


for role, cfg in load_config().agents.items():
    threading.Thread(target=role_loop, args=(role, cfg), daemon=True).start()

while True:
    time.sleep(3600)  # main thread idle; threads do everything
```

That's the orchestrator. About 30 lines for the core. Add config loader, Discord poster, CLI, service installers → ~200 lines total.

---

## 5. Configuration

### Per-target — `.skynet/config.yml` in the target repo

```yaml
target_repo: vinu-dev/rpi-home-monitor

agents:
  researcher:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 60
    total_min: 30
    stall_min: 5
    prompt: |
      You are the Researcher. Read docs/ai/roles/researcher.md and follow it.

  architect:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 5
    prompt: |
      You are the Architect. Read docs/ai/roles/architect.md and follow it.

  implementer:
    cli: codex
    args: ["--auto-approve"]
    interval_min: 5
    total_min: 60
    stall_min: 10
    prompt: |
      You are the Implementer. Read docs/ai/roles/implementer.md and follow it.

  tester:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 30
    stall_min: 10
    prompt: |
      You are the Tester. Read docs/ai/roles/tester.md and follow it.

  reviewer:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 5
    total_min: 20
    stall_min: 5
    prompt: |
      You are the Reviewer. Read docs/ai/roles/reviewer.md and follow it.

  release:
    cli: claude
    args: ["-p", "--dangerously-skip-permissions"]
    interval_min: 1440          # daily
    total_min: 60
    stall_min: 15
    prompt: |
      You are the Release Engineer. Read docs/ai/roles/release.md and follow it.
```

The framework prompt is **generic**. Real instructions live in the target repo at `docs/ai/roles/<role>.md`.

### Per-host — `pipeline.local.toml`

```toml
[host]
state_dir = "~/.skynet/state"

[github]
token_env = "GITHUB_TOKEN"

[notification]
discord_webhook_env = "DISCORD_WEBHOOK_URL"
```

---

## 6. What target repos provide

**The repo owner writes role rules**. Without these, the agents have nothing to do.

```
target-repo/
├── .skynet/
│   └── config.yml                   ← agent assignments + timeouts
└── docs/
    └── ai/
        └── roles/
            ├── researcher.md        ← project-specific instructions
            ├── architect.md
            ├── implementer.md
            ├── tester.md
            ├── reviewer.md
            └── release.md
```

A role file is a markdown document telling the agent what to do in this repo. Example sketch for `architect.md`:

```markdown
# Architect

## Trigger
Find issues labeled `ready-for-design` (oldest first). If none, exit.

## Steps
1. Read issue + linked context + docs/architecture/ + docs/ai/risk-register.md
2. Write design doc to docs/ai/designs/<id>-<slug>.md with:
   - Goal, acceptance criteria, architecture impact, risks, test plan
3. Commit on branch `skynet/<id>/design-<slug>`
4. Push
5. Open PR titled `[design] <issue-title>`
6. Replace label `ready-for-design` with `ready-for-implementation`
7. Exit
```

Same shape for the other 5 roles. Repo owner customizes per their own conventions.

The framework is dumb. It just dispatches CLI processes. The intelligence — what each role does, how, when, with what conventions — lives in the target repo.

---

## 7. Process supervision (the watchdog, inline)

Two timeouts per role, declared in `.skynet/config.yml`:

- **`stall_min`** — kill if subprocess produces no stdout for X minutes
- **`total_min`** — kill if subprocess runs longer than Y minutes

If either fires: kill, log, Discord ping, sleep, next interval.

If subprocess exits non-zero: log, Discord ping, sleep, next interval.

If host process itself dies: systemd / NSSM restarts it. Threads come back up. GitHub state is unchanged so work resumes naturally.

That's the whole watchdog. No 4-mode classifier. No checkpoint resume. No state machine in our code.

---

## 8. "Are agents waiting for input?"

**v0.1 approach:** invoke each CLI with non-interactive flags (`--dangerously-skip-permissions`, `--auto-approve`, etc., per CLI). Sidesteps almost every "waiting on confirmation" case.

If a CLI does pause, `stall_min` catches it: no stdout for 5 min → killed, retried next interval.

**v0.2+ (deferred):** optional **babysitter LLM** that watches stdout and decides "still working / kill / send 'continue' to stdin." Per-role, configurable. Not in v0.1.

---

## 9. Notifications

Discord webhook. The orchestrator posts:

- agent.started
- agent.exited (with return code)
- agent.stalled (with how long silent)
- agent.timed_out

Optional batching (every 60s) to avoid hitting Discord's per-webhook rate limit if loops are fast.

That's the whole notifier. ~30 lines.

---

## 10. Platform support

**Linux-first, Windows-supported.**

- Linux: systemd unit file, runs forever as a user service
- Windows: NSSM service, runs as the Operator's user account (so OAuth-stored credentials for `claude login` / `codex login` are reachable)
- Same Python codebase; only the service installer branches on `sys.platform`

WSL2 is needed on Windows for any role that calls Linux-only tooling (e.g., `bitbake` for Yocto release in rpi-home-monitor's case). The CLIs themselves (`claude`, `codex`) work natively on Windows.

---

## 11. v0.1 scope

What ships:

- Orchestrator daemon (~200 lines Python)
- 6 forever-loops in parallel
- Per-role timeouts
- Discord notifier
- systemd unit + NSSM XML generators
- Tiny CLI: `skynet start / stop / status`

Not in v0.1 (deferred):

- Babysitter LLM (v0.2+)
- Hardware test integration (v1+)
- Anything else not on this page

When v0.1 ships and rpi-home-monitor's role files are written, the system runs.

---

## 12. The mental model

> Skynet Agentry is a contractor's PM running 6 alarm clocks. Every interval, an alarm goes off and a worker (LLM CLI) wakes up, reads the repo's instructions for its role, does the work, exits. If a worker doesn't come back on time, the PM kills it and lets the next alarm wake a fresh one. The PM has no memory beyond the alarm schedule. Everything else is in the repo or in GitHub.

That's it.
