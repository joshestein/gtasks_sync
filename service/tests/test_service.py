import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from gtasks_sync import service
from gtasks_sync.api import AuthError, Transient, iso
from gtasks_sync.cache import SyncError, read_cache
from gtasks_sync.keychain import KeychainError
from gtasks_sync.queue import SYNC_NOW_FILE, Queue, list_op_files
from gtasks_sync.service import (
    COMPLETED_WINDOW,
    MAX_BACKOFF_SECONDS,
    POLL_SECONDS,
    QueueHandler,
    Syncer,
    Wake,
    backoff_seconds,
    classify,
    fetch,
    wait_for_next_round,
)
from gtasks_sync.state import State, load_state

from .conftest import LOCAL_ID, NOW, OTHER_LOCAL_ID, FakeApi, WriteOp, accepted


@pytest.fixture
def cache_file(tmp_path: Path) -> Path:
    return tmp_path / "cache.json"


@pytest.fixture
def opens() -> list[int]:
    """One entry per open_api call."""
    return []


MakeSyncer = Callable[..., Syncer]


@pytest.fixture
def make_syncer(api: FakeApi, state: State, queue: Queue, cache_file: Path, opens: list[int]) -> MakeSyncer:
    def open_fake() -> FakeApi:
        opens.append(1)
        return api

    def make(open_api: Callable[[], FakeApi] = open_fake, now: datetime = NOW) -> Syncer:
        return Syncer(open_api=open_api, state=state, queue=queue, cache_file=cache_file, now=lambda: now)

    return make


@pytest.fixture
def syncer(make_syncer: MakeSyncer) -> Syncer:
    return make_syncer()


def cached(cache_file: Path) -> dict:
    return json.loads(cache_file.read_text())


def titles(cache_file: Path) -> list[str]:
    return sorted(t["title"] for t in cached(cache_file)["tasks"])


# round


def test_round_applies_fetches_writes_cache_and_removes_ops(
    syncer: Syncer, api: FakeApi, state: State, write_op: WriteOp, queue_dir: Path, cache_file: Path
) -> None:
    api.add(title="old", status="completed")
    write_op("create", title="milk")

    assert syncer.round() is None

    data = cached(cache_file)
    assert data["error"] is None
    assert data["synced_at"] == data["last_attempt_at"] == "2026-11-15T09:00:00.000Z"
    milk = next(t for t in data["tasks"] if t["title"] == "milk")
    assert milk["local_id"] == LOCAL_ID
    assert titles(cache_file) == ["milk", "old"]
    assert list_op_files(queue_dir) == list_op_files(queue_dir / "accepted") == []
    assert load_state(state.path).id_map == {LOCAL_ID: milk["id"]}


def test_failed_fetch_keeps_ops_and_old_tasks_then_recovers(
    syncer: Syncer, api: FakeApi, write_op: WriteOp, queue_dir: Path, cache_file: Path
) -> None:
    api.add(title="old")
    syncer.round()
    path = write_op("create", title="milk")
    api.fail["list_open"] = Transient("timeout")

    error = syncer.round()

    assert error is not None and error.kind == "network"
    data = cached(cache_file)
    assert data["error"]["kind"] == "network"
    assert data["synced_at"] == "2026-11-15T09:00:00.000Z"
    assert titles(cache_file) == ["old"]  # The new task shows only through the overlay.
    assert list_op_files(queue_dir / "accepted") == [accepted(path)]

    api.calls.clear()
    assert syncer.round() is None
    assert "insert" not in api.call_names()  # Applied in the failed round, not sent again.
    assert titles(cache_file) == ["milk", "old"]
    assert list_op_files(queue_dir / "accepted") == []


def test_error_mid_queue_keeps_the_rest(
    syncer: Syncer, api: FakeApi, write_op: WriteOp, queue_dir: Path
) -> None:
    task = api.add(title="milk")
    write_op("complete", task=task["id"])
    write_op("delete", task=task["id"])
    api.fail["delete"] = Transient("timeout")

    assert syncer.round() == SyncError("network", "Transient: timeout")
    assert len(list_op_files(queue_dir)) == len(list_op_files(queue_dir / "accepted")) == 1
    assert "list_open" not in api.call_names()


def test_first_round_with_no_cache_writes_an_empty_list_on_failure(
    syncer: Syncer, api: FakeApi, cache_file: Path
) -> None:
    api.fail["list_open"] = Transient("down")
    syncer.round()
    data = cached(cache_file)
    assert (data["tasks"], data["synced_at"]) == ([], None)


def test_auth_error_opens_the_api_again_next_round(syncer: Syncer, api: FakeApi, opens: list[int]) -> None:
    api.fail["list_open"] = AuthError("HTTP 401")
    assert syncer.round() == SyncError("auth", "AuthError: HTTP 401")
    assert syncer.round() is None
    assert len(opens) == 2
    syncer.round()
    assert len(opens) == 2


def test_keychain_error_is_an_auth_error(make_syncer: MakeSyncer) -> None:
    def open_api() -> FakeApi:
        raise KeychainError("no secrets: run `gtasks-sync setup`")

    error = make_syncer(open_api=open_api).round()
    assert error is not None and error.kind == "auth"


