import argparse
import sys
from pathlib import Path

from gtasks_sync.api import ApiError
from gtasks_sync.auth import authorize, open_api
from gtasks_sync.keychain import KeychainError, save_secrets


def setup(args: argparse.Namespace) -> None:
    client_secret: Path = args.client_secret
    if not client_secret.is_file():
        sys.exit(f"No such file: {client_secret}")
    print("A browser window opens. Sign in and allow access to Google Tasks.")
    secrets = authorize(client_secret)

    # Save first: if the check fails (network, API not enabled), a later check needs no new consent.
    try:
        save_secrets(secrets)
    except KeychainError as e:
        sys.exit(f"Cannot save to Keychain: {e}")
    print("Secrets saved to Keychain.")
    try:
        tasks = open_api(secrets).list_open()
    except ApiError as e:
        sys.exit(f"Access check failed: {type(e).__name__}: {e}\nFix the cause (network, Tasks API enabled?) and run setup again.")
    print(f"Access works ({len(tasks)} open tasks).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gtasks-sync", description="Sync Google Tasks to local files for Raycast.")
    commands = parser.add_subparsers(dest="command", required=True)
    setup_cmd = commands.add_parser("setup", help="authorize with Google and save the secrets to Keychain")
    setup_cmd.add_argument(
        "--client-secret", type=Path, required=True, help="client_secret.json of a Desktop app OAuth client"
    )
    setup_cmd.set_defaults(fn=setup)
    args = parser.parse_args()
    args.fn(args)
