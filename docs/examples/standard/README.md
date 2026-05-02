# Standard Example — Agentry roster

Standard 6-role roster for hobby projects, small teams, internal tools.

For regulated software (medical device, finance, etc.) see the [medical-device example](../medical-device/) instead.

---

## The 6 roles

| Role | Reads | Produces |
|------|-------|----------|
| **researcher** | repo + web | new issues for missing features (no label, awaiting Operator triage) |
| **architect** | issues `ready-for-design` | design doc on a branch + relabel `ready-for-implementation` |
| **implementer** | issues `ready-for-implementation` (or `tests-failed`) | code on a branch + relabel `ready-for-test` |
| **tester** | issues `ready-for-test` | runs tests; if green opens PR `ready-for-review`, if red `tests-failed` |
| **reviewer** | PRs `ready-for-review` | approves OR labels `blocked` |
| **release** | merged commits since last tag (daily) | tag + build + GitHub Release |

---

## Lifecycle

```
[new issue, no label]
        ↓ Operator labels `ready-for-design`
ready-for-design          → architect    → ready-for-implementation
ready-for-implementation  → implementer  → ready-for-test
ready-for-test            → tester       → ready-for-review (PR) | tests-failed
ready-for-review (PR)     → reviewer     → approve | blocked
[approved → GitHub auto-merge → merged]
        ↓ release (daily) → tag + build + Release if warranted
```

6 stages. 6 labels:

- `ready-for-design`
- `ready-for-implementation`
- `ready-for-test`
- `tests-failed`
- `ready-for-review`
- `blocked`

---

## Files in this example

```
docs/examples/standard/
├── README.md                              ← this file
├── .agentry/
│   └── config.yml                         ← 6-role declaration (copy to your target repo)
└── docs/
    └── ai/
        └── roles/
            ├── researcher.md              ← project-specific rule files
            ├── architect.md                  (these are the work specifics —
            ├── implementer.md                 the framework prompt only points
            ├── tester.md                      at them)
            ├── reviewer.md
            └── release.md
```

---

## Setup

1. Copy [`config.yml`](.agentry/config.yml) to `<your-target-repo>/.agentry/config.yml`
2. Edit `target_repo`, pick CLIs per role, tune timeouts
3. Copy each [`docs/ai/roles/*.md`](docs/ai/roles/) skeleton to `<your-target-repo>/docs/ai/roles/`
4. Edit each rule file with your project-specific instructions (file conventions, test commands, branch naming, etc.)
5. Customize `sensitive_paths` in `config.yml`
6. (Once v0.1 ships) `agentry doctor --target <repo> --init-labels` and `agentry target add --repo <repo>`

---

## How to extend

If your project needs more roles than the standard 6 (e.g., a `docs_writer` for OSS libraries, or a `security_reviewer` for web services), just add them to `agents:` in `config.yml` and write a corresponding `docs/ai/roles/<role>.md`. The framework spawns one forever-loop per declared role automatically — no special handling for "non-standard" roles.

For a worked-out extension example with 11 roles for IEC 62304 + ISO 13485 + FDA compliance, see the [medical-device example](../medical-device/).