def test_round_keeps_map_entries_only_for_tasks_in_the_cache(syncer: Syncer, api: FakeApi, state: State) -> None:
    task = api.add(title="milk")
    state.id_map = {LOCAL_ID: task["id"], OTHER_LOCAL_ID: "deleted-elsewhere"}
    syncer.round()
    assert state.id_map == {LOCAL_ID: task["id"]}
    assert load_state(state.path).id_map == {LOCAL_ID: task["id"]}


# errors and backoff


def test_classify() -> None:
    assert classify(AuthError("x")).kind == "auth"
    assert classify(KeychainError("x")).kind == "auth"
    assert classify(Transient("x")).kind == "network"
    assert classify(ValueError("x")) == SyncError("other", "ValueError: x")


def test_backoff() -> None:
    assert backoff_seconds(None, 0) == POLL_SECONDS
    assert backoff_seconds(SyncError("auth", ""), 1) == MAX_BACKOFF_SECONDS
    network = SyncError("network", "")
    assert [backoff_seconds(network, n) for n in (1, 2, 3, 4, 5, 10)] == [60, 120, 240, 480, 900, 900]


# wake-ups


@pytest.fixture
def handler(queue_dir: Path) -> Callable[..., Wake]:
    def make(event: object) -> Wake:
        wake = Wake()
        QueueHandler(queue_dir, wake).on_any_event(event)  # pyright: ignore[reportArgumentType]
        return wake

    return make


def test_new_op_file_wakes_the_loop(handler: Callable[..., Wake], queue_dir: Path) -> None:
    assert handler(FileCreatedEvent(str(queue_dir / "1-abcd1234.json"))).op.is_set()
    assert handler(FileMovedEvent(str(queue_dir / ".tmp"), str(queue_dir / "1-abcd1234.json"))).op.is_set()


def test_temp_files_and_subdirectories_do_not_wake(handler: Callable[..., Wake], queue_dir: Path) -> None:
    assert not handler(FileCreatedEvent(str(queue_dir / ".1-abcd1234.json.tmp"))).op.is_set()
    assert not handler(FileCreatedEvent(str(queue_dir / "failed" / "1-abcd1234.json"))).op.is_set()
    assert not handler(FileCreatedEvent(str(queue_dir / "accepted" / "1-abcd1234.json"))).op.is_set()


def test_sync_now_sets_both_only_if_the_file_exists(handler: Callable[..., Wake], queue_dir: Path) -> None:
    path = queue_dir / SYNC_NOW_FILE
    assert not handler(FileModifiedEvent(str(path))).sync_now.is_set()
    path.touch()
    wake = handler(FileModifiedEvent(str(path)))
    assert wake.sync_now.is_set() and wake.op.is_set()


def test_after_a_failure_only_sync_now_ends_the_wait() -> None:
    wake = Wake()
    wake.op.set()
    start = time.monotonic()
    wait_for_next_round(wake, 0.2, failed=True)
    assert time.monotonic() - start >= 0.2

    wake.sync_now.set()
    start = time.monotonic()
    wait_for_next_round(wake, 5, failed=True)
    assert time.monotonic() - start < 1


def test_restart_keeps_synced_at_and_tasks_on_a_failed_round(
    syncer: Syncer, make_syncer: MakeSyncer, api: FakeApi, cache_file: Path
) -> None:
    api.add(title="milk")
    syncer.round()
    later = NOW + timedelta(minutes=5)
    restarted = make_syncer(now=later)
    assert restarted.synced_at == NOW

    api.fail["list_open"] = Transient("down")
    restarted.round()

    tasks, status = read_cache(cache_file)
    assert [t["title"] for t in tasks] == ["milk"]
    assert status is not None and (status.synced_at, status.last_attempt_at) == (NOW, later)


def test_fetch_keeps_one_copy_of_a_task_completed_between_the_two_calls(api: FakeApi) -> None:
    task = api.add(title="milk")
    open_copy = dict(task)
    api.patch(task["id"], {"status": "completed"})
    api.list_open = lambda: [open_copy]  # The open list was read before the completion.
    [fetched] = fetch(api, NOW)
    assert fetched["status"] == "completed"


def test_fetch_leaves_out_tasks_completed_before_the_window(api: FakeApi) -> None:
    api.add(title="old", status="completed", completed=iso(NOW - COMPLETED_WINDOW - timedelta(seconds=1)))
    api.add(title="recent", status="completed")
    assert [t["title"] for t in fetch(api, NOW)] == ["recent"]


def test_a_bad_task_from_the_api_is_an_error_not_a_crash(
    syncer: Syncer, api: FakeApi, cache_file: Path
) -> None:
    api.add(title="milk")
    syncer.round()
    api.list_open = lambda: [{"title": "no id"}]
    error = syncer.round()
    assert error is not None and error.kind == "other"
    tasks, status = read_cache(cache_file)
    assert [t["title"] for t in tasks] == ["milk"]
    assert status is not None and status.error == error


def test_a_disk_error_after_the_fetch_is_an_error_not_a_crash(
    syncer: Syncer, monkeypatch: pytest.MonkeyPatch, write_op: WriteOp, queue_dir: Path
) -> None:
    write_op("create", title="milk")

    def full(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(service, "write_cache", full)
    error = syncer.round()
    assert error is not None and error.kind == "other"
    assert len(list_op_files(queue_dir / "accepted")) == 1  # Kept: the cache has no result for it.


def test_an_idle_round_does_not_write_state(syncer: Syncer, state: State) -> None:
    syncer.round()
    assert not state.path.exists()
