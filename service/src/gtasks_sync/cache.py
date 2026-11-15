"""cache.json: every task the Mac shows, plus sync status. Written only by the service."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from gtasks_sync.api import Task, task_fields
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
    last_attempt_at: datetime | None
    error: SyncError | None


def iso(dt: datetime | None) -> str | None:
    """Same format as JS Date.toISOString()."""
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def read_cached_tasks(path: Path) -> list[dict[str, Any]]:
    """The tasks in the current cache.json, or [] if there is no usable file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks = data["tasks"] if data["version"] == CACHE_VERSION else []
    except (OSError, ValueError, TypeError, KeyError):
        return []
    return tasks if isinstance(tasks, list) else []


def write_cache(path: Path, tasks: list[dict[str, Any]], status: Status) -> None:
    error = status.error
    write_json_atomic(
        path,
        {
            "version": CACHE_VERSION,
            "synced_at": iso(status.synced_at),
            "last_attempt_at": iso(status.last_attempt_at),
            "error": {"kind": error.kind, "message": error.message} if error else None,
            "tasks": tasks,
        },
    )
