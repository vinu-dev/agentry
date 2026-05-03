"""Click-based CLI for Agentry.

After this refactor the CLI surface is intentionally small. ``agentry`` runs
inside the target repo's local venv (created by ``agentry/start.{ps1,sh}``);
the daemon-mode service installer is gone.

Subcommands (v0.1):
  agentry --version
  agentry doctor    [--target PATH]
  agentry start     [--target PATH]
  agentry status    [--target PATH]
  agentry default-paths
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import click
from pydantic import ValidationError

from agentry.config import (
    bundled_default_config_path,
    bundled_default_role_path,
    load_target_config,
    load_target_env,
    role_rule_path,
    target_config_file,
    target_env_file,
    target_logs_dir,
)
from agentry.github import gh_available, list_labels, repo_exists
from agentry.github import init_labels as gh_init_labels
from agentry.notify import DiscordNotifier
from agentry.orchestrator import Orchestrator
from agentry.version import __version__

logger = logging.getLogger("agentry")


@click.group(invoke_without_command=False)
@click.version_option(__version__, prog_name="agentry")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging (DEBUG level).")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Agentry — autonomous multi-agent product organization."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)


# -----------------------------------------------------------------------------
# doctor
# -----------------------------------------------------------------------------


@cli.command()
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Target repo directory. Defaults to the current directory.",
)
@click.option(
    "--init-labels",
    "init_labels_flag",
    is_flag=True,
    help="Create the standard labels in the target repo on GitHub.",
)
def doctor(target_path: Path, init_labels_flag: bool) -> None:
    """Validate that the target repo + secrets + CLIs are operable."""
    target_path = target_path.resolve()
    load_target_env(target_path)
    ok = True

    # 1. Target config (or bundled default).
    try:
        target_config = load_target_config(target_path)
    except FileNotFoundError as e:
        click.secho(f"FAIL  target path: {e}", fg="red")
        sys.exit(2)
    except (ValidationError, ValueError) as e:
        click.secho(f"FAIL  config invalid:\n{e}", fg="red")
        sys.exit(2)

    using_bundled = not target_config_file(target_path).is_file()
    if using_bundled:
        click.secho(
            "INFO  no agentry/config.yml in target; using bundled standard 6-role config",
            fg="cyan",
        )
        click.secho(
            "      run scripts/add-to-target to drop a config + role file skeletons into this repo",
            fg="cyan",
        )
    else:
        click.secho(f"OK    {target_config_file(target_path)} present and valid", fg="green")

    # 2. Role rule files.
    for role in target_config.agents:
        rule = role_rule_path(target_path, role)
        if rule.is_file():
            target_specific = (target_path / "docs" / "ai" / "roles" / f"{role}.md").is_file()
            tag = "(target)" if target_specific else "(bundled)"
            click.secho(f"OK    role {role} rule file {tag}: {rule}", fg="green")
        else:
            click.secho(f"FAIL  role {role}: no rule file at {rule}", fg="red")
            ok = False

    # 3. CLIs on PATH.
    for role, cfg in target_config.agents.items():
        if shutil.which(cfg.cli):
            click.secho(f"OK    role {role} cli {cfg.cli!r} found on PATH", fg="green")
        else:
            click.secho(
                f"WARN  role {role} cli {cfg.cli!r} not on PATH; that role will fail to spawn",
                fg="yellow",
            )

    # 4. Secrets file.
    env_path = target_env_file(target_path)
    token_present = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    gh_on_path = gh_available()
    gh_repo_ok = gh_on_path and repo_exists(target_config.target_repo)

    if env_path.is_file():
        click.secho(f"OK    {env_path} present", fg="green")
    else:
        click.secho(
            f"WARN  no secrets file at {env_path}; copy {env_path.with_suffix('.example')} "
            "and fill in GITHUB_TOKEN",
            fg="yellow",
        )
    if token_present:
        click.secho("OK    GitHub auth: GITHUB_TOKEN present", fg="green")
    elif gh_repo_ok:
        click.secho("OK    GitHub auth: gh can reach target repo", fg="green")
    else:
        click.secho(
            "FAIL  GitHub auth unavailable; set GITHUB_TOKEN in agentry/.env "
            "or authenticate gh for this repo",
            fg="red",
        )
        ok = False

    # 5. gh CLI / target repo.
    if gh_on_path:
        if gh_repo_ok:
            click.secho(f"OK    gh sees {target_config.target_repo}", fg="green")
        else:
            click.secho(
                f"WARN  gh cannot reach {target_config.target_repo}; check auth + repo name",
                fg="yellow",
            )
    else:
        click.secho(
            "WARN  gh CLI not on PATH; agents won't be able to manage labels/PRs",
            fg="yellow",
        )

    # 6. Optional --init-labels.
    if init_labels_flag:
        if not gh_available():
            click.secho("FAIL  cannot init labels: gh not on PATH", fg="red")
            sys.exit(2)
        existing = list_labels(target_config.target_repo)
        from agentry.github import STANDARD_LABELS

        labels_to_create = STANDARD_LABELS.copy()
        for name in target_config.labels.values():
            labels_to_create.setdefault(name, "ededed")

        for name in labels_to_create:
            if name in existing:
                click.secho(f"OK    label {name!r} already present", fg="green")
        results = gh_init_labels(target_config.target_repo, labels_to_create)
        for name, success in results.items():
            color = "green" if success else "red"
            click.secho(f"{'OK   ' if success else 'FAIL '} create label {name!r}", fg=color)

    click.secho("\n=> RESULT: PASS" if ok else "\n=> RESULT: FAIL", fg="green" if ok else "red")
    sys.exit(0 if ok else 2)


# -----------------------------------------------------------------------------
# start
# -----------------------------------------------------------------------------


@cli.command()
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Target repo directory. Defaults to the current directory.",
)
def start(target_path: Path) -> None:
    """Start the orchestrator in foreground.

    Runs forever until you Ctrl-C or close the terminal. There's no service
    install path — every reboot, run ``agentry/start.ps1`` (or ``.sh``) again
    from inside the target repo.
    """
    target_path = target_path.resolve()
    load_target_env(target_path)
    target_config = load_target_config(target_path)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL") or None
    if not webhook_url:
        click.secho(
            "INFO  DISCORD_WEBHOOK_URL not set; events go to "
            f"{target_logs_dir(target_path)} only",
            fg="cyan",
        )

    notifier = DiscordNotifier(webhook_url=webhook_url, flush_seconds=60)
    notifier.start()

    orch = Orchestrator(
        target_config=target_config,
        target_path=target_path,
        notifier=notifier,
    )

    def handle_signal(signum: int, _frame) -> None:
        logger.info("received signal %d; shutting down", signum)
        orch.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):
            pass

    click.secho(
        f"agentry started for {target_config.target_repo} ({len(target_config.agents)} roles)\n"
        f"  target: {target_path}\n"
        f"  logs:   {target_logs_dir(target_path)}\n"
        "press Ctrl-C to stop.",
        fg="green",
    )
    orch.start()
    orch.wait()
    notifier.stop()
    click.secho("agentry stopped cleanly", fg="green")


# -----------------------------------------------------------------------------
# status
# -----------------------------------------------------------------------------


@cli.command()
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
)
def status(target_path: Path) -> None:
    """Show recent orchestrator activity by reading log files."""
    target_path = target_path.resolve()
    target_config = load_target_config(target_path)
    log_root = target_logs_dir(target_path)

    click.echo(f"target:    {target_config.target_repo}")
    click.echo(f"path:      {target_path}")
    click.echo(f"logs:      {log_root}")
    click.echo(f"roles ({len(target_config.agents)}):")

    for role in sorted(target_config.agents):
        role_logs = log_root / role
        if not role_logs.is_dir():
            click.secho(f"  {role}: no log dir yet", fg="yellow")
            continue
        all_logs = sorted(role_logs.glob("*.log"))
        if not all_logs:
            click.secho(f"  {role}: no runs yet", fg="yellow")
            continue
        latest = all_logs[-3:]
        click.echo(f"  {role}: {len(all_logs)} runs total")
        for p in latest:
            size = p.stat().st_size
            click.echo(f"    └─ {p.name} ({size} bytes)")


# -----------------------------------------------------------------------------
# default-paths (utility)
# -----------------------------------------------------------------------------


@cli.command("default-paths")
def default_paths() -> None:
    """Print the on-disk paths of the bundled default config + role files."""
    click.echo(f"bundled config:    {bundled_default_config_path()}")
    for role in (
        "researcher",
        "architect",
        "implementer",
        "tester",
        "reviewer",
        "release",
    ):
        click.echo(f"  {role:14s} {bundled_default_role_path(role)}")


__all__ = ["cli"]
