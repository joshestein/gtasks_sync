"""The sync loop: apply ops, fetch, write the cache, remove op files."""

import faulthandler
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from gtasks_sync.api import AuthError, Task, TasksApi, Transient
from gtasks_sync.apply import apply_queue
from gtasks_sync.cache import Status, SyncError, read_cache, serialize_tasks, write_cache
from gtasks_sync.queue import OP_FILE_RE, SYNC_NOW_FILE, Queue
from gtasks_sync.state import State

log = logging.getLogger(__name__)

POLL_SECONDS = 60
MAX_BACKOFF_SECONDS = 15 * 60
DEBOUNCE_SECONDS = 1
# Every HTTP call has a timeout, so a round that runs this long is hung.
# faulthandler then exits the process and launchd restarts it. A crash at any point is safe.
ROUND_TIMEOUT_SECONDS = 5 * 60
COMPLETED_WINDOW = timedelta(days=7)


class SyncApi(TasksApi, Protocol):
    def list_open(self) -> list[Task]: ...

    def list_completed_since(self, since: datetime) -> list[Task]: ...


def classify(e: Exception) -> SyncError:
    # KeychainError is an AuthError: the fix for both is `gtasks-sync setup`.
    kind = "auth" if isinstance(e, AuthError) else "network" if isinstance(e, Transient) else "other"
    return SyncError(kind, f"{type(e).__name__}: {e}")


def backoff_seconds(error: SyncError | None, failures: int) -> float:
    """Seconds until the next round. failures counts consecutive failed rounds, this one included."""
    if error is None:
        return POLL_SECONDS
    if error.kind == "auth":
        return MAX_BACKOFF_SECONDS
    return min(POLL_SECONDS * 2 ** (failures - 1), MAX_BACKOFF_SECONDS)


def fetch(api: SyncApi, now: datetime) -> list[Task]:
    """Open tasks and tasks completed in the window. A full fetch also catches deletes made elsewhere.

    A task completed between the two calls is in both lists. The second, newer copy wins.
    """
    tasks = {t["id"]: t for t in [*api.list_open(), *api.list_completed_since(now - COMPLETED_WINDOW)]}
    return list(tasks.values())


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Syncer:
    # Reads Keychain and builds a client. Called again after an auth error, so a new setup takes effect.
    open_api: Callable[[], SyncApi]
    state: State
    queue: Queue
    cache_file: Path
    now: Callable[[], datetime] = _utc_now
    api: SyncApi | None = field(default=None, init=False)
    # From the last cache, so a restart keeps the time of the last good sync.
    synced_at: datetime | None = field(init=False)

    def __post_init__(self) -> None:
        _, status = read_cache(self.cache_file)
        self.synced_at = status.synced_at if status else None

    def round(self) -> SyncError | None:
        """One round. Never raises: every error goes to the log and to cache.json."""
        attempt_at = self.now()
        tasks: list[dict[str, Any]] | None = None
        error = None
        try:
            api = self.api = self.api or self.open_api()
            apply_queue(api, self.state, self.queue, attempt_at)
            tasks = serialize_tasks(fetch(api, attempt_at), self.state)
        except Exception as e:
            error = self._fail(e)
            if error.kind == "auth":
                self.api = None

        try:
            if tasks is None:
                # Never empty the list on a failed round. Op files stay, so the overlay still shows them.
                tasks, _ = read_cache(self.cache_file)
            else:
                self.synced_at = attempt_at
            write_cache(self.cache_file, tasks, Status(self.synced_at, attempt_at, error))
            if error is None:
                # Only now, with their result in the cache, can Accepted ops go: a pending task never flickers.
                self.queue.finish(self.state.task_key, {t["id"]: t["updated"] for t in tasks})
                if self.state.keep_tasks({t["id"] for t in tasks}):
                    self.state.save()
        except Exception as e:  # For example a full disk. The next round tries again.
            error = error or self._fail(e)
        return error

    def _fail(self, e: Exception) -> SyncError:
        error = classify(e)
        log.warning("round failed: %s", error.message, exc_info=error.kind == "other")
        return error


@dataclass(frozen=True)
class Wake:
    """op: a new op file. sync_now: the user asked for a round now. sync_now also sets op."""

    op: threading.Event = field(default_factory=threading.Event)
    sync_now: threading.Event = field(default_factory=threading.Event)


class QueueHandler(FileSystemEventHandler):
    """Wake the loop when the extension renames a new op file into the queue or touches the sync-now file."""

    def __init__(self, queue_dir: Path, wake: Wake) -> None:
        self.queue_dir = queue_dir
        self.wake = wake

    def on_any_event(self, event: FileSystemEvent) -> None:
        path = Path(str(event.dest_path or event.src_path))
        if path.parent != self.queue_dir:
            return
        if path.name == SYNC_NOW_FILE:
            # "modified": the file was already there. FSEvents can merge an old flag into the unlink,
            # so the file must still exist.
            if event.event_type in ("created", "modified", "moved") and path.exists():
                self.wake.sync_now.set()
                self.wake.op.set()
        elif event.event_type in ("created", "moved") and OP_FILE_RE.fullmatch(path.name):
            self.wake.op.set()


def watch_queue(queue_dir: Path, wake: Wake) -> BaseObserver:
    observer = Observer()
    observer.schedule(QueueHandler(queue_dir, wake), str(queue_dir), recursive=False)
    observer.start()
    return observer


def wait_for_next_round(wake: Wake, delay: float, failed: bool) -> None:
    """After a failed round, only sync-now cuts the backoff short, so new ops do not hammer a failing server.
    After a new op, wait a moment so a burst of ops goes in one round."""
    if failed:
        wake.sync_now.wait(delay)
    elif wake.op.wait(delay) and not wake.sync_now.is_set():
        time.sleep(DEBOUNCE_SECONDS)


def run_forever(syncer: Syncer, wake: Wake) -> None:
    failures = 0
    while True:
        wake.op.clear()
        wake.sync_now.clear()
        # Remove the request before the round, so a request made during the round starts another one.
        try:
            (syncer.queue.dir / SYNC_NOW_FILE).unlink(missing_ok=True)
        except OSError:
            log.exception("could not remove %s", SYNC_NOW_FILE)
        # On a hang, faulthandler writes all stacks to stderr (the launchd log) and exits.
        faulthandler.dump_traceback_later(ROUND_TIMEOUT_SECONDS, exit=True)
        error = syncer.round()
        faulthandler.cancel_dump_traceback_later()

        failures = 0 if error is None else failures + 1
        wait_for_next_round(wake, backoff_seconds(error, failures), failed=error is not None)
