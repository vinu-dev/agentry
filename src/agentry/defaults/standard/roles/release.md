# Release

Cuts releases on a schedule. Runs daily by default.

## Trigger
Cron — runs every `interval_min` (default 1440 = daily).

## Steps per invocation

1. Get the most recent git tag: `git describe --tags --abbrev=0`.
2. Get commits since that tag: `git log <last-tag>..main --oneline`.
3. Decide whether a release is warranted:
   - **Project's heuristic** — define your own:
     - "release if 5+ user-visible commits"
     - "release every Friday regardless"
     - "release only when a `release-now` label is set on a milestone"
4. If no release: exit 0.
5. If yes:
   - Determine new version (`semver` bump based on conventional-commits, manual rule, or whatever the project uses)
   - Update version files (e.g., `pyproject.toml`, `package.json`, `version.py`)
   - Generate changelog from commits between tags
   - Build artifacts (run `./scripts/build.sh` or whatever the project uses)
   - Sign artifacts if applicable (using `SWU_SIGNING_KEY_PATH` env var, etc.)
   - Tag the release: `git tag -a v<new-version> -m "Release v<new-version>"`
   - Push tag: `git push origin v<new-version>`
   - Create GitHub Release: `gh release create v<new-version> --notes-file <changelog-path> <artifacts...>`
6. Exit with code 0.

## Constraints

- Don't release if `main` is not at a clean state (uncommitted changes, conflicts).
- Don't release if any required secret env var is missing — exit 0 with a clear log message instead of failing partway.
- Use the project's existing build pipeline; don't invent a parallel one.

## Failure modes

- Build fails → log the error, do not tag or release, exit 1 (will retry next day).
- Signing fails → exit 1.
- GitHub Release API errors → exit 1; tag is already pushed, just need to retry the Release create step.

## Project-specific bits to fill in

- Versioning rule (semver-conventional-commits, manual, calver)
- Build command(s)
- Artifact paths
- Changelog format
- Whether to sign artifacts and how
- Pre-release vs. stable channel logic
