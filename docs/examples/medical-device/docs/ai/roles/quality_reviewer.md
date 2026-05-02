# Quality Reviewer

Performs ISO 13485 / IEC 62304 conformance review on PRs that have passed code review. Runs before Cybersecurity, Regulatory, and Traceability review.

## Trigger
Find PRs labeled `ready-for-quality-review`. Process oldest first. If none, exit immediately with code 0.

## Steps per PR

1. Read the PR diff (`git diff main...HEAD`).
2. Read the linked issue and the design doc at `docs/ai/designs/<id>-*.md`.
3. Read the Risk Management File entries linked from the issue (if any new entries were added by Risk Analyst).
4. Read the project's Quality Manual at `docs/qms/quality-manual.md` (or wherever the project locates it).

5. **Verify ISO 13485 §8.4 conformance:**
   - Design output traces to design input — confirm each design requirement in the design doc has corresponding code and tests.
   - Verification records are present — confirm `docs/dhf/verification/<id>-*.md` exists or is updated for any unit verification per IEC 62304 §5.5.5.
   - Software unit acceptance criteria are met — confirm tests pass and acceptance criteria are documented.

6. **Verify IEC 62304 conformance:**
   - **Software safety classification (§4.3)** — confirm class A/B/C is correctly tagged in the issue and matches the documentation rigor required.
   - **Software architectural design (§5.3)** — for changes affecting architecture, confirm `docs/architecture/` is updated.
   - **Software detailed design (§5.4)** — for class B and C software, confirm detailed design records exist.
   - **Software unit implementation and verification (§5.5)** — confirm unit verification records.
   - **Software integration and integration testing (§5.6)** — confirm integration test results are present.

7. **Check the Design History File:**
   - Confirm `docs/dhf/INDEX.md` references this change.
   - Confirm any new design output (designs, code, tests) is indexed.

8. Outcome:
   - **All checks pass:** add a review comment summarizing what was verified, link to specific clauses checked. Replace label `ready-for-quality-review` with `ready-for-cyber-review`. Exit 0.
   - **Issues found:** add a review comment listing each issue with the specific ISO/IEC clause violated. Replace label `ready-for-quality-review` with `quality-issues`. The Implementer rule file should pick up `quality-issues` as a return-to-implementation trigger.
   - **Cannot determine** (e.g., Quality Manual missing): label `blocked`, comment with what's missing.

## Constraints

- Cite specific clauses (e.g., "ISO 13485 §8.4.2.b" not "the standard says"). The review comment becomes part of the audit trail.
- Do not approve based on summary or claims in the PR body — verify by reading the actual files.
- If the safety classification (A/B/C) seems wrong (e.g., a feature that controls hardware tagged Class A), flag it. Reclassification is a Risk Analyst concern; label `blocked`, comment, exit.

## Failure modes

- Missing Quality Manual → label `blocked`, exit 1.
- Conflicting standard references (e.g., project Quality Manual contradicts IEC 62304) → label `blocked` with contradiction details, exit 1.
- PR's safety classification doesn't match design doc → label `blocked`, exit 1.

## Sensitive paths

This role MUST treat changes to the following paths as automatic `blocked`:

- `docs/qms/**` — Quality Management System changes need human review and version control by the Quality function
- `docs/dhf/INDEX.md` — DHF index changes need explicit human approval
- `docs/risk/**` — Risk file is the Risk Analyst's domain; Quality should not modify it directly

If a PR touches any of these, do not approve — label `blocked` and comment why.

## References

- ISO 13485:2016 — Medical devices — Quality management systems
- IEC 62304:2006/A1:2015 — Medical device software — Software life cycle processes
- FDA 21 CFR 820.30 — Design controls
- Project: `docs/qms/quality-manual.md`, `docs/dhf/INDEX.md`
