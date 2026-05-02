# Skynet Agentry

Status: **v0.0a-final (spec complete, pre-implementation)**

Skynet Agentry is a small Python daemon that runs **6 forever-loops in parallel**, one per role. Each loop spawns an LLM CLI subprocess (Claude Code, Codex CLI, etc.) at its own interval, the subprocess does its job using the rules defined in the target repo, and exits. The daemon supervises: timeouts, restarts, Discord pings.

That's the whole product. ~200 lines of Python.

State lives in GitHub (issues, labels, PRs, branches). The daemon has no persistent state. Restart it any time.

## The 6 roles

| Role | Reads | Produces |
|------|-------|----------|
| **Researcher** | repo + web | new issues for missing features |
| **Architect** | issues `ready-for-design` | design docs, relabels `ready-for-implementation` |
| **Implementer** | issues `ready-for-implementation` | code on a branch, relabels `ready-for-test` |
| **Tester** | issues `ready-for-test` | runs tests; if green opens PR `ready-for-review`, if red `tests-failed` |
| **Reviewer** | PRs `ready-for-review` | approves OR `blocked` |
| **Release Engineer** | merged commits since last tag | tag + build + GitHub Release |

Each role gets its own model assignment. Operator picks: Claude for research, Codex for implementation, local Llama for review, etc.

## What target repos provide

A repo is "Skynet-ready" when it has:

```
target-repo/
├── .skynet/config.yml                ← agent assignments + timeouts
└── docs/ai/roles/
    ├── researcher.md                  ← project-specific instructions per role
    ├── architect.md
    ├── implementer.md
    ├── tester.md
    ├── reviewer.md
    └── release.md
```

Plus 6 GitHub labels (`ready-for-design`, `ready-for-implementation`, `ready-for-test`, `tests-failed`, `ready-for-review`, `blocked`) — created by `skynet doctor --init-labels`.

The framework prompts are generic ("read docs/ai/roles/X.md and follow it"). The actual work instructions live in the repo. Different repos can have different conventions.

## Read in this order

1. **[`docs/architecture.md`](docs/architecture.md)** — the lean design (~250 lines)
2. **[`docs/how-to-use.md`](docs/how-to-use.md)** — Operator's practical guide
3. **[`docs/v0.1-plan.md`](docs/v0.1-plan.md)** — concrete build plan (~weekend-sized)
4. **[`COMPATIBILITY-SPEC.md`](COMPATIBILITY-SPEC.md)** — what target repos must provide

Templates:

- **[`pipeline.example.toml`](pipeline.example.toml)** — per-host config template
- **[`.env.example`](.env.example)** — secrets template

## What works today

Nothing runs yet. v0.0a is the spec — design only, no code. The runtime ships in v0.1.

## Install (when v0.1 ships)

```bash
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
skynet --version
skynet service install                    # systemd or NSSM
```

Then configure a target repo with `.skynet/config.yml` + role rule files, and `skynet target add --repo <url>`.

## License

MIT — see [LICENSE](LICENSE).
