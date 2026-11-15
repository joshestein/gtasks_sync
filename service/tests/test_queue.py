from pathlib import Path
from typing import Any

import pytest

from gtasks_sync.queue import InvalidOp, Op, Queue, list_op_files, parse_op

from .conftest import LOCAL_ID, OTHER_LOCAL_ID, WriteOp, accepted


def test_lists_in_name_order_and_skips_other_files(queue_dir: Path, write_op: WriteOp) -> None:
    first = write_op("create", title="a")
    second = write_op("delete")
    (queue_dir / ".1700000000005-ffff0000.json.tmp").write_text("{}")
    (queue_dir / ".hidden.json").write_text("{}")
    (queue_dir / "tasks.json").write_text("{}")
    (queue_dir / "failed").mkdir()
    assert list_op_files(queue_dir) == [first, second]


def test_parses_create_with_defaults(write_op: WriteOp) -> None:
    assert parse_op(write_op("create", title="milk")) == Op(
        kind="create", task=LOCAL_ID, fields={"title": "milk", "notes": "", "due": None}
    )


def test_title_is_stripped(write_op: WriteOp) -> None:
    assert parse_op(write_op("create", title=" milk \n")).fields["title"] == "milk"
    assert parse_op(write_op("update", task="abc123", fields={"title": " x "})).fields == {"title": "x"}


def test_parses_create_with_all_fields(write_op: WriteOp) -> None:
    op = parse_op(write_op("create", title="milk", notes="oat", due="2026-11-20"))
    assert op.fields == {"title": "milk", "notes": "oat", "due": "2026-11-20"}


def test_parses_update_with_changed_fields_only(write_op: WriteOp) -> None:
    op = parse_op(write_op("update", task="abc123", fields={"title": "x", "due": None}))
    assert op == Op(kind="update", task="abc123", fields={"title": "x", "due": None})


@pytest.mark.parametrize("kind", ["complete", "uncomplete", "delete"])
def test_parses_ops_without_fields(write_op: WriteOp, kind: str) -> None:
    assert parse_op(write_op(kind, task="abc123", title="ignored")) == Op(kind=kind, task="abc123")  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("op", "task", "raw", "fields"),
    [
        ("create", LOCAL_ID, "{not json", {}),
        ("create", LOCAL_ID, "[]", {}),
        ("archive", LOCAL_ID, None, {}),
        ("delete", "", None, {}),
        ("create", "abc123", None, {"title": "x"}),  # create needs a local id
        ("delete", "local:bad", None, {}),
        ("create", LOCAL_ID, None, {}),  # no title
        ("create", LOCAL_ID, None, {"title": "  "}),
        ("create", LOCAL_ID, None, {"title": "x", "notes": None}),
        ("create", LOCAL_ID, None, {"title": "x", "due": "2026-13-01"}),
        ("create", LOCAL_ID, None, {"title": "x", "due": "2026-11-20T00:00:00Z"}),
        ("update", "abc123", None, {}),
        ("update", "abc123", None, {"fields": {}}),
        ("update", "abc123", None, {"fields": {"status": "completed"}}),
        ("update", "abc123", None, {"fields": {"title": ""}}),
    ],
)
def test_rejects_invalid(write_op: WriteOp, op: str, task: str, raw: str | None, fields: dict[str, Any]) -> None:
    with pytest.raises(InvalidOp):
        parse_op(write_op(op, task=task, raw=raw, **fields))


def test_pending_moves_unreadable_files_to_failed(queue: Queue, write_op: WriteOp) -> None:
    bad = write_op("create", raw="{")
    good = write_op("delete")
    assert [(p, op.kind) for p, op in queue.pending()] == [(good, "delete")]
    assert list_op_files(queue.failed_dir) == [queue.failed_dir / bad.name]


def test_accept_and_fail_move_the_file(queue: Queue, write_op: WriteOp) -> None:
    first = write_op("delete")
    second = write_op("delete")
    queue.accept(first)
    queue.fail(second)
    assert list_op_files(queue.dir) == []
    assert list_op_files(queue.accepted_dir) == [accepted(first)]
    assert list_op_files(queue.failed_dir) == [queue.failed_dir / second.name]


def same(task: str) -> str:
    return task


def test_finish_removes_accepted_ops_and_older_failed_ops_for_the_same_task(queue: Queue, write_op: WriteOp) -> None:
    old_failed = write_op("update", task=LOCAL_ID, fields={"title": "x"})
    other_failed = write_op("update", task=OTHER_LOCAL_ID, fields={"title": "x"})
    unreadable_failed = write_op("delete", raw="{")
    for path in (old_failed, other_failed, unreadable_failed):
        queue.fail(path)
    done = write_op("delete")
    queue.accept(done)
    newer_failed = write_op("update", task=LOCAL_ID, fields={"title": "y"})
    queue.fail(newer_failed)

    removed = queue.finish(same)

    assert removed == [accepted(done), queue.failed_dir / old_failed.name]
    assert list_op_files(queue.accepted_dir) == []
    assert [p.name for p in list_op_files(queue.failed_dir)] == sorted(
        [other_failed.name, unreadable_failed.name, newer_failed.name]
    )
