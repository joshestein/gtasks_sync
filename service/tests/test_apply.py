from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from gtasks_sync.api import AuthError, BadRequest, Transient, iso
from gtasks_sync.apply import ADOPT_SLACK, apply_queue
from gtasks_sync.queue import Queue, list_op_files
from gtasks_sync.state import State, load_state

from .conftest import LOCAL_ID, NOW, OTHER_LOCAL_ID, FakeApi, WriteOp, accepted

Run = Callable[..., list[Path]]


@pytest.fixture
def run(api: FakeApi, state: State, queue: Queue) -> Run:
    def run() -> list[Path]:
        """Apply, then finish as after a cache write. Return the removed files."""
        apply_queue(api, state, queue, NOW)
        return queue.finish(state.task_key)

    return run


@pytest.fixture
def replay_create(state: State, write_op: WriteOp) -> None:
    """A create for "milk" whose earlier insert attempt left a mark: the adopt path."""
    state.insert_attempts[LOCAL_ID] = NOW
    write_op("create", title="milk")


def failed_names(queue_dir: Path) -> list[str]:
    return [p.name for p in list_op_files(queue_dir / "failed")]


# create


def test_create_inserts_and_maps(api: FakeApi, state: State, state_path: Path, write_op: WriteOp, run: Run) -> None:
    path = write_op("create", title="milk", notes="oat", due="2026-11-20")
    assert run() == [accepted(path)]
    [task] = api.live()
    assert (task["title"], task["notes"], task["due"]) == ("milk", "oat", "2026-11-20T00:00:00.000Z")
    assert state.resolve(LOCAL_ID) == task["id"]
    assert state.insert_attempts == {}
    assert load_state(state_path) == state


