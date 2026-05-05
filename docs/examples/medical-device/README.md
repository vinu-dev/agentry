# Medical Device Example - Agentry Roster

This example shows how a target repository for medical device software can use
Agentry with specialized review roles for regulated development.

It is documentation and starter material, not a regulatory template. Copy the
pattern into a real target repo, then adapt it to your Quality Management
System, Design History File, risk process, and validation evidence.

For regulated targets, start from a released Agentry tag such as `v0.1.2` and
pin that tag in the generated start scripts. Add controlled documents,
generated traceability files, release files, and risk/security records to
`merge_sensitive_paths` so overlapping PRs move through review one at a time.
Keep `context.work_packets` enabled and use `trigger.pr_check_gate: settled` on
reviewer-style PR roles so expensive compliance reviewers do not launch while
all matching PR checks are still pending. Work packets name one `Selected
Candidate`, which keeps each compliance role focused on one auditable item per
cycle.

## Why An Extended Roster

Medical device software has more gates than a typical hobby project:

- risk management is mandatory and continuous
- software safety classification affects verification rigor
- cybersecurity evidence is expected
- quality management needs audit-ready records
- requirements, design, code, tests, risk, and release records need traceability

Each concern can be represented as a role in `agentry/config.yml`.

## Example Roles

| Role | Concern |
|------|---------|
| `researcher` | candidate issues, complaints, standards changes |
| `risk_analyst` | ISO 14971 risk impact |
| `architect` | software architecture and design |
| `implementer` | implementation and unit tests |
| `tester` | verification evidence |
| `code_reviewer` | functional code review |
| `quality_reviewer` | QMS and process conformance |
| `cybersecurity_reviewer` | threat model, SBOM, vulnerability impact |
| `regulatory_reviewer` | submission and regulatory impact |
| `traceability_tracker` | bidirectional traceability |
| `release` | release records, tags, artifacts |

## Lifecycle

```text
needs-risk
  -> risk_analyst
  -> ready-for-design
  -> architect
  -> ready-for-implementation
  -> implementer
  -> ready-for-test
  -> tester
  -> pr-open
  -> ready-for-code-review
  -> code_reviewer
  -> ready-for-quality-review
  -> quality_reviewer
  -> ready-for-cyber-review
  -> cybersecurity_reviewer
  -> ready-for-regulatory-review
  -> regulatory_reviewer
  -> ready-for-traceability
  -> traceability_tracker
  -> ready-for-merge
```

Failure labels should route back to implementation or human triage, depending
on the target's QMS.

## Files In This Example

```text
docs/examples/medical-device/
  README.md
  agentry/
    config.yml
  docs/ai/roles/
    risk_analyst.md
    quality_reviewer.md
    cybersecurity_reviewer.md
    regulatory_reviewer.md
    traceability_tracker.md
```

The standard roles are not duplicated here. Start from the standard target
layout, then add these extra role files and config entries.

## Recommended Setup

1. Run the normal `scripts/add-to-target.*` flow in the target repo.
2. Copy/adapt this example's extra role entries into `agentry/config.yml`.
3. Copy/adapt the extra role files into `docs/ai/roles/`.
4. Add every non-standard workflow label to the config `labels:` mapping so
   `agentry doctor --target . --init-labels` can create them.
5. Use `agentry/start.ps1 gui --target .` or `./agentry/start.sh gui --target .`
   to choose `manual`, `pipeline`, or `autonomous` mode and model profile.
6. Keep Researcher disabled until the regulated backlog creation policy is
   explicit and approved.

## Important Caveats

This example is a productivity aid, not compliance advice. You remain
responsible for:

- making role rules match your actual QMS and regulatory strategy
- verifying AI-generated records before relying on them
- defining required human approvals and sign-offs
- deciding whether autonomous issue creation is acceptable
- ensuring release artifacts and traceability evidence are reviewed by qualified
  people

Agentry can coordinate the work. Compliance responsibility stays with the
organization deploying it.
