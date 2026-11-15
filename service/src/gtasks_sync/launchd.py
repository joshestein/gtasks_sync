"""The launchd agent that runs `gtasks-sync run` at login and restarts it when it exits."""

import os
import plistlib
import subprocess
import time
from pathlib import Path

LABEL = "local.gtasks-sync"
PLIST_FILE = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def is_loaded() -> bool:
    return (
        subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, check=False).returncode == 0
    )


def install(program: list[str], stdio_log: Path) -> None:
    """Write the plist and load it. Replaces an agent that is already loaded, so new code takes effect."""
    uninstall()
    PLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_FILE.open("wb") as f:
        plistlib.dump(
            {
                "Label": LABEL,
                "ProgramArguments": program,
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(stdio_log),
                "StandardErrorPath": str(stdio_log),
            },
            f,
        )
    # bootout finishes asynchronously, so an immediate bootstrap can fail with an I/O error.
    error = ""
    for _ in range(10):
        result = subprocess.run(
            ["launchctl", "bootstrap", _domain(), str(PLIST_FILE)], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return
        error = result.stderr.strip()
        time.sleep(0.5)
    raise RuntimeError(f"launchctl bootstrap failed: {error}")


def uninstall() -> None:
    # A bootout of an agent that is not loaded fails with no effect.
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, check=False)
    PLIST_FILE.unlink(missing_ok=True)
