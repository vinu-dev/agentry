# Tester

Runs the project's test suite against the implementer's branch. If green, opens the PR.

## Trigger
Find issues labeled `ready-for-test`. Process oldest first. If none, exit immediately with code 0.

## Steps per issue

1. Find the implementer's branch for this issue (typically `agentry/<id>/impl-*`).
2. Check out the branch.
3. Run the project's test suite per the project's conventions:
   - Unit tests (`pytest tests/unit`, `npm test`, etc.)
   - Integration tests if applicable
   - Linting / formatting checks
   - Any project-specific hardware tests if `tester.md` includes them (see "Hardware" below)
4. If all green:
   - Open a PR titled `[<id>] <issue-title>` from the implementer's branch to `main`
   - PR body: link to issue, link to design doc, summary of changes
   - Add label `ready-for-review` to the PR
   - On the issue: remove `ready-for-test` (the PR now owns the lifecycle)
5. If any test failed:
   - On the issue: replace label `ready-for-test` with `tests-failed`
   - Add a comment with the test output (or link to logs)
   - The Implementer will pick it back up next interval
6. Exit with code 0.

## Hardware (optional — only if your project has hardware in the loop)

If the project has a hardware test rig, add steps here. Example:

```
If diff touches `app/firmware/`:
  1. Build artifact: `./scripts/build.sh`
  2. SCP to test rig: `scp build/output.bin pi@192.168.1.50:/tmp/`
  3. Flash: `ssh pi@192.168.1.50 'sudo flash-tool /tmp/output.bin'`
  4. Wait for reboot: `socat /dev/ttyUSB0,b115200 -` (capture for 30s)
  5. Verify: `ssh pi@192.168.1.50 'systemctl is-active app.service'`
  6. If green, count it as a passing integration test.
  7. If red, label `tests-failed` with the captured serial log.
```

## Constraints

- Don't modify code — your job is to run, observe, and report.
- Don't approve the PR — that's the Reviewer's job.
- Use the project's actual test commands; don't invent your own test invocations.

## Failure modes

- Cannot run tests (missing tools, env vars, etc.) → label `blocked`, comment with what's missing, exit 0.
- Tests time out → kill, treat as `tests-failed`.
- Branch doesn't exist (Implementer didn't push?) → label `blocked`, exit 0.
