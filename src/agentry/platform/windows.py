"""Windows service installation via NSSM.

Requires `NSSM <https://nssm.cc/>`_ to be on PATH (operator's responsibility).
NSSM is the standard wrapper for running arbitrary processes as Windows
services because the Windows Service Control Manager has weird requirements
on what "a service" looks like that don't match a Python long-running script.

For OAuth credentials (``claude login`` / ``codex login``) to be reachable,
the service MUST run as the Operator's user account, not LocalSystem. This
function configures that automatically using whatever user is currently
running ``agentry service install``.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _ensure_nssm() -> str:
    nssm = shutil.which("nssm")
    if not nssm:
        raise RuntimeError(
            "nssm not found on PATH. Install from https://nssm.cc/ and add it to PATH."
        )
    return nssm


def install_service(target_path: Path, agentry_bin: str | None = None) -> None:
    """Register an NSSM service named ``agentry``.

    Idempotent — if the service exists, it's reconfigured rather than
    erroring.
    """
    nssm = _ensure_nssm()
    bin_path = agentry_bin or shutil.which("agentry") or sys.executable

    # If we don't have a clean exe path, fall back to "python -m agentry".
    if bin_path.endswith("agentry.exe") or bin_path.endswith("agentry"):
        cmd, args = bin_path, f"start --target {target_path.resolve()}"
    else:
        cmd, args = bin_path, f"-m agentry start --target {target_path.resolve()}"

    # Install (or remove + reinstall if already present).
    existing = subprocess.run(  # noqa: S603
        [nssm, "status", "agentry"], capture_output=True, text=True
    )
    if existing.returncode == 0:
        # Already installed — stop and remove first so settings reset.
        subprocess.run([nssm, "stop", "agentry"], check=False)  # noqa: S603
        subprocess.run([nssm, "remove", "agentry", "confirm"], check=False)  # noqa: S603

    subprocess.run([nssm, "install", "agentry", cmd, args], check=True)  # noqa: S603

    # Run as the current user so claude/codex OAuth credentials are reachable.
    user = os.environ.get("USERNAME") or getpass.getuser()
    subprocess.run(  # noqa: S603
        [nssm, "set", "agentry", "ObjectName", f".\\{user}", ""],
        check=False,
    )

    # Restart on failure with a short delay.
    subprocess.run([nssm, "set", "agentry", "AppRestartDelay", "10000"], check=False)  # noqa: S603
    subprocess.run([nssm, "set", "agentry", "AppExit", "Default", "Restart"], check=False)  # noqa: S603

    # Capture stdout/stderr to a log file under %USERPROFILE%\.agentry\logs\.
    user_home = Path(os.path.expanduser("~"))
    log_dir = user_home / ".agentry" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        [nssm, "set", "agentry", "AppStdout", str(log_dir / "agentry.out.log")],
        check=False,
    )
    subprocess.run(  # noqa: S603
        [nssm, "set", "agentry", "AppStderr", str(log_dir / "agentry.err.log")],
        check=False,
    )

    subprocess.run([nssm, "start", "agentry"], check=False)  # noqa: S603


def uninstall_service() -> None:
    """Stop and remove the NSSM service named ``agentry``. Idempotent."""
    nssm = shutil.which("nssm")
    if not nssm:
        return
    subprocess.run([nssm, "stop", "agentry"], check=False)  # noqa: S603
    subprocess.run([nssm, "remove", "agentry", "confirm"], check=False)  # noqa: S603


__all__ = ["install_service", "uninstall_service"]
