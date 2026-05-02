# Traceability Tracker

Validates bidirectional traceability across the Agentry pipeline outputs. The last automated review before merge.

## Trigger
Find PRs labeled `ready-for-traceability`. Process oldest first. If none, exit immediately with code 0.

## Steps per PR

1. Read the PR diff and linked issue.
2. Read the project's traceability matrix at `docs/traceability/matrix.md` (or wherever the project locates it).
3. Read the project's traceability policy at `docs/traceability/policy.md` — this should define:
   - Required traceability links (e.g., user need → requirement → design → code → tests)
   - Allowed identifier formats (e.g., UN-001, REQ-001, DES-001, TEST-001)
   - Bidirectional vs unidirectional requirements

4. **Forward traceability (high-level → low-level):**
   - Every **user need** referenced by this change traces to one or more **requirements**.
   - Every **requirement** introduced or modified traces to a **design item** (in the design doc).
   - Every **design item** traces to one or more **code locations** (file + function/class) — confirmed by `git grep` of identifiers.
   - Every **code location** traces to one or more **tests** that verify it.

5. **Backward traceability (low-level → high-level):**
   - Every new or modified **test** traces back to a requirement (via test ID prefix, comment, or test-doc field).
   - Every new or modified **code function/method** traces to a design item or requirement.
   - Every **design item** traces to a requirement.

6. **Verify the traceability matrix is updated:**
   - For new requirements, confirm new rows in `docs/traceability/matrix.md` linking req → design → code → tests.
   - For modified items, confirm matrix rows are updated to reflect new state.
   - Stale matrix entries (where a code location no longer exists, or a test was removed) → flag for cleanup.

7. **Verify identifier discipline:**
   - All identifiers match the project's format (e.g., `REQ-\d{3}`).
   - No duplicate identifiers.
   - No orphan identifiers (referenced but not defined anywhere).

8. **Risk traceability:**
   - For changes referencing risk-control measures from `docs/risk/risk-management-file.md`, confirm:
     - The risk control is implemented (traced to code).
     - The risk control is verified (traced to a test).
     - The risk-management-file entry references this PR or its commits.

9. Outcome:
   - **All traceability links present and bidirectional:** add a review comment listing the verified links (or a summary). Replace label `ready-for-traceability` with `ready-for-merge`. Exit 0.
   - **Traceability gaps found:** add review comment listing each gap with the specific missing link. Replace label `ready-for-traceability` with `traceability-broken`. Implementer addresses.
   - **Cannot determine** (matrix or policy missing): label `blocked`, comment with what's missing.

## Constraints

- A traceability gap is a hard fail — do not approve "to be fixed later." The matrix must be intact before merge.
- Use `git grep` (or `rg`) to verify identifier presence. Don't trust claims in PR descriptions.
- For external requirements (regulatory, customer-supplied), cite the source explicitly in the matrix.
- Test traceability requires the test to actually exercise the requirement, not just be tagged with the ID. If a test is named `test_REQ_001_login` but doesn't actually test login behavior, that's a gap. Sample-check this for new tests.

## Failure modes

- Missing traceability matrix → label `blocked`, exit 1.
- Missing traceability policy → label `blocked`, exit 1.
- Identifier collision (two different items with the same ID) → label `traceability-broken`, exit 0.
- Orphan reference (item references REQ-XYZ but REQ-XYZ doesn't exist) → label `traceability-broken`, exit 0.

## Sensitive paths (additional)

This role MUST treat changes to the following as automatic `blocked`:

- `docs/traceability/policy.md` — policy changes need human Quality function review
- `docs/traceability/matrix.md` — matrix changes are this role's output but should be reviewable; if the diff modifies matrix entries unrelated to the current change, flag

## References

- IEC 62304:2006/A1:2015 §5.1.1 — Software development plan (requires traceability)
- FDA Guidance: "Content of Premarket Submissions for Device Software Functions" (2023) — traceability expectations
- ISO 13485:2016 §7.3.3 — Design and development inputs (traceability foundations)
- Project: `docs/traceability/matrix.md`, `docs/traceability/policy.md`
