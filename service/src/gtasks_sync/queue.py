"""The op queue: one JSON file per op in the queue directory (ADR 0002)."""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast, get_args

from gtasks_sync.errors import OpFailed

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


def failed_dir(queue_dir: Path) -> Path:
    return queue_dir / "failed"


def move_to_failed(path: Path) -> None:
    dest = failed_dir(path.parent)
    dest.mkdir(exist_ok=True)
    os.replace(path, dest / path.name)


def remove_ops(paths: list[Path]) -> None:
    for p in paths:
        p.unlink(missing_ok=True)
