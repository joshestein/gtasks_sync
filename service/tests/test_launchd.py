import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gtasks_sync import launchd


class FakeLaunchctl:
    """Records launchctl calls. The agent counts as loaded after bootstrap, until bootout."""

    def __init__(self, loaded: bool = False, bootstrap_failures: int = 0) -> None:
        self.loaded = loaded
        self.bootstrap_failures = bootstrap_failures
        self.calls: list[str] = []

    def run(self, args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        verb = args[1]
        self.calls.append(verb)
        code = 0
        if verb == "print":
            code = 0 if self.loaded else 113
        elif verb == "bootout":
            self.loaded = False
        elif verb == "bootstrap":
            if self.bootstrap_failures:
                self.bootstrap_failures -= 1
                code = 5
            else:
                self.loaded = True
        return subprocess.CompletedProcess(args, code, "", "Input/output error" if code == 5 else "")


@pytest.fixture
def plist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "LaunchAgents" / f"{launchd.LABEL}.plist"
    monkeypatch.setattr(launchd, "PLIST_FILE", path)
    monkeypatch.setattr(launchd.time, "sleep", lambda _: None)
    return path


def use(fake: FakeLaunchctl, monkeypatch: pytest.MonkeyPatch) -> FakeLaunchctl:
    monkeypatch.setattr(launchd.subprocess, "run", fake.run)
    return fake


def test_install_writes_the_plist_and_loads_it(plist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use(FakeLaunchctl(), monkeypatch)
    launchd.install(["/venv/bin/gtasks-sync", "run"], Path("/logs/launchd.log"))

    assert plistlib.loads(plist.read_bytes()) == {
        "Label": "local.gtasks-sync",
        "ProgramArguments": ["/venv/bin/gtasks-sync", "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": "/logs/launchd.log",
        "StandardErrorPath": "/logs/launchd.log",
    }
    assert fake.calls == ["print", "bootstrap"]
    assert launchd.is_loaded()


def test_install_replaces_a_loaded_agent(plist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use(FakeLaunchctl(loaded=True), monkeypatch)
    launchd.install(["x"], Path("/log"))
    assert fake.calls == ["print", "bootout", "bootstrap"]


def test_install_retries_bootstrap_while_bootout_finishes(plist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use(FakeLaunchctl(loaded=True, bootstrap_failures=2), monkeypatch)
    launchd.install(["x"], Path("/log"))
    assert fake.calls.count("bootstrap") == 3


def test_install_gives_up_after_ten_tries(plist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(FakeLaunchctl(bootstrap_failures=99), monkeypatch)
    with pytest.raises(RuntimeError, match="Input/output error"):
        launchd.install(["x"], Path("/log"))


def test_uninstall_unloads_and_removes_the_plist(plist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use(FakeLaunchctl(), monkeypatch)
    launchd.install(["x"], Path("/log"))
    launchd.uninstall()
    assert not plist.exists()
    assert not fake.loaded
    launchd.uninstall()  # A second uninstall is not an error.
