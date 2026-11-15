"""state.json: the id map, insert attempt marks, and applied ops. Written and read only by the service."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from gtasks_sync.atomic import write_json_atomic
from gtasks_sync.queue import is_local_id

log = logging.getLogger(__name__)

STATE_VERSION = 1
# An id map entry lives this long after its task got its id, while no op names its local id.
MAP_TTL = timedelta(days=7)


@dataclass(frozen=True)
class Mapped:
    task_id: str
    at: datetime


@dataclass
class State:
    path: Path = field(compare=False)
    id_map: dict[str, Mapped] = field(default_factory=dict)
    # Local id -> time of the first insert attempt (ADR 0001).
    insert_attempts: dict[str, datetime] = field(default_factory=dict)
    # Op file name -> its task (task id when known, else local id), for ops the API accepted.
    # They stay on disk until the cache has their result.
    applied: dict[str, str] = field(default_factory=dict)

    def resolve(self, task: str) -> str | None:
        """The task id for an op's task. None for a local id with no task id yet."""
        if not is_local_id(task):
            return task
        mapped = self.id_map.get(task)
        return mapped.task_id if mapped else None

    def task_key(self, task: str) -> str:
        """One key per task, whether an op names it by local id or task id."""
        return self.resolve(task) or task

    def map(self, local_id: str, task_id: str, at: datetime) -> None:
        self.id_map[local_id] = Mapped(task_id, at)
        self.insert_attempts.pop(local_id, None)

    def local_ids(self) -> dict[str, str]:
        """Task id -> local id."""
        return {m.task_id: local_id for local_id, m in self.id_map.items()}

    def prune(self, now: datetime, referenced: set[str]) -> None:
        """Drop old id map entries and attempt marks that no op names."""
        self.id_map = {
            local_id: m
            for local_id, m in self.id_map.items()
            if local_id in referenced or now - m.at < MAP_TTL
        }
        self.insert_attempts = {k: v for k, v in self.insert_attempts.items() if k in referenced}

    def save(self) -> None:
        write_json_atomic(
            self.path,
            {
                "version": STATE_VERSION,
                "id_map": {k: {"task_id": m.task_id, "at": m.at.isoformat()} for k, m in self.id_map.items()},
                "insert_attempts": {k: v.isoformat() for k, v in self.insert_attempts.items()},
                "applied": self.applied,
            },
        )


def _from_json(path: Path, raw: dict[str, Any]) -> State:
    if raw["version"] != STATE_VERSION:
        raise ValueError(f"unknown state version {raw['version']!r}")
    return State(
        path=path,
        id_map={k: Mapped(v["task_id"], datetime.fromisoformat(v["at"])) for k, v in raw["id_map"].items()},
        insert_attempts={k: datetime.fromisoformat(v) for k, v in raw["insert_attempts"].items()},
        applied=raw["applied"],
    )


def load_state(path: Path) -> State:
    """The saved state, or an empty state if there is no usable file."""
    try:
        return _from_json(path, json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        log.info("no %s: start empty", path.name)
    except Exception:
        # Losing the map can make a duplicate or a failed op. Never stop the service for it.
        log.exception("cannot read %s: start empty", path.name)
    return State(path=path)
