"""Click-based CLI for Agentry.

After this refactor the CLI surface is intentionally small. ``agentry`` runs
inside the target repo's local venv (created by ``agentry/start.{ps1,sh}``);
the daemon-mode service installer is gone.

Subcommands (v0.1):
  agentry --version
  agentry doctor    [--target PATH]
  agentry start     [--target PATH]
  agentry status    [--target PATH]
  agentry stop      [ROLE|--all] [--target PATH]
  agentry configure [--target PATH] [--gui]
  agentry gui       [--target PATH]
  agentry default-paths
"""

from __future__ import annotations

import logging
import os
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
from agentry.configure import (
    MODEL_PROFILES,
    apply_recommended_options,
    read_raw_config,
    summarize_config,
)
from agentry.dashboard import run_dashboard
from agentry.github import gh_available, list_labels, repo_exists
from agentry.github import init_labels as gh_init_labels
from agentry.notify import DiscordNotifier
from agentry.orchestrator import Orchestrator, _role_allowed_by_mode
from agentry.session import active_session, list_sessions, stop_all_sessions, stop_session
from agentry.supervisor import resolve_cli
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
    for role, cfg in target_config.agents.items():
        if not cfg.enabled:
            click.secho(f"SKIP  role {role} disabled", fg="cyan")
            continue
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
        if not cfg.enabled:
            continue
        resolved_cli = resolve_cli(cfg.cli)
        if resolved_cli:
            click.secho(
                f"OK    role {role} cli {cfg.cli!r} found on PATH ({resolved_cli})",
                fg="green",
            )
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

    active_count = sum(
        1
        for role, cfg in target_config.agents.items()
        if cfg.enabled and _role_allowed_by_mode(target_config, role)
    )
    configured_count = sum(1 for cfg in target_config.agents.values() if cfg.enabled)
    disabled_count = len(target_config.agents) - configured_count

    click.secho(
        f"agentry started for {target_config.target_repo} "
        f"({active_count} active roles, {configured_count} enabled in config, "
        f"{disabled_count} disabled, mode={target_config.mode})\n"
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
    """Show sessions, run mode, and recent orchestrator activity."""
    target_path = target_path.resolve()
    target_config = load_target_config(target_path)
    log_root = target_logs_dir(target_path)
    sessions = {record.get("role"): record for record in list_sessions(target_path)}

    click.echo(f"target:    {target_config.target_repo}")
    click.echo(f"path:      {target_path}")
    click.echo(f"logs:      {log_root}")
    click.echo(f"mode:      {target_config.mode}")
    click.echo(
        "research:  "
        f"allow_create_issues={target_config.research.allow_create_issues}, "
        f"max_open_ready_for_design={target_config.research.max_open_ready_for_design}"
    )
    click.echo(
        "automation:"
        f" auto_merge={target_config.automation.auto_merge},"
        f" stop_when_queue_empty={target_config.automation.stop_when_queue_empty}"
    )
    enabled_count = sum(1 for cfg in target_config.agents.values() if cfg.enabled)
    disabled_count = len(target_config.agents) - enabled_count
    click.echo(f"roles ({enabled_count} enabled, {disabled_count} disabled):")

    for role in sorted(target_config.agents):
        cfg = target_config.agents[role]
        allowed = _role_allowed_by_mode(target_config, role)
        session = sessions.get(role)
        session_state = _format_session_state(session)
        if not cfg.enabled:
            click.secho(f"  {role}: disabled ({session_state})", fg="cyan")
            continue
        if not allowed:
            click.secho(f"  {role}: blocked by mode ({session_state})", fg="cyan")
            continue
        role_logs = log_root / role
        if not role_logs.is_dir():
            click.secho(f"  {role}: no log dir yet ({session_state})", fg="yellow")
            continue
        all_logs = sorted(role_logs.glob("*.log"))
        if not all_logs:
            click.secho(f"  {role}: no runs yet ({session_state})", fg="yellow")
            continue
        latest = all_logs[-3:]
        click.echo(f"  {role}: {len(all_logs)} runs total ({session_state})")
        for p in latest:
            size = p.stat().st_size
            click.echo(f"    - {p.name} ({size} bytes)")


def _format_session_state(session: dict | None) -> str:
    if not session:
        return "no session"
    state = session.get("state") or "unknown"
    pid = session.get("pid")
    tokens = session.get("tokens_used")
    budget = session.get("token_budget")
    bits = [str(state)]
    if pid:
        bits.append(f"pid={pid}")
    if tokens is not None or budget is not None:
        bits.append(f"tokens={tokens or 0}/{budget or '?'}")
    if session.get("budget_exceeded"):
        bits.append("budget-exceeded")
    return ", ".join(bits)


# -----------------------------------------------------------------------------
# stop
# -----------------------------------------------------------------------------


@cli.command()
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
)
@click.option("--all", "all_roles", is_flag=True, help="Stop all recorded role sessions.")
@click.argument("role", required=False)
def stop(target_path: Path, all_roles: bool, role: str | None) -> None:
    """Stop a role subprocess recorded in agentry/state/sessions."""
    target_path = target_path.resolve()
    if all_roles:
        results = stop_all_sessions(target_path)
        if not results:
            click.secho("no sessions found", fg="yellow")
            return
        for name, stopped in sorted(results.items()):
            color = "green" if stopped else "yellow"
            click.secho(f"{name}: {'stop signal sent' if stopped else 'marked stopped'}", fg=color)
        return

    if not role:
        raise click.UsageError("pass a ROLE or --all")

    if active_session(target_path, role) is None:
        click.secho(f"{role}: no active session; marking stopped if state exists", fg="yellow")
    stopped = stop_session(target_path, role)
    click.secho(f"{role}: {'stop signal sent' if stopped else 'marked stopped'}", fg="green")


