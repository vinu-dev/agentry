# Agentry

Status: **v0.0a-final (spec complete, pre-implementation)**

Agentry is a small Python daemon that runs **N forever-loops in parallel**, one per role declared by the target repo. Each loop spawns an LLM CLI subprocess (Claude Code, Codex CLI, etc.) at its own interval. The framework supplies a generic prompt encoding the parallel-pipeline pattern; the target repo supplies project-specific role rule files at `docs/ai/roles/<role>.md`. The agent does the work, exits. The daemon supervises: timeouts, restarts, Discord pings.

That's the whole product. ~200 lines of Python. **N is whatever the repo declares** — 6 for a hobby project, 11+ for a medical device project.

State lives in GitHub (issues, labels, PRs, branches). The daemon has no persistent state. Restart it any time.

## Common starter roster (6 roles)

| Role | Reads | Produces |
|------|-------|----------|
| **Researcher** | repo + web | new issues for missing features |
| **Architect** | issues `ready-for-design` | design docs, relabels `ready-for-implementation` |
| **Implementer** | issues `ready-for-implementation` | code on a branch, relabels `ready-for-test` |
| **Tester** | issues `ready-for-test` | runs tests; if green opens PR `ready-for-review`, if red `tests-failed` |
| **Reviewer** | PRs `ready-for-review` | approves OR `blocked` |
| **Release Engineer** | merged commits since last tag | tag + build + GitHub Release |

Each role gets its own model assignment. Operator picks: Claude for research, Codex for implementation, local Llama for review, etc.

## Extended roster — medical device (11 roles)

For regulated software (IEC 62304 + ISO 13485 + ISO 14971 + IEC 81001-5-1 + FDA 21 CFR 820), the roster grows to include:

- **risk_analyst** (ISO 14971)
- **code_reviewer** (functional review)
- **quality_reviewer** (ISO 13485 / IEC 62304 conformance)
- **cybersecurity_reviewer** (IEC 81001-5-1 + FDA cyber guidance)
- **regulatory_reviewer** (FDA 510(k) / 21 CFR 820)
- **traceability_tracker** (bidirectional req → design → code → tests)

Same framework, more threads. See [`docs/examples/medical-device/`](docs/examples/medical-device/) for a full config and rule files.

## What target repos provide

**Nothing — by default.** Agentry ships with best-practice defaults: the standard 6-role config and bundled rule files. Point Agentry at your repo and it runs with those defaults out of the box.

You only commit files in your target repo when you want to **override** a default:

```
target-repo/   (only the files you want to customize)
├── .agentry/config.yml                ← override CLIs / timeouts / roles (optional)
└── docs/ai/roles/                     ← override per-role instructions (optional, per file)
    ├── researcher.md
    ├── architect.md
    ├── implementer.md
    ├── tester.md
    ├── reviewer.md
    └── release.md
```

Most projects override one or two things (which CLI handles each role; project-specific test commands). The bundled defaults handle the rest.

The canonical default config and rule files are at [`docs/examples/standard/`](docs/examples/standard/) — that's exactly what gets copied into your target if you run `agentry init`.

GitHub labels are created automatically by `agentry doctor --init-labels`: `ready-for-design`, `ready-for-implementation`, `ready-for-test`, `tests-failed`, `ready-for-review`, `blocked`.

The framework prompts are generic ("read `docs/ai/roles/X.md` and follow it"). The actual work instructions live in the bundled rule files (or your overrides if you have them).

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

## Install (one-liner)

### Windows (PowerShell)

```powershell
iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install.ps1 | iex
```

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install.sh | bash
```

The installer is idempotent and installs everything Agentry needs:

- Python 3.11+ (only if missing)
- Node.js LTS (only if missing) — required for the LLM CLIs
- `agentry` itself (via `pipx` on Linux, `pip --user` on Windows)
- `claude` (Claude Code) and `codex` (OpenAI Codex CLI) via npm
- NSSM on Windows (only needed if you'll use `agentry service install`)
- `~/.agentry/` directory with template `.env` and `pipeline.local.toml`

The installer does **not** do anything that requires your credentials:

- It does not run `claude login` / `codex login` (those open your browser)
- It does not fill in API keys / Discord webhook / GitHub PAT in your `.env`

Those steps are listed at the end of the install run.

### After install

```bash
claude login                                  # opens browser, links your subscription
codex login                                   # same for ChatGPT
$EDITOR ~/.agentry/.env                       # fill in GITHUB_TOKEN + DISCORD_WEBHOOK_URL

cd <your-target-repo>
agentry doctor --init-labels                  # creates the 6 GitHub labels in the target
agentry start                                  # foreground (Ctrl-C to stop)
# OR
agentry service install                       # always-on (systemd / NSSM)
```

Then configure the target with `.agentry/config.yml` + role rule files (or use the bundled defaults), and `agentry target add --repo <url>` if running with the service.

## License

**AGPL-3.0** — see [LICENSE](LICENSE).

This is intentional copyleft. If you fork Agentry, modify it, and run it
as a service to others (including running it inside your company on private
projects you don't open), you must release the source of your modified version
under AGPL-3.0 as well.

### Commercial license

The AGPL terms are not friendly to closed-source commercial use. If you want
to use Agentry inside a proprietary product or service without the
AGPL obligations, a commercial license is available — contact
[@vinu-dev](https://github.com/vinu-dev).
