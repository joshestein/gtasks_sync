import json
from pathlib import Path

from gtasks_sync.cache import SyncError, Status, read_cached_tasks, serialize_tasks, write_cache
from gtasks_sync.state import State

from .conftest import LOCAL_ID, NOW


def test_serializes_tasks_with_local_ids(state: State) -> None:
    tasks = [
        {
            "id": "t1",
            "title": "milk",
            "due": "2026-11-20T00:00:00.000Z",
            "status": "needsAction",
            "position": "00001",
            "updated": "2026-11-15T09:00:00.000Z",
            "webViewLink": "https://tasks.google.com/x",
        },
        {"id": "t2", "title": "sub", "parent": "t1", "status": "completed", "completed": "2026-11-15T09:00:00.000Z"},
    ]
    state.map(LOCAL_ID, "t1", NOW)

    [first, second] = serialize_tasks(tasks, state)

    assert first == {
        "id": "t1",
        "local_id": LOCAL_ID,
        "parent": None,
        "position": "00001",
        "title": "milk",
        "notes": "",
        "due": "2026-11-20",
        "status": "needsAction",
        "completed": None,
        "updated": "2026-11-15T09:00:00.000Z",
        "url": "https://tasks.google.com/x",
    }
    assert (second["local_id"], second["parent"], second["due"]) == (None, "t1", None)


def test_write_then_read(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    write_cache(path, [{"id": "t1"}], Status(synced_at=NOW, last_attempt_at=NOW, error=SyncError("auth", "revoked")))
    data = json.loads(path.read_text())
    assert data["synced_at"] == "2026-11-15T09:00:00.000Z"
    assert data["error"] == {"kind": "auth", "message": "revoked"}
    assert read_cached_tasks(path) == [{"id": "t1"}]


def test_read_bad_cache_gives_no_tasks(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    assert read_cached_tasks(path) == []
    path.write_text('{"version": 99, "tasks": [{}]}')
    assert read_cached_tasks(path) == []
    path.write_text('{"version": 1, "tasks": {}}')
    assert read_cached_tasks(path) == []