# -----------------------------------------------------------------------------
# configure / gui
# -----------------------------------------------------------------------------


@cli.command("configure")
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
)
@click.option("--gui", "open_gui", is_flag=True, help="Run the local web dashboard.")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=4783, show_default=True, type=int)
@click.option("--defaults", "use_defaults", is_flag=True, help="Apply recommended defaults.")
@click.option("--mode", type=click.Choice(["manual", "pipeline", "autonomous"]))
@click.option("--model-profile", type=click.Choice(sorted(MODEL_PROFILES)))
@click.option("--enable-researcher/--disable-researcher", default=None)
@click.option("--enable-release/--disable-release", default=None)
@click.option("--auto-merge/--no-auto-merge", default=None)
@click.option("--stop-when-queue-empty/--keep-waiting", default=None)
def configure_cmd(
    target_path: Path,
    open_gui: bool,
    host: str,
    port: int,
    use_defaults: bool,
    mode: str | None,
    model_profile: str | None,
    enable_researcher: bool | None,
    enable_release: bool | None,
    auto_merge: bool | None,
    stop_when_queue_empty: bool | None,
) -> None:
    """Configure run mode, role switches, and recommended model tiers."""
    target_path = target_path.resolve()
    if open_gui:
        run_dashboard(target_path, host=host, port=port)
        return

    raw = read_raw_config(target_path)
    current = summarize_config(raw)

    if not use_defaults and _no_config_options(
        mode,
        model_profile,
        enable_researcher,
        enable_release,
        auto_merge,
        stop_when_queue_empty,
    ):
        selected_mode = click.prompt(
            "Run mode",
            default=str(current.get("mode") or "pipeline"),
            type=click.Choice(["manual", "pipeline", "autonomous"]),
        )
        selected_profile = click.prompt(
            "Model profile",
            default="balanced",
            type=click.Choice(sorted(MODEL_PROFILES)),
        )
        current_roles = current.get("roles") if isinstance(current.get("roles"), dict) else {}
        researcher_now = bool(
            current_roles.get("researcher", {}).get("enabled")
            if isinstance(current_roles.get("researcher"), dict)
            else False
        )
        release_now = bool(
            current_roles.get("release", {}).get("enabled")
            if isinstance(current_roles.get("release"), dict)
            else False
        )
        automation = (
            current.get("automation") if isinstance(current.get("automation"), dict) else {}
        )
        selected_researcher = click.confirm("Enable Researcher", default=researcher_now)
        selected_release = click.confirm("Enable Release Engineer", default=release_now)
        selected_auto_merge = click.confirm(
            "Auto-merge agent-approved PRs",
            default=bool(automation.get("auto_merge", False)),
        )
        selected_stop_empty = click.confirm(
            "Stop when queue is empty",
            default=bool(automation.get("stop_when_queue_empty", False)),
        )
    else:
        selected_mode = mode or "pipeline"
        selected_profile = model_profile or "balanced"
        selected_researcher = bool(enable_researcher) if enable_researcher is not None else False
        selected_release = bool(enable_release) if enable_release is not None else False
        selected_auto_merge = bool(auto_merge) if auto_merge is not None else False
        selected_stop_empty = (
            bool(stop_when_queue_empty) if stop_when_queue_empty is not None else False
        )

    updated = apply_recommended_options(
        target_path,
        mode=selected_mode,
        enable_researcher=selected_researcher,
        enable_release=selected_release,
        model_profile=selected_profile,
        auto_merge=selected_auto_merge,
        stop_when_queue_empty=selected_stop_empty,
    )
    summary = summarize_config(updated)
    click.secho(f"updated {target_config_file(target_path)}", fg="green")
    click.echo(f"mode: {summary['mode']}")
    for role, info in summary["roles"].items():
        click.echo(
            f"  {role}: enabled={info['enabled']} "
            f"model={info['model'] or '?'} budget={info['token_budget'] or '?'}"
        )


@cli.command()
@click.option(
    "--target",
    "target_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=4783, show_default=True, type=int)
def gui(target_path: Path, host: str, port: int) -> None:
    """Run the local Agentry status/configuration dashboard."""
    run_dashboard(target_path.resolve(), host=host, port=port)


def _no_config_options(*values: object) -> bool:
    return all(value is None for value in values)


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
