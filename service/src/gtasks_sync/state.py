"""state.json: the id map, insert attempt marks, and applied ops. Written and read only by the service."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from gtasks_sync.atomic import write_json_atomic
from gtasks_sync.queue import is_local_id

log = logging.getLogger(__name__)

# 2: id_map values are task ids, and applied ops moved to queue/accepted/.
STATE_VERSION = 2


@dataclass
class State:
    path: Path = field(compare=False)
    # Local id -> task id. An entry lives while its task is in the Cache.
    id_map: dict[str, str] = field(default_factory=dict)
    # Local id -> time of the first insert attempt (ADR 0001). Gone once the create is mapped or failed.
    insert_attempts: dict[str, datetime] = field(default_factory=dict)

    def resolve(self, task: str) -> str | None:
        """The task id for an op's task. None for a local id with no task id."""
        return self.id_map.get(task) if is_local_id(task) else task

    def task_key(self, task: str) -> str:
        """One key per task, whether an op names it by local id or task id."""
        return self.resolve(task) or task

    def map(self, local_id: str, task_id: str) -> None:
        self.id_map[local_id] = task_id
        self.insert_attempts.pop(local_id, None)

    def local_ids(self) -> dict[str, str]:
        """Task id -> local id."""
        return {task_id: local_id for local_id, task_id in self.id_map.items()}

    def keep_tasks(self, task_ids: set[str]) -> bool:
        """Drop id map entries for tasks not in the Cache. Return True if any were dropped."""
        kept = {local_id: task_id for local_id, task_id in self.id_map.items() if task_id in task_ids}
        changed = kept != self.id_map
        self.id_map = kept
        return changed

    def save(self) -> None:
        write_json_atomic(
            self.path,
            {
                "version": STATE_VERSION,
                "id_map": self.id_map,
                "insert_attempts": {k: v.isoformat() for k, v in self.insert_attempts.items()},
            },
        )


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {value!r}")
    return value


def _from_json(path: Path, raw: dict[str, Any]) -> State:
    """Raise on any bad shape, so load_state starts empty instead of failing in every round."""
    if raw["version"] != STATE_VERSION:
        raise ValueError(f"unknown state version {raw['version']!r}")
    return State(
        path=path,
        id_map={_str(k): _str(v) for k, v in raw["id_map"].items()},
        insert_attempts={_str(k): datetime.fromisoformat(v) for k, v in raw["insert_attempts"].items()},
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
