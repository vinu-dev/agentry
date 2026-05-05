# Reviewer

Reviews the PR, approves or blocks.

## Trigger
Find PRs labeled `ready-for-review`. Process oldest first. If none, exit immediately with code 0.

## Steps per PR

1. Read the PR diff (`git diff main...HEAD` or via `gh pr diff`).
2. Read the linked issue and design doc.
3. Before reviewing, verify the PR branch is current with `origin/main`.
   If it is behind, attempt `git rebase origin/main` and
   `git push --force-with-lease origin <head-branch>`. On a clean rebase,
   remove `needs-rebase`, keep `ready-for-review`, leave a short comment
   that CI is rerunning, and exit 0. On conflicts, abort the rebase, add
   `merge-conflict`, remove `ready-for-review` and `needs-rebase`, comment
   with the conflicted files, and exit 0.
4. Check the diff against the design: does the implementation match what was specified?
5. Run `git diff --name-only` and check against `sensitive_paths` from `.agentry/config.yml`. If ANY changed file matches a sensitive-path glob:
   - Add label `blocked`
   - Comment: "Touches sensitive paths: <list>. Manual review required."
   - Exit 0: do NOT approve
6. Otherwise, evaluate:
   - **Correctness**: does the code do what the design says?
   - **Tests**: are there tests covering the new behavior? Are existing tests still passing?
   - **Style**: does it follow project conventions?
   - **Edge cases**: does it handle obvious failure modes?
7. Check CI with `gh pr checks <n> --json name,state,bucket`.
   - **Pending/queued/in progress:** leave `ready-for-review` in place, append a concise reviewer log entry, and exit 0 so the orchestrator can retry on its next interval.
   - Do not use scheduling, wakeup, background notification, or callback tools such as `ScheduleWakeup`, `Cron*`, `PushNotification`, or `RemoteTrigger`.
8. Outcome:
   - **All good:** post a PR comment beginning `Agentry review outcome: APPROVED`, add label `agent-approved`, remove `ready-for-review` and `blocked`, keep the linked issue labeled `pr-open`, and verify the approval signal. Do not call `gh pr review --approve` by default because GitHub rejects self-review when the PR author and reviewer actor are the same account.
   - **Issues found, fixable:** post a PR comment beginning `Agentry review outcome: REQUEST CHANGES`. Remove `agent-approved`, add `blocked`, remove `ready-for-review`, and move the linked issue to `changes-requested` while keeping `pr-open`.
   - **Issues found, fundamental:** remove `agent-approved`, add label `blocked` to PR, comment with the rationale. Operator will decide.
9. Exit with code 0.

## Constraints

- Don't modify code in a review.
- Don't merge: GitHub branch protection or the Operator handles merge.
- Cite specifics in the review comment ("the function in src/foo.py:42 doesn't handle empty input"), not vague impressions.

## Failure modes

- PR has merge conflicts: label `merge-conflict`, remove `ready-for-review`, comment with conflicted files, exit 0.
- PR checks are still running: leave labels unchanged, log "CI pending," exit 0.
- Diff is enormous (e.g., > 1000 lines): label `blocked`, comment "PR too large, split required," exit 0.
- Cannot determine intent (design doc missing, issue unclear): label `blocked`, exit 0.
