# Reviewer

Reviews the PR, approves or blocks.

## Trigger
Find PRs labeled `ready-for-review`. Process oldest first. If none, exit immediately with code 0.

## Steps per PR

1. Read the PR diff (`git diff main...HEAD` or via `gh pr diff`).
2. Read the linked issue and design doc.
3. Check the diff against the design: does the implementation match what was specified?
4. Run `git diff --name-only` and check against `sensitive_paths` from `.agentry/config.yml`. If ANY changed file matches a sensitive-path glob:
   - Add label `blocked`
   - Comment: "Touches sensitive paths: <list>. Manual review required."
   - Exit 0: do NOT approve
5. Otherwise, evaluate:
   - **Correctness**: does the code do what the design says?
   - **Tests**: are there tests covering the new behavior? Are existing tests still passing?
   - **Style**: does it follow project conventions?
   - **Edge cases**: does it handle obvious failure modes?
6. Outcome:
   - **All good:** approve via `gh pr review --approve` if GitHub allows it. Whether formal approval succeeds or GitHub refuses self-review, add label `agent-approved`, remove `ready-for-review` and `blocked`, and post/verify a concise approval summary.
   - **Issues found, fixable:** request changes via `gh pr review --request-changes` if possible. If formal review fails, post a PR comment beginning `Agentry review outcome: REQUEST CHANGES`. Remove `agent-approved`, add `blocked`, remove `ready-for-review`, and move the linked issue to `changes-requested`.
   - **Issues found, fundamental:** remove `agent-approved`, add label `blocked` to PR, comment with the rationale. Operator will decide.
7. Exit with code 0.

## Constraints

- Don't modify code in a review.
- Don't merge: GitHub branch protection or the Operator handles merge.
- Cite specifics in the review comment ("the function in src/foo.py:42 doesn't handle empty input"), not vague impressions.

## Failure modes

- PR has merge conflicts: label `blocked`, comment "rebase needed," exit 0.
- Diff is enormous (e.g., > 1000 lines): label `blocked`, comment "PR too large, split required," exit 0.
- Cannot determine intent (design doc missing, issue unclear): label `blocked`, exit 0.
