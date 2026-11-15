"""The op queue: one JSON file per op in the queue directory (ADR 0002)."""

import json
import logging
import os
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast, get_args

from gtasks_sync.errors import OpFailed

log = logging.getLogger(__name__)

OpKind = Literal["create", "update", "complete", "uncomplete", "delete"]

# Minted by the extension at capture (ADR 0001). Must match raycast/src/lib/store.ts.
LOCAL_ID_RE = re.compile(r"local:\d+-[0-9a-f]{8}")
# Op file names: "<Date.now()>-<hex>.json". Must match OP_FILE in raycast/src/lib/store.ts.
OP_FILE_RE = re.compile(r"\d+-[0-9a-f]+\.json")
# The extension touches this file to ask for a round now, even during a backoff.
SYNC_NOW_FILE = "sync-now"


class InvalidOp(OpFailed):
    """The op file cannot be read or has a bad schema."""


@dataclass(frozen=True)
class Op:
    kind: OpKind
    task: str
    # create: title, notes, due. update: the changed fields only. Others: empty.
    fields: dict[str, str | None] = field(default_factory=dict)


def is_local_id(task: str) -> bool:
    return task.startswith("local:")


def list_op_files(queue_dir: Path) -> list[Path]:
    """Op files in apply order. Skips temp files and other files."""
    return sorted(p for p in queue_dir.glob("*.json") if OP_FILE_RE.fullmatch(p.name))


def _check_title(value: Any) -> str:
    # The extension trims too. This is a second guard, so adoption compares what the API stores.
    title = value.strip() if isinstance(value, str) else ""
    if not title:
        raise InvalidOp("title must be a non-empty string")
    return title


def _check_notes(value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidOp("notes must be a string")
    return value


def _check_due(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError as e:
        raise InvalidOp(f"bad due date: {value!r}") from e
    return value


_CHECKS = {"title": _check_title, "notes": _check_notes, "due": _check_due}


def parse_op(path: Path) -> Op:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidOp(f"unreadable: {e}") from e
    if not isinstance(raw, dict):
        raise InvalidOp("not an object")

    kind = raw.get("op")
    if kind not in get_args(OpKind):
        raise InvalidOp(f"unknown op: {kind!r}")
    task = raw.get("task")
    if not isinstance(task, str) or not task:
        raise InvalidOp("missing task")
    if (kind == "create" or is_local_id(task)) and not LOCAL_ID_RE.fullmatch(task):
        raise InvalidOp(f"bad local id: {task!r}")

    fields: dict[str, str | None] = {}
    if kind == "create":
        fields = {
            "title": _check_title(raw.get("title")),
            "notes": _check_notes(raw.get("notes", "")),
            "due": _check_due(raw.get("due")),
        }
    elif kind == "update":
        changed = raw.get("fields")
        if not isinstance(changed, dict) or not changed:
            raise InvalidOp("update needs fields")
        for name, value in changed.items():
            if name not in _CHECKS:
                raise InvalidOp(f"unknown field: {name!r}")
            fields[name] = _CHECKS[name](value)

    return Op(kind=cast(OpKind, kind), task=task, fields=fields)


def _move(path: Path, dest: Path) -> None:
    dest.mkdir(exist_ok=True)
    os.replace(path, dest / path.name)


class Queue:
    def __init__(self, dir: Path) -> None:
        self.dir = dir
        self.accepted_dir = dir / "accepted"
        self.failed_dir = dir / "failed"

    def pending(self) -> Iterator[tuple[Path, Op]]:
        """Ops in the Queue, oldest first. A file that cannot be read becomes a Failed op here."""
        for path in list_op_files(self.dir):
            try:
                op = parse_op(path)
            except InvalidOp as e:
                log.warning("failed op %s: %s", path.name, e)
                self.fail(path)
                continue
            yield path, op

    def accept(self, path: Path) -> None:
        _move(path, self.accepted_dir)

    def fail(self, path: Path) -> None:
        _move(path, self.failed_dir)

    def finish(self, task_key: Callable[[str], str], cached: Mapping[str, str | None]) -> list[Path]:
        """Call once the Cache shows the Accepted ops. Remove them, and each Failed op that no longer means
        anything. Return the removed files.

        task_key: names one task whether an op uses its local id or task id.
        cached: task id -> `updated` for every task in the Cache.
        """
        accepted = list_op_files(self.accepted_dir)
        newest = {key: p.name for p in accepted if (key := _key(p, task_key))}  # Name order: the last wins.
        stale = [p for p in list_op_files(self.failed_dir) if _is_stale(p, task_key, cached, newest)]
        for path in [*accepted, *stale]:
            path.unlink(missing_ok=True)
        return [*accepted, *stale]


def _key(path: Path, task_key: Callable[[str], str]) -> str | None:
    try:
        return task_key(parse_op(path).task)
    except InvalidOp:
        return None


def _is_stale(
    path: Path, task_key: Callable[[str], str], cached: Mapping[str, str | None], newest: Mapping[str, str]
) -> bool:
    """The one rule for when a Failed op goes. The Mac shows every Failed op, so it has no rule of its own.

    It goes when a later op for its task was accepted, the task left the Cache, or Google has a newer version.
    A failed create stays until a delete dismisses it: its task never reached Google.
    """
    try:
        op = parse_op(path)
    except InvalidOp:
        return False
    key = task_key(op.task)
    if path.name < newest.get(key, ""):
        return True
    if op.kind == "create":
        return False
    if key not in cached:
        return True
    updated = cached[key]
    return updated is not None and datetime.fromisoformat(updated) > _op_time(path)


def _op_time(path: Path) -> datetime:
    """When the Mac wrote the op, from its file name."""
    return datetime.fromtimestamp(int(path.name.split("-")[0]) / 1000, UTC)
