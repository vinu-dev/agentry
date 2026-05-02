# Medical Device Example — Agentry roster

This example shows how a target repository for medical device software can declare an extended Agentry roster with specialized review roles for regulatory compliance.

The example is **documentation only** — these files describe what a medical device repo's `.agentry/config.yml` and `docs/ai/roles/*.md` would look like. Copy and adapt to your actual medical device project.

---

## Why an extended roster

Medical device software development under FDA / IEC / ISO regimes has more required review stages than a hobby project:

- **Risk management** is mandatory and continuous (ISO 14971)
- **Software safety classification** dictates verification rigor (IEC 62304 §4.3)
- **Cybersecurity** is now required for FDA submission (IEC 81001-5-1, FDA cyber guidance)
- **Quality management** must be auditable (ISO 13485)
- **Traceability** between requirements, design, code, and tests is non-negotiable

Each of these can be its own role in the Agentry roster.

---

## The 11-role roster

| Role | Concern | Standard reference |
|------|---------|-------------------|
| `researcher` | New feature ideas | — |
| `risk_analyst` | Risk file (ISO 14971) updates per new feature | ISO 14971 |
| `architect` | Software architectural design | IEC 62304 §5.3 |
| `implementer` | Software detailed design + unit implementation | IEC 62304 §5.4–5.5 |
| `tester` | Software unit/integration/system testing | IEC 62304 §5.5–5.7 |
| `code_reviewer` | Functional code review | IEC 62304 §5.5.4 |
| `quality_reviewer` | ISO 13485 / IEC 62304 conformance | ISO 13485, IEC 62304 |
| `cybersecurity_reviewer` | Threat modeling, SBOM, vuln assessment | IEC 81001-5-1, FDA Cyber |
| `regulatory_reviewer` | FDA submission impact, 21 CFR 820 compliance | FDA 21 CFR 820, 510(k) |
| `traceability_tracker` | Bidirectional req → design → code → tests | IEC 62304 §5.1.1 |
| `release` | Version + tag + Design History File update + GitHub Release | ISO 13485 §7.5.3 |

11 roles. Each runs in its own forever-loop. Each has its own `cli` and timeouts in `.agentry/config.yml`. Each has its own rule file in `docs/ai/roles/`.

---

## Lifecycle

```
[new issue, no label]
        ↓ Operator labels `ready-for-risk-analysis`
ready-for-risk-analysis     → risk_analyst         → ready-for-design
ready-for-design            → architect            → ready-for-implementation
ready-for-implementation    → implementer          → ready-for-test
ready-for-test              → tester               → ready-for-code-review | tests-failed
ready-for-code-review       → code_reviewer        → ready-for-quality-review | review-failed
ready-for-quality-review    → quality_reviewer     → ready-for-cyber-review | quality-issues
ready-for-cyber-review      → cybersecurity_review → ready-for-regulatory-review | cyber-issues
ready-for-regulatory-review → regulatory_reviewer  → ready-for-traceability | regulatory-issues
ready-for-traceability      → traceability_tracker → ready-for-merge | traceability-broken
ready-for-merge             → GitHub auto-merge
[merged]
        ↓ release_engineer (daily) → tag + DHF update + Release
```

11 stages. Any failure label (e.g., `quality-issues`) routes back to `ready-for-implementation` for the implementer to fix and re-trigger the chain.

---

## Files in this example

```
docs/examples/medical-device/
├── README.md                                  ← this file
├── .agentry/
│   └── config.yml                             ← 11-role declaration
└── docs/
    └── ai/
        └── roles/
            ├── risk_analyst.md                ← ISO 14971 risk analysis
            ├── quality_reviewer.md            ← ISO 13485 / IEC 62304 conformance
            ├── cybersecurity_reviewer.md      ← IEC 81001-5-1 / FDA cyber
            ├── regulatory_reviewer.md         ← FDA 510(k) / 21 CFR 820
            └── traceability_tracker.md        ← bidirectional traceability
```

The standard 6 roles (`researcher`, `architect`, `implementer`, `tester`, `code_reviewer`, `release`) are not duplicated here — those rule files are project-specific and not unique to medical device development. Use the generic templates from `agentry init` and adapt.

---

## Setup

1. Run `agentry init --template medical-device` in your medical device repo
2. Edit `.agentry/config.yml` to set models per role (consider Opus for `quality_reviewer`, `regulatory_reviewer`, `traceability_tracker` — they need long context and careful reasoning)
3. Customize each `docs/ai/roles/*.md` rule file to your specific Quality Manual, Design History File location, applicable standards, etc.
4. `agentry doctor --target <repo> --init-labels`
5. `agentry target add --repo <repo>`

---

## Important caveats

This example is **starting-point documentation, not a regulatory template**. You are responsible for:

- Verifying that the rule files reflect your actual Quality Management System
- Ensuring AI-generated content (designs, reviews, traceability) meets your verification + validation requirements before regulatory submission
- Auditing whether autonomous AI workflows are acceptable under your QMS — many MDRs require specific human-in-the-loop steps that this example does not encode
- Treating Agentry's outputs as **drafts for expert review**, not as final regulatory artifacts

The framework is a productivity aid. Compliance responsibility stays with the organization deploying it.
