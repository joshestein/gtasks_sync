import json
import logging
from pathlib import Path

import pytest

from gtasks_sync.inbox import Inbox
from gtasks_sync.queue import Queue, list_op_files, parse_op

from .conftest import NOW


def put(inbox: Inbox, name: str, content: str) -> Path:
    path = inbox.dir / name
    path.write_text(content)
    return path


def ops(queue: Queue) -> list[tuple[str, dict[str, str | None]]]:
    return [(op.kind, op.fields) for _, op in queue.pending()]


def test_valid_file_becomes_one_create_op_and_is_deleted(inbox: Inbox, queue: Queue) -> None:
    put(
        inbox, "a.json", json.dumps({"text": " buy milk ", "captured_at": "2026-11-15T09:30:00+00:00", "capture": "n1"})
    )

    inbox.ingest(queue.dir, NOW)

    [path] = list_op_files(queue.dir)
    op = parse_op(path)
    assert (op.kind, op.fields) == ("create", {"title": "buy milk", "notes": "", "due": None})
    assert json.loads(path.read_text()) == {
        "op": "create",
        "task": op.task,
        "title": "buy milk",
        "notes": "",
        "due": None,
    }
    assert list(inbox.dir.iterdir()) == []


def test_unknown_fields_are_ignored(inbox: Inbox, queue: Queue) -> None:
    put(inbox, "a.json", json.dumps({"text": "milk", "priority": 3, "notes": "x", "due": "2026-11-20"}))
    inbox.ingest(queue.dir, NOW)
    assert ops(queue) == [("create", {"title": "milk", "notes": "", "due": None})]


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '"milk"', "{}", '{"text": ""}', '{"text": "  "}', '{"text": 3}'],
)
def test_bad_file_goes_to_failed_with_no_op(inbox: Inbox, queue: Queue, content: str) -> None:
    put(inbox, "bad.json", content)

    inbox.ingest(queue.dir, NOW)

    assert list_op_files(queue.dir) == []
    assert inbox.files() == []
    assert inbox.failed() == [inbox.failed_dir / "bad.json"]


def test_non_utf8_file_goes_to_failed(inbox: Inbox, queue: Queue) -> None:
    (inbox.dir / "bad.json").write_bytes(b'{"text": "\xff"}')
    inbox.ingest(queue.dir, NOW)
    assert inbox.failed() == [inbox.failed_dir / "bad.json"]


def test_other_names_are_ignored(inbox: Inbox, queue: Queue) -> None:
    names = ["a.json.part", "a.txt", "a.json.tmp", "json"]
    for name in names:
        put(inbox, name, '{"text": "milk"}')

    inbox.ingest(queue.dir, NOW)

    assert list_op_files(queue.dir) == []
    assert sorted(p.name for p in inbox.dir.iterdir()) == sorted(names)


def test_bad_file_does_not_block_later_files(inbox: Inbox, queue: Queue) -> None:
    put(inbox, "a.json", '{"text": "first"}')
    put(inbox, "b.json", "{")
    put(inbox, "c.json", '{"text": "third"}')

    inbox.ingest(queue.dir, NOW)

    assert [f["title"] for _, f in ops(queue)] == ["first", "third"]  # Name order.
    assert inbox.files() == []
    assert inbox.failed() == [inbox.failed_dir / "b.json"]


def test_queue_write_error_keeps_the_file_for_the_next_round(inbox: Inbox, queue: Queue) -> None:
    put(inbox, "a.json", '{"text": "milk"}')

    inbox.ingest(queue.dir / "missing", NOW)
    assert inbox.files() == [inbox.dir / "a.json"]

    inbox.ingest(queue.dir, NOW)
    assert len(list_op_files(queue.dir)) == 1
    assert inbox.files() == []


def test_file_that_cannot_be_deleted_makes_only_one_op(
    inbox: Inbox, queue: Queue, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = put(inbox, "a.json", '{"text": "milk"}')

    def deny(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "unlink", deny)
    with caplog.at_level(logging.ERROR):
        inbox.ingest(queue.dir, NOW)
        inbox.ingest(queue.dir, NOW)

    assert len(list_op_files(queue.dir)) == 1
    assert path.exists()
    assert "cannot remove inbox file a.json" in caplog.text


def test_missing_inbox_dir_does_nothing(tmp_path: Path, queue: Queue) -> None:
    Inbox(tmp_path / "none").ingest(queue.dir, NOW)
    assert list_op_files(queue.dir) == []
