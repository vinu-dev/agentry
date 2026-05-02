"""Click-based CLI for Agentry.

Subcommands (v0.1):
  agentry --version
  agentry doctor    [--target PATH]
  agentry init      [--template standard|medical-device]
  agentry start     [--target PATH]
  agentry status    [--target PATH]
  agentry service install     [--target PATH]
  agentry service uninstall

Out of scope for v0.1: pause/resume/kick/replay/quarantine/unlock — all of
those need IPC between the running daemon and the CLI. Operators stop with
the OS service manager (systemctl / nssm stop) for now.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import sys
from importlib.resources import files
from pathlib import Path

import click
from pydantic import ValidationError

from agentry.config import (
    bundled_default_config_path,
    bundled_default_role_path,
    load_host_config,
    load_target_config,
    role_rule_path,
)
from agentry.github import gh_available, init_labels, list_labels, repo_exists
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
    is_flag=True,
    help="Create the standard labels in the target repo on GitHub.",
)
def doctor(target_path: Path, init_labels: bool) -> None:  # noqa: PLR0915
    """Validate that the target repo + host config + CLIs are operable."""
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

    using_bundled = not (target_path / ".agentry" / "config.yml").is_file()
    if using_bundled:
        click.secho("INFO  using bundled standard 6-role config (no .agentry/config.yml in target)", fg="cyan")
    else:
        click.secho("OK    .agentry/config.yml present and valid", fg="green")

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

    # 4. Host config.
    try:
        host_config = load_host_config()
        click.secho(f"OK    host config loaded; state_dir={host_config.state_dir}", fg="green")
    except (ValidationError, ValueError) as e:
        click.secho(f"FAIL  host config invalid:\n{e}", fg="red")
        ok = False
        host_config = None  # type: ignore[assignment]

    # 5. gh CLI / target repo.
    if gh_available():
        if repo_exists(target_config.target_repo):
            click.secho(f"OK    gh sees {target_config.target_repo}", fg="green")
        else:
            click.secho(
                f"WARN  gh cannot reach {target_config.target_repo}; check auth + repo name",
                fg="yellow",
            )
    else:
        click.secho("WARN  gh CLI not on PATH; agents won't be able to manage labels/PRs", fg="yellow")

    # 6. Optional --init-labels.
    if init_labels:
        if not gh_available():
            click.secho("FAIL  cannot init labels: gh not on PATH", fg="red")
            sys.exit(2)
        existing = list_labels(target_config.target_repo)
        from agentry.github import STANDARD_LABELS

        for name in STANDARD_LABELS:
            if name in existing:
                click.secho(f"OK    label {name!r} already present", fg="green")
        results = init_labels(target_config.target_repo)
        for name, success in results.items():
            color = "green" if success else "red"
            click.secho(f"{'OK   ' if success else 'FAIL '} create label {name!r}", fg=color)

    click.secho("\n=> RESULT: PASS" if ok else "\n=> RESULT: FAIL", fg="green" if ok else "red")
    sys.exit(0 if ok else 2)


# -----------------------------------------------------------------------------
# init
# -----------------------------------------------------------------------------


@cli.command()
@click.option(
    "--template",
    type=click.Choice(["standard", "medical-device"]),
    default="standard",
    help="Which bundled template to copy.",
)
@click.option(
    "--target",
    "target_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Target repo directory. Defaults to the current directory.",
)
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(template: str, target_path: Path, force: bool) -> None:
    """Copy the bundled template into the target repo."""
    target_path = target_path.resolve()
    if not target_path.exists():
        click.secho(f"target path does not exist: {target_path}", fg="red")
        sys.exit(2)

    template_pkg = "agentry.defaults.standard"
    if template == "medical-device":
        # Medical-device template lives in docs/examples/, not bundled into
        # the package today. Operators can copy it manually until v0.2.
        click.secho(
            "medical-device template is documentation-only in v0.1.\n"
            "Copy from https://github.com/vinu-dev/agentry/tree/main/docs/examples/medical-device manually.",
            fg="yellow",
        )
        sys.exit(1)

    src_root = files(template_pkg)
    written: list[Path] = []
    for src in src_root.iterdir():
        # Walk the template, mirroring its structure into target_path.
        _copy_resource_into(src, target_path, src_root, force=force, written=written)

    click.secho(f"\nWrote {len(written)} file(s) into {target_path}", fg="green")
    for p in written:
        click.echo(f"  {p.relative_to(target_path)}")


def _copy_resource_into(src, target_root: Path, root, *, force: bool, written: list[Path]) -> None:
    """Recursively copy a bundled resource into the target directory tree."""
    if src.is_dir():
        for child in src.iterdir():
            _copy_resource_into(child, target_root, root, force=force, written=written)
        return

    rel = Path(str(src)).relative_to(str(root))
    # The standard template ships .agentry/config.yml + roles/*.md.
    # We want them at:
    #   <target>/.agentry/config.yml
    #   <target>/docs/ai/roles/<role>.md
    # The bundle on disk is laid out as:
    #   defaults/standard/config.yml
    #   defaults/standard/roles/<role>.md
    if rel.name == "config.yml" and len(rel.parts) == 1:
        dst = target_root / ".agentry" / "config.yml"
    elif rel.parts[0] == "roles":
        dst = target_root / "docs" / "ai" / "roles" / Path(*rel.parts[1:])
    else:
        # Unknown bundled file — copy verbatim as a sibling of .agentry/.
        dst = target_root / rel

    if dst.exists() and not force:
        click.secho(f"SKIP  {dst} already exists (use --force to overwrite)", fg="yellow")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    written.append(dst)


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
    """Start the orchestrator in foreground (use service install for daemon mode)."""
    target_path = target_path.resolve()
    target_config = load_target_config(target_path)
    host_config = load_host_config()

    webhook_env = host_config.discord_webhook_env
    webhook_url = os.environ.get(webhook_env) or None
    if not webhook_url:
        click.secho(
            f"WARN  {webhook_env} not set; Discord notifications will be dropped",
            fg="yellow",
        )

    notifier = DiscordNotifier(
        webhook_url=webhook_url, flush_seconds=host_config.batch_notify_seconds
    )
    notifier.start()

    orch = Orchestrator(
        target_config=target_config,
        host_config=host_config,
        target_path=target_path,
        notifier=notifier,
    )

    # Set up SIGTERM/SIGINT handlers in the main thread.
    def handle_signal(signum: int, _frame) -> None:
        logger.info("received signal %d; shutting down", signum)
        orch.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):
            # Some platforms don't allow setting signal handlers from
            # non-main threads. We're in the main thread here so this
            # should rarely fail, but be tolerant just in case.
            pass

    click.secho(
        f"agentry started for {target_config.target_repo} ({len(target_config.agents)} roles)",
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
    """Show recent orchestrator activity by reading log files.

    v0.1 status is read-only via the filesystem; for live IPC we'd need a
    socket and a richer protocol — deferred.
    """
    target_path = target_path.resolve()
    target_config = load_target_config(target_path)
    host_config = load_host_config()
    log_root = host_config.state_dir / "logs"

    click.echo(f"target: {target_config.target_repo}")
    click.echo(f"state_dir: {host_config.state_dir}")
    click.echo(f"roles ({len(target_config.agents)}):")

    for role in sorted(target_config.agents):
        role_logs = log_root / role
        if not role_logs.is_dir():
            click.secho(f"  {role}: no log dir yet", fg="yellow")
            continue
        latest = sorted(role_logs.glob("*.log"))[-3:] if any(role_logs.iterdir()) else []
        if not latest:
            click.secho(f"  {role}: no runs yet", fg="yellow")
            continue
        click.echo(f"  {role}: {len(list(role_logs.glob('*.log')))} runs total")
        for p in latest:
            size = p.stat().st_size
            click.echo(f"    └─ {p.name} ({size} bytes)")


# -----------------------------------------------------------------------------
# service
# -----------------------------------------------------------------------------


@cli.group()
def service() -> None:
    """Install/uninstall the always-on service (systemd / NSSM)."""


@service.command("install")
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
)
def service_install(target_path: Path) -> None:
    """Register the orchestrator as a system service."""
    target_path = target_path.resolve()
    if sys.platform == "win32":
        from agentry.platform import windows as plat
    else:
        from agentry.platform import linux as plat

    plat.install_service(target_path)
    click.secho(f"service installed for target {target_path}", fg="green")


@service.command("uninstall")
def service_uninstall() -> None:
    """Stop and remove the system service."""
    if sys.platform == "win32":
        from agentry.platform import windows as plat
    else:
        from agentry.platform import linux as plat

    plat.uninstall_service()
    click.secho("service uninstalled", fg="green")


# -----------------------------------------------------------------------------
# default-paths (utility — show where bundled defaults live)
# -----------------------------------------------------------------------------


@cli.command("default-paths")
def default_paths() -> None:
    """Print the on-disk paths of the bundled default config + role files."""
    click.echo(f"config:    {bundled_default_config_path()}")
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