def test_create_leaves_out_empty_notes_and_due(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    write_op("create", title="milk")
    run()
    assert api.calls == [("insert", {"title": "milk"})]


def test_create_already_mapped_is_skipped(api: FakeApi, state: State, write_op: WriteOp, run: Run) -> None:
    state.map(LOCAL_ID, "t9")
    write_op("create", title="milk")
    run()
    assert api.calls == []


def test_lost_insert_response_is_adopted_not_duplicated(
    api: FakeApi, state: State, state_path: Path, write_op: WriteOp, run: Run
) -> None:
    path = write_op("create", title="milk", due="2026-11-20")
    api.lose_insert_response = True
    with pytest.raises(Transient):
        run()
    assert load_state(state_path).insert_attempts == {LOCAL_ID: NOW}

    assert run() == [accepted(path)]

    [task] = api.live()
    assert state.resolve(LOCAL_ID) == task["id"]
    assert api.call_names() == ["insert", "list_updated_since"]
    assert api.calls[1][1] == NOW - ADOPT_SLACK


def test_mark_without_match_inserts(api: FakeApi, state: State, write_op: WriteOp, run: Run) -> None:
    """The insert never reached the server."""
    state.insert_attempts[LOCAL_ID] = NOW
    api.add(title="other")
    write_op("create", title="milk")
    run()
    assert sorted(t["title"] for t in api.live()) == ["milk", "other"]


@pytest.mark.usefixtures("replay_create")
def test_adopt_skips_mapped_deleted_and_different_tasks(api: FakeApi, state: State, run: Run) -> None:
    mapped = api.add(title="milk")
    api.add(title="milk", deleted=True)
    api.add(title="milk", notes="different")
    api.add(title="milk", due="2026-11-21T00:00:00.000Z")
    target = api.add(title="milk")
    state.map(OTHER_LOCAL_ID, mapped["id"])
    run()
    assert state.resolve(LOCAL_ID) == target["id"]
    assert "insert" not in api.call_names()


@pytest.mark.usefixtures("replay_create")
def test_adopt_ignores_completed_tasks_and_subtasks(api: FakeApi, run: Run) -> None:
    """An old "milk" completed in the same round must not take the place of a new "milk"."""
    api.add(title="milk", status="completed")
    parent = api.add(title="p")
    api.add(title="milk", parent=parent["id"])
    run()
    assert api.call_names() == ["list_updated_since", "insert"]


@pytest.mark.usefixtures("replay_create")
def test_two_matches_insert_instead_of_adopt(api: FakeApi, run: Run) -> None:
    """A wrong adopt loses the capture. A duplicate does not."""
    api.add(title="milk")
    api.add(title="milk")
    run()
    assert len(api.live()) == 3


@pytest.mark.usefixtures("replay_create")
def test_adopt_ignores_tasks_updated_before_the_mark(api: FakeApi, run: Run) -> None:
    api.add(title="milk", updated=iso(NOW - ADOPT_SLACK - timedelta(seconds=1)))
    run()
    assert api.call_names() == ["list_updated_since", "insert"]


# update, complete, uncomplete, delete


def test_update_patches_changed_fields_only(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    task = api.add(title="milk", notes="n", due="2026-11-20T00:00:00.000Z")
    write_op("update", task=task["id"], fields={"title": "oat milk", "due": None})
    run()
    assert api.calls == [("patch", task["id"], {"title": "oat milk", "due": None})]
    assert task["notes"] == "n"


def test_update_sets_due(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    task = api.add(title="milk")
    write_op("update", task=task["id"], fields={"due": "2026-12-01"})
    run()
    assert task["due"] == "2026-12-01T00:00:00.000Z"


def test_complete_sends_one_patch(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    """The API completes the subtasks itself (checked against the real server)."""
    task = api.add(title="p")
    write_op("complete", task=task["id"])
    run()
    assert api.calls == [("patch", task["id"], {"status": "completed"})]


def test_uncomplete(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    task = api.add(title="p", status="completed")
    write_op("uncomplete", task=task["id"])
    run()
    assert api.calls == [("patch", task["id"], {"status": "needsAction"})]


def test_delete(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    task = api.add(title="milk")
    write_op("delete", task=task["id"])
    run()
    assert api.live() == []


EXISTING_TASK_OPS = pytest.mark.parametrize(
    ("kind", "fields"),
    [("update", {"fields": {"title": "x"}}), ("complete", {}), ("uncomplete", {}), ("delete", {})],
)


@EXISTING_TASK_OPS
def test_op_on_task_deleted_elsewhere_is_skipped(
    api: FakeApi, write_op: WriteOp, queue_dir: Path, run: Run, kind: str, fields: dict[str, Any]
) -> None:
    task = api.add(title="milk", deleted=True)
    path = write_op(kind, task=task["id"], **fields)
    assert run() == [accepted(path)]
    assert failed_names(queue_dir) == []


@EXISTING_TASK_OPS
def test_op_on_missing_task_is_skipped(
    write_op: WriteOp, queue_dir: Path, run: Run, kind: str, fields: dict[str, Any]
) -> None:
    """404: the task is gone for good."""
    path = write_op(kind, task="gone", **fields)
    assert run() == [accepted(path)]
    assert failed_names(queue_dir) == []


def test_ops_on_a_local_id_use_the_mapped_task(api: FakeApi, write_op: WriteOp, run: Run) -> None:
    """Capture, edit, then complete, all before one sync."""
    write_op("create", title="milk")
    write_op("update", fields={"title": "oat milk"})
    write_op("complete")
    run()
    [task] = api.live()
    assert (task["title"], task["status"]) == ("oat milk", "completed")


# failures and replay


def test_op_on_unmapped_local_id_fails(write_op: WriteOp, queue_dir: Path, run: Run) -> None:
    """Its create failed earlier, so the task does not exist."""
    path = write_op("update", task=OTHER_LOCAL_ID, fields={"title": "x"})
    assert run() == []
    assert failed_names(queue_dir) == [path.name]


def test_delete_dismisses_a_failed_capture(api: FakeApi, write_op: WriteOp, queue_dir: Path, run: Run) -> None:
    """The create failed, so the task never reached Google. A delete removes the failed create."""
    api.fail["insert"] = BadRequest("400")
    create = write_op("create", title="milk")
    run()
    assert failed_names(queue_dir) == [create.name]

    delete = write_op("delete")
    assert run() == [accepted(delete), queue_dir / "failed" / create.name]
    assert api.calls == []


def test_bad_file_and_bad_request_fail_and_do_not_block(
    api: FakeApi, write_op: WriteOp, queue_dir: Path, run: Run
) -> None:
    task = api.add(title="milk")
    bad_file = write_op("create", raw="{")
    api.fail["patch"] = BadRequest("400")
    bad_request = write_op("update", task=task["id"], fields={"title": "x"})
    good = write_op("delete", task=task["id"])

    # The delete applied, so the older failed update for the same task goes with it.
    assert run() == [accepted(good), queue_dir / "failed" / bad_request.name]
    assert failed_names(queue_dir) == [bad_file.name]
    assert api.live() == []


@pytest.mark.parametrize("error", [Transient("timeout"), AuthError("revoked")])
def test_transient_or_auth_error_stops_the_round_and_keeps_later_ops(
    api: FakeApi, state: State, write_op: WriteOp, queue_dir: Path, run: Run, error: Exception
) -> None:
    task = api.add(title="milk")
    first = write_op("update", task=task["id"], fields={"title": "a"})
    second = write_op("complete", task=task["id"])
    third = write_op("delete", task=task["id"])
    api.fail["delete"] = error

    with pytest.raises(type(error)):
        run()
    assert list_op_files(queue_dir) == [third]
    assert list_op_files(queue_dir / "accepted") == [accepted(first), accepted(second)]

    api.calls.clear()
    assert run() == [accepted(first), accepted(second), accepted(third)]
    assert api.calls == [("delete", task["id"])]


def test_unexpected_error_stops_the_round_and_keeps_the_op(
    api: FakeApi, state: State, write_op: WriteOp, queue_dir: Path, run: Run
) -> None:
    """For example a full disk. The op could succeed later, so it must not become a failed op."""
    task = api.add(title="milk")
    path = write_op("delete", task=task["id"])
    api.fail["delete"] = OSError("disk full")
    with pytest.raises(OSError):
        run()
    assert list_op_files(queue_dir) == [path]
    assert failed_names(queue_dir) == []


def test_accepted_ops_are_not_sent_again(api: FakeApi, state: State, queue: Queue, write_op: WriteOp) -> None:
    """The round failed after the op applied: it waits in accepted/ for the next good round."""
    task = api.add(title="milk")
    write_op("update", task=task["id"], fields={"title": "a"})
    apply_queue(api, state, queue, NOW)
    api.calls.clear()

    apply_queue(api, state, queue, NOW)

    assert api.calls == []


def test_later_applied_op_removes_older_failed_op_for_same_task(
    api: FakeApi, state: State, write_op: WriteOp, queue_dir: Path, run: Run
) -> None:
    task = api.add(title="milk")
    state.map(LOCAL_ID, task["id"])
    api.fail["patch"] = BadRequest("400")
    write_op("update", task=LOCAL_ID, fields={"title": "x"})
    other = api.add(title="other")
    api.fail["delete"] = BadRequest("400")
    other_failed = write_op("delete", task=other["id"])
    run()
    [mine_failed_name, _] = failed_names(queue_dir)

    later = write_op("complete", task=task["id"])
    done = run()

    assert done == [accepted(later), queue_dir / "failed" / mine_failed_name]
    assert other_failed.name in failed_names(queue_dir)


def test_the_map_entry_is_saved_before_the_create_is_accepted(
    api: FakeApi, state: State, state_path: Path, queue: Queue, write_op: WriteOp
) -> None:
    path = write_op("create", title="milk")
    apply_queue(api, state, queue, NOW)
    assert accepted(path).exists()
    assert load_state(state_path).id_map == {LOCAL_ID: api.live()[0]["id"]}


def test_a_failed_create_drops_its_insert_mark(
    api: FakeApi, state: State, state_path: Path, queue: Queue, write_op: WriteOp
) -> None:
    state.insert_attempts[LOCAL_ID] = NOW
    api.add(title="milk")
    api.add(title="milk")  # Two matches: no adopt, so it inserts.
    api.fail["insert"] = BadRequest("400")
    write_op("create", title="milk")
    apply_queue(api, state, queue, NOW)
    assert load_state(state_path).insert_attempts == {}
