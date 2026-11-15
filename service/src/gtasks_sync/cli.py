import argparse
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from gtasks_sync.api import ApiError
from gtasks_sync.auth import authorize, open_api
from gtasks_sync.cache import read_cache
from gtasks_sync import launchd
from gtasks_sync.keychain import KeychainError, delete_secrets, read_secrets, save_secrets
from gtasks_sync.paths import APP_DIR, CACHE_FILE, LAUNCHD_LOG_FILE, LOG_FILE, QUEUE_DIR, STATE_FILE
from gtasks_sync.queue import Queue, list_op_files
from gtasks_sync.state import load_state

log = logging.getLogger(__name__)


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
    _install()


def install(_: argparse.Namespace) -> None:
    try:
        read_secrets()
    except KeychainError as e:
        sys.exit(str(e))
    _install()


def _install() -> None:
    """Load the agent, or reload it so new code takes effect."""
    launchd.install([str(Path(sys.prefix) / "bin" / "gtasks-sync"), "run"], LAUNCHD_LOG_FILE)
    print(f"Service installed ({launchd.PLIST_FILE}). Log: {LOG_FILE}")


def run(_: argparse.Namespace) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    # Here, not at the top: setup and status must work even if the watcher library cannot load.
    from gtasks_sync.service import Syncer, Wake, run_forever, watch_queue

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    syncer = Syncer(
        open_api=lambda: open_api(read_secrets()),
        state=load_state(STATE_FILE),
        queue=Queue(QUEUE_DIR),
        cache_file=CACHE_FILE,
    )
    wake = Wake()
    watch_queue(QUEUE_DIR, wake)
    log.info("started")
    run_forever(syncer, wake)


def status(_: argparse.Namespace) -> None:
    print(f"agent:    {'loaded' if launchd.is_loaded() else 'not loaded'}")
    tasks, cache = read_cache(CACHE_FILE)
    if cache is None:
        print("cache:    none")
    else:
        error = cache.error
        print(f"synced:   {cache.synced_at or 'never'}")
        print(f"attempt:  {cache.last_attempt_at}")
        print(f"error:    {f'{error.kind}: {error.message}' if error else 'none'}")
        print(f"tasks:    {len(tasks)}")
    queue = Queue(QUEUE_DIR)
    print(f"queued:   {len(list_op_files(queue.dir))}")
    print(f"accepted: {len(list_op_files(queue.accepted_dir))}")
    print(f"failed:   {len(list_op_files(queue.failed_dir))}")


def uninstall(args: argparse.Namespace) -> None:
    launchd.uninstall()
    print("Service removed.")
    if not args.purge:
        return
    # Accepted ops already reached Google. Only ops still in the Queue would be lost.
    queued = len(list_op_files(QUEUE_DIR))
    if queued and input(f"{queued} ops have not reached Google and will be lost. Type 'yes' to continue: ") != "yes":
        sys.exit("Stopped. The Keychain item and data are kept.")
    delete_secrets()
    shutil.rmtree(APP_DIR, ignore_errors=True)
    print("Keychain item and data removed.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gtasks-sync", description="Sync Google Tasks to local files for Raycast.")
    commands = parser.add_subparsers(dest="command", required=True)
    setup_cmd = commands.add_parser("setup", help="authorize with Google, save the secrets to Keychain, install the service")
    setup_cmd.add_argument(
        "--client-secret", type=Path, required=True, help="client_secret.json of a Desktop app OAuth client"
    )
    setup_cmd.set_defaults(fn=setup)
    commands.add_parser("install", help="install or reload the service, with the secrets already saved").set_defaults(
        fn=install
    )
    commands.add_parser("run", help="run the sync loop (launchd runs this)").set_defaults(fn=run)
    commands.add_parser("status", help="show sync status").set_defaults(fn=status)
    remove = commands.add_parser("uninstall", help="remove the service")
    remove.add_argument("--purge", action="store_true", help="also delete the Keychain item and all local data")
    remove.set_defaults(fn=uninstall)
    args = parser.parse_args()
    args.fn(args)
