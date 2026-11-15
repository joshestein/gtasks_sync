import json
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from gtasks_sync.api import Task, Transient, iso
from gtasks_sync.queue import Queue
from gtasks_sync.state import State

LOCAL_ID = "local:1763198043000-3f9a0c1e"
OTHER_LOCAL_ID = "local:1763198044000-00000001"
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

WriteOp = Callable[..., Path]


class FakeApi:
    """The default task list in memory. Records every call."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.calls: list[tuple[Any, ...]] = []
        self._ids = count(1)
        # Method name -> error to raise before the call does anything.
        self.fail: dict[str, Exception] = {}
        # Insert stores the task, then raises Transient: the response was lost.
        self.lose_insert_response = False

    def add(self, **fields: Any) -> Task:
        task_id = f"t{next(self._ids)}"
        task: Task = {"id": task_id, "status": "needsAction", "updated": iso(NOW), **fields}
        if task["status"] == "completed":
            task.setdefault("completed", iso(NOW))
        self.tasks[task_id] = task
        return task

    def _check(self, method: str) -> None:
        if method in self.fail:
            raise self.fail.pop(method)

    def _children(self, task_id: str) -> list[Task]:
        return [t for t in self.tasks.values() if t.get("parent") == task_id]

    def insert(self, body: Task) -> Task:
        self._check("insert")
        self.calls.append(("insert", body))
        task = self.add(**body)
        if self.lose_insert_response:
            self.lose_insert_response = False
            raise Transient("timeout")
        return task

    def patch(self, task_id: str, body: Task) -> None:
        self._check("patch")
        self.calls.append(("patch", task_id, body))
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.update(body)  # As the real API: a deleted task takes the patch and stays deleted.
        if body.get("status") == "completed":  # As the real API.
            for t in [task, *self._children(task_id)]:
                t.update(status="completed", completed=iso(NOW))
        elif body.get("status") == "needsAction":
            task.pop("completed", None)

    def delete(self, task_id: str) -> None:
        self._check("delete")
        self.calls.append(("delete", task_id))
        if task_id in self.tasks:
            for task in [self.tasks[task_id], *self._children(task_id)]:
                task["deleted"] = True

    def list_updated_since(self, since: datetime) -> list[Task]:
        self._check("list_updated_since")
        self.calls.append(("list_updated_since", since))
        return [t for t in self.live() if datetime.fromisoformat(t["updated"]) >= since]

    def call_names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def list_open(self) -> list[Task]:
        self._check("list_open")
        self.calls.append(("list_open",))
        return [t for t in self.live() if t["status"] == "needsAction"]

    def list_completed_since(self, since: datetime) -> list[Task]:
        self._check("list_completed_since")
        self.calls.append(("list_completed_since", since))
        return [t for t in self.live() if t["status"] == "completed" and datetime.fromisoformat(t["completed"]) >= since]

    def live(self) -> list[Task]:
        return [t for t in self.tasks.values() if not t.get("deleted")]


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def queue_dir(tmp_path: Path) -> Path:
    d = tmp_path / "queue"
    d.mkdir()
    return d


@pytest.fixture
def queue(queue_dir: Path) -> Queue:
    return Queue(queue_dir)


def accepted(path: Path) -> Path:
    """Where an op file goes once Google accepts it."""
    return path.parent / "accepted" / path.name


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture
def state(state_path: Path) -> State:
    return State(path=state_path)


@pytest.fixture
def write_op(queue_dir: Path) -> WriteOp:
    """Write an op file the way the extension does. Names sort in call order."""
    # From NOW on, so an op is newer than a task the fake API made at NOW.
    counter = count(int(NOW.timestamp() * 1000))

    def write(op: str, task: str = LOCAL_ID, raw: str | None = None, **fields: Any) -> Path:
        path = queue_dir / f"{next(counter)}-abcd1234.json"
        body = {"op": op, "task": task, **fields}
        path.write_text(raw if raw is not None else json.dumps(body))
        return path

    return write
