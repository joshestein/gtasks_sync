from datetime import timedelta
from pathlib import Path

import pytest

from gtasks_sync.state import MAP_TTL, Mapped, State, load_state

from .conftest import LOCAL_ID, NOW, OTHER_LOCAL_ID


def test_round_trip(state_path: Path) -> None:
    state = State(
        path=state_path,
        id_map={LOCAL_ID: Mapped("t1", NOW)},
        insert_attempts={OTHER_LOCAL_ID: NOW},
        applied={"1700000000000-abcd1234.json": "t1"},
    )
    state.save()
    assert load_state(state_path) == state


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{",
        '{"version": 99}',
        '{"version": 1, "id_map": {}, "insert_attempts": {}, "applied": []}',
        '{"version": 1, "id_map": {}, "insert_attempts": {}, "applied": null}',
        '{"version": 1, "id_map": {}, "insert_attempts": {}, "applied": {"a.json": 3}}',
        '{"version": 1, "id_map": {"local:1-00000000": {"task_id": null, "at": "2026-11-15T09:00:00+00:00"}},'
        ' "insert_attempts": {}, "applied": {}}',
    ],
)
def test_missing_or_bad_file_gives_empty_state(state_path: Path, content: str | None) -> None:
    if content is not None:
        state_path.write_text(content)
    assert load_state(state_path) == State(path=state_path)


def test_resolve_and_task_key(state: State) -> None:
    state.map(LOCAL_ID, "t1", NOW)
    assert state.resolve(LOCAL_ID) == "t1"
    assert state.resolve(OTHER_LOCAL_ID) is None
    assert state.resolve("abc123") == "abc123"
    assert state.task_key(LOCAL_ID) == "t1"
    assert state.task_key(OTHER_LOCAL_ID) == OTHER_LOCAL_ID


def test_map_clears_the_attempt_mark(state: State) -> None:
    state.insert_attempts[LOCAL_ID] = NOW
    state.map(LOCAL_ID, "t1", NOW)
    assert state.insert_attempts == {}
    assert state.local_ids() == {"t1": LOCAL_ID}


def test_prune_drops_old_entries_and_marks_no_op_names(state: State) -> None:
    old = NOW - MAP_TTL - timedelta(seconds=1)
    state.id_map = {LOCAL_ID: Mapped("t1", old), OTHER_LOCAL_ID: Mapped("t2", old), "local:1-00000000": Mapped("t3", NOW)}
    state.insert_attempts = {"local:2-00000000": NOW, "local:3-00000000": NOW}
    state.prune(NOW, referenced={OTHER_LOCAL_ID, "local:2-00000000"})
    assert set(state.id_map) == {OTHER_LOCAL_ID, "local:1-00000000"}
    assert set(state.insert_attempts) == {"local:2-00000000"}
