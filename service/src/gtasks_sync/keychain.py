"""OAuth secrets in the login Keychain, through /usr/bin/security (ADR 0003)."""

import base64
import json
import subprocess
from dataclasses import asdict, dataclass

from gtasks_sync.api import AuthError

SECURITY = "/usr/bin/security"
SERVICE = "gtasks-sync"
ACCOUNT = "oauth"
NOT_FOUND = 44


class KeychainError(AuthError):
    """The fix is the same as for a revoked token: run setup."""


@dataclass(frozen=True)
class Secrets:
    client_id: str
    client_secret: str
    refresh_token: str


def _security(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([SECURITY, *args], input=stdin, capture_output=True, text=True, check=False)


def save_secrets(secrets: Secrets) -> None:
    """Store one item with all three values, replacing any old one.

    The value goes through stdin (`security -i`), never argv, so `ps` cannot see it.
    Base64 keeps quotes and backslashes out of the `security -i` command line.
    """
    value = base64.b64encode(json.dumps(asdict(secrets)).encode()).decode()
    command = f'add-generic-password -U -s {SERVICE} -a {ACCOUNT} -w "{value}" -T {SECURITY}\n'
    result = _security("-i", stdin=command)
    if result.returncode != 0 or result.stderr.strip():
        raise KeychainError(f"cannot save secrets: {result.stderr.strip()}")


def read_secrets() -> Secrets:
    result = _security("find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w")
    if result.returncode == NOT_FOUND:
        raise KeychainError("no secrets: run `gtasks-sync setup`")
    if result.returncode != 0:
        raise KeychainError(f"cannot read secrets: {result.stderr.strip()}")
    try:
        return Secrets(**json.loads(base64.b64decode(result.stdout.strip())))
    except (ValueError, TypeError) as e:
        raise KeychainError(f"bad Keychain item, run `gtasks-sync setup`: {e}") from e


def delete_secrets() -> bool:
    """Return False if there was no item."""
    result = _security("delete-generic-password", "-s", SERVICE, "-a", ACCOUNT)
    if result.returncode not in (0, NOT_FOUND):
        raise KeychainError(f"cannot delete secrets: {result.stderr.strip()}")
    return result.returncode == 0
