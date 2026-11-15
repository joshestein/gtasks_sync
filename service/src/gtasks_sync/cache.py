"""cache.json: every task the Mac shows, plus sync status. Written only by the service."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from gtasks_sync.api import Task, iso, task_fields
from gtasks_sync.atomic import write_json_atomic
from gtasks_sync.state import State

CACHE_VERSION = 1

ErrorKind = Literal["auth", "network", "other"]


@dataclass(frozen=True)
class SyncError:
    kind: ErrorKind
    message: str


@dataclass(frozen=True)
class Status:
    synced_at: datetime | None
    last_attempt_at: datetime
    error: SyncError | None


def task_to_dict(task: Task, local_id: str | None) -> dict[str, Any]:
    title, notes, due = task_fields(task)
    return {
        "id": task["id"],
        "local_id": local_id,
        "parent": task.get("parent"),
        "position": task.get("position", ""),
        "title": title,
        "notes": notes,
        "due": due,
        "status": task.get("status", "needsAction"),
        "completed": task.get("completed"),
        "updated": task.get("updated"),
        "url": task.get("webViewLink"),
    }


def serialize_tasks(tasks: Iterable[Task], state: State) -> list[dict[str, Any]]:
    local_ids = state.local_ids()
    return [task_to_dict(t, local_ids.get(t["id"])) for t in tasks]


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _error(value: Any) -> SyncError | None:
    if isinstance(value, dict) and value.get("kind") in ("auth", "network", "other"):
        return SyncError(value["kind"], str(value.get("message", "")))
    return None


def read_cache(path: Path) -> tuple[list[dict[str, Any]], Status | None]:
    """(tasks, status) from the current cache.json. ([], None) if there is no usable file.

    Each part is read on its own, so a bad field never loses the tasks: the service keeps them on a failed round.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return [], None
    tasks = data.get("tasks")
    last_attempt_at = _time(data.get("last_attempt_at"))
    status = (
        Status(_time(data.get("synced_at")), last_attempt_at, _error(data.get("error"))) if last_attempt_at else None
    )
    return (tasks if isinstance(tasks, list) else []), status


def write_cache(path: Path, tasks: list[dict[str, Any]], status: Status) -> None:
    error = status.error
    write_json_atomic(
        path,
        {
            "version": CACHE_VERSION,
            "synced_at": iso(status.synced_at) if status.synced_at else None,
            "last_attempt_at": iso(status.last_attempt_at),
            "error": {"kind": error.kind, "message": error.message} if error else None,
            "tasks": tasks,
        },
    )
