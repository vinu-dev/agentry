# Skynet Agentry

Status: **v0.0a (spec series complete, pre-implementation)**

Skynet Agentry is an **orchestrator + watchdog pair** that runs continuously on a single host, rents AI worker agents from cloud and local providers, and ships features end-to-end on any compliant target repository — Researcher, Architect, Implementer, Tester, PR Author, Reviewer, Release Engineer — with the Operator (the human running it) reserved for emergency overrides, policy changes, and onboarding new targets.

The agents are commodity workers (Claude, GPT-5, local Llama, whatever the Operator assigns). The orchestrator is the value.

> **The contractor metaphor.** Skynet Agentry is a contractor you hire once. You give it a job description (`.skynet/config.yml`). It hires gig workers from the AI spot market. It supervises them, fires the ones that don't work, calls in backups. You get a Discord ping when something interesting happens.

## Read in this order

1. **[`docs/architecture.md`](docs/architecture.md)** — full architecture and design (20 sections)
2. **[`docs/how-to-use.md`](docs/how-to-use.md)** — Operator's practical guide
3. **[`docs/v0.1-plan.md`](docs/v0.1-plan.md)** — concrete build plan for v0.1 (the first runnable version)
4. **[`COMPATIBILITY-SPEC.md`](COMPATIBILITY-SPEC.md)** — contract for target repositories
5. **[`schemas/skynet-config.schema.json`](schemas/skynet-config.schema.json)** — machine-checkable schema for `.skynet/config.yml`

Templates:

- **[`pipeline.example.toml`](pipeline.example.toml)** — per-host config template (copy to `~/.skynet/pipeline.local.toml`)
- **[`.env.example`](.env.example)** — secrets template (copy to `~/.skynet/.env`)

## What works today

Nothing runs yet. v0.0a is the spec series — design only, no code. The runtime ships in v0.1.

## What v0.1 will deliver

An Operator on a Linux or Windows host can:

- Install Skynet Agentry as a CLI tool (`uv tool install skynet-agentry`)
- Onboard any compliant target repository (`skynet init --target <repo>`)
- Configure per-role model assignments (Claude, GPT-5, Codex CLI subscription, local Llama, …) with fallback chains
- Watch features ship end-to-end without manual intervention
- Trust that no merge violated the configured path policies, no agent ran outside its workspace, and costs stayed within the daily cap

See [`docs/v0.1-plan.md`](docs/v0.1-plan.md) for the full build plan, module structure, and acceptance criteria.

## Two-repo model

```
Skynet Agentry (this repo)         Target repo
the framework                       (e.g. rpi-home-monitor)
─ orchestrator                  →   ─ .skynet/config.yml
─ watchdog                          ─ docs/ai/
─ agent runners                     ─ docs/ai/plans/   ← researcher writes
─ skynet CLI                        ─ docs/ai/designs/ ← architect writes

   installed once per host             cloned per task by orchestrator
```

The framework is generic. Targets declare conformance to the [Compatibility Spec](COMPATIBILITY-SPEC.md) and provide a `.skynet/config.yml` describing their build/test commands, sensitive paths, and per-role model assignments. Target repos never copy framework source.

## License

MIT — see [LICENSE](LICENSE).

## Status

Private and pre-release. While the framework is private:

```bash
uv tool install --from git+ssh://git@github.com/vinu-dev/skynet-agentry.git skynet-agentry
```
