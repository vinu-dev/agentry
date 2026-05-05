# Release Guide

This guide describes how Agentry itself is released.

## Versioning

Agentry uses `pyproject.toml` as the package version source. Release tags use
the same version with a `v` prefix, for example `v0.1.2`.

Target repositories pin Agentry by Git tag or commit in:

```text
agentry/start.ps1
agentry/start.sh
```

## Release Checklist

1. Update release-facing docs:
   - `README.md`
   - `CHANGELOG.md`
   - `docs/how-to-use.md`
   - `docs/design.md`
   - `docs/architecture.md`
   - `docs/watchdog-and-dashboard.md`
   - `COMPATIBILITY-SPEC.md`
   - example docs under `docs/examples/`
2. Run validation:

   ```bash
   python -m compileall -q src tests
   python -m pytest tests -q
   python -m ruff check src tests
   python -m build
   ```

3. Merge the release docs/code PR to `main`.
4. Create and push the tag:

   ```bash
   git tag -a v0.1.2 -m "Agentry v0.1.2"
   git push origin v0.1.2
   ```

5. Create the GitHub Release from the tag and attach built artifacts from
   `dist/` when available.

## Target Upgrade After A Release

For an existing target repo:

1. Stop Agentry in that target.
2. Update the pinned ref in `agentry/start.ps1` and `agentry/start.sh` to the
   new release tag or commit.
3. Commit that pin update in the target repo.
4. Refresh the local venv:

   Windows:

   ```powershell
   $env:AGENTRY_FORCE_INSTALL = "1"
   .\agentry\start.ps1 status --target .
   Remove-Item Env:\AGENTRY_FORCE_INSTALL
   ```

   Linux:

   ```bash
   AGENTRY_FORCE_INSTALL=1 ./agentry/start.sh status --target .
   ```

5. Run:

   Windows:

   ```powershell
   .\agentry\start.ps1 doctor --target . --init-labels
   ```

   Linux:

   ```bash
   ./agentry/start.sh doctor --target . --init-labels
   ```

6. Start Agentry when ready.
