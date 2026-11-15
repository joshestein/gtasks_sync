"""Apply queued ops to Google Tasks."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from gtasks_sync.api import Task, TasksApi, insert_body, patch_body, task_fields
from gtasks_sync.errors import OpFailed
from gtasks_sync.queue import InvalidOp, Op, failed_dir, list_op_files, move_to_failed, parse_op
from gtasks_sync.state import State

log = logging.getLogger(__name__)

# The adopt search starts this long before the attempt mark, for clock skew between Mac and server.
ADOPT_SLACK = timedelta(minutes=5)


class UnmappedLocalId(OpFailed):
    """An op names a local id whose create failed."""


def _matches(task: Task, fields: dict[str, str | None]) -> bool:
    """Could task be the insert whose response was lost? It is open and top-level, as every capture is."""
    return (
        task.get("status") == "needsAction"
        and task.get("parent") is None
        and task_fields(task) == (fields["title"], fields["notes"], fields["due"])
    )


def _create(api: TasksApi, state: State, op: Op, now: datetime) -> None:
    """Insert once per local id, even when an earlier insert succeeded but its response was lost (ADR 0001)."""
    local_id = op.task
    if local_id in state.id_map:
        return

    mark = state.insert_attempts.get(local_id)
    if mark is None:
        state.insert_attempts[local_id] = now
        state.save()
    else:
        mapped = state.local_ids()
        candidates = [
            t for t in api.list_updated_since(mark - ADOPT_SLACK) if t["id"] not in mapped and _matches(t, op.fields)
        ]
        # Two or more: a wrong adopt loses the capture, a duplicate does not. So insert.
        if len(candidates) == 1:
            state.map(local_id, candidates[0]["id"], now)
            log.warning("adopted task %s for %s after a lost insert", candidates[0]["id"], local_id)
            return

    created = api.insert(insert_body(op.fields))
    state.map(local_id, created["id"], now)


def apply_op(api: TasksApi, state: State, op: Op, now: datetime) -> None:
    """Apply one op. Every op is safe to send again. An op on a task deleted elsewhere has no effect."""
    if op.kind == "create":
        _create(api, state, op, now)
        return

    task_id = state.resolve(op.task)
    if task_id is None:
        if op.kind == "delete":
            # Its create failed, so the task never reached Google. This applied delete
            # also removes the failed create (done_files), so a failed capture can be dismissed.
            return
        raise UnmappedLocalId(op.task)
    match op.kind:
        case "update":
            api.patch(task_id, patch_body(op.fields))
        case "complete":
            # The API also completes the subtasks, as the Google apps do.
            api.patch(task_id, {"status": "completed"})
        case "uncomplete":
            api.patch(task_id, {"status": "needsAction"})
        case "delete":
            api.delete(task_id)


def done_files(queue_dir: Path, state: State) -> list[Path]:
    """Files to remove after the cache is written: applied ops, and failed ops older than an applied op
    for the same task. Without the second part, a failed op stays in the overlay for good."""
    applied = [p for p in list_op_files(queue_dir) if p.name in state.applied]
    # Files are in name order, so the last one per task is the newest.
    newest = {state.applied[p.name]: p.name for p in applied}
    if not newest:
        return applied  # Fast path: skip reading failed/.

    stale = []
    for path in list_op_files(failed_dir(queue_dir)):
        try:
            key = state.task_key(parse_op(path).task)
        except InvalidOp:
            continue
        if path.name < newest.get(key, ""):
            stale.append(path)
    return applied + stale


def apply_queue(api: TasksApi, state: State, queue_dir: Path, now: datetime) -> list[Path]:
    """Apply the queued ops that are not applied yet, in order. Return done_files().

    An op that can never succeed moves to failed/ and never blocks later ops.
    Any other error (network, auth, disk, a bug) stops the round: the op and all later ops stay for the next round.
    """
    for path in list_op_files(queue_dir):
        if path.name in state.applied:
            continue
        try:
            op = parse_op(path)
            apply_op(api, state, op, now)
        except OpFailed as e:
            log.warning("failed op %s: %s: %s", path.name, type(e).__name__, e)
            move_to_failed(path)
        else:
            state.applied[path.name] = state.task_key(op.task)
            state.save()
    return done_files(queue_dir, state)
