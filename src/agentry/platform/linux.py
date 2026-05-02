"""Linux service installation via systemd user unit.

Writes ``~/.config/systemd/user/agentry.service`` and runs
``systemctl --user enable --now agentry``. User services don't need root and
don't survive logout by default — operators wanting boot-survival should
enable lingering with ``loginctl enable-linger <user>``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

UNIT_TEMPLATE = """\
[Unit]
Description=Agentry — autonomous multi-agent product organization
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={agentry_bin} start --target {target_path}
Restart=on-failure
RestartSec=10s
# Keep stdout/stderr in journal
StandardOutput=journal
StandardError=journal
# Allow up to 30s for graceful shutdown after SIGTERM
TimeoutStopSec=30s
# Don't kill grandchildren on SIGTERM — let agentry tear them down itself
KillMode=mixed

[Install]
WantedBy=default.target
"""


def _systemd_user_dir() -> Path:
    return Path(os.path.expanduser("~/.config/systemd/user"))


def install_service(target_path: Path, agentry_bin: str | None = None) -> Path:
    """Write the systemd user unit and enable + start it.

    Returns the path of the unit file. Idempotent — safe to re-run.
    """
    if shutil.which("systemctl") is None:
        raise RuntimeError("systemctl not found; this host doesn't appear to use systemd")

    bin_path = agentry_bin or shutil.which("agentry") or "agentry"
    unit_dir = _systemd_user_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "agentry.service"

    contents = UNIT_TEMPLATE.format(
        agentry_bin=bin_path,
        target_path=str(target_path.resolve()),
    )
    unit_path.write_text(contents, encoding="utf-8")

    # Reload, enable, and start.
    for cmd in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "agentry.service"],
        ["systemctl", "--user", "start", "agentry.service"],
    ):
        subprocess.run(cmd, check=False)  # noqa: S603

    return unit_path


def uninstall_service() -> None:
    """Stop, disable, and remove the unit file. Idempotent."""
    for cmd in (
        ["systemctl", "--user", "stop", "agentry.service"],
        ["systemctl", "--user", "disable", "agentry.service"],
    ):
        subprocess.run(cmd, check=False)  # noqa: S603

    unit_path = _systemd_user_dir() / "agentry.service"
    if unit_path.exists():
        unit_path.unlink()

    subprocess.run(  # noqa: S603
        ["systemctl", "--user", "daemon-reload"], check=False
    )


__all__ = ["install_service", "uninstall_service"]
