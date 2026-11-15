from pathlib import Path

import pytest

from gtasks_sync.state import State, load_state

from .conftest import LOCAL_ID, NOW, OTHER_LOCAL_ID


def test_round_trip(state_path: Path) -> None:
    state = State(path=state_path, id_map={LOCAL_ID: "t1"}, insert_attempts={OTHER_LOCAL_ID: NOW})
    state.save()
    assert load_state(state_path) == state


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{",
        '{"version": 99}',
        '{"version": 1, "id_map": {}, "insert_attempts": {}, "applied": {}}',  # The old format.
        '{"version": 2, "id_map": [], "insert_attempts": {}}',
        '{"version": 2, "id_map": null, "insert_attempts": {}}',
        '{"version": 2, "id_map": {"local:1-00000000": null}, "insert_attempts": {}}',
        '{"version": 2, "id_map": {}, "insert_attempts": {"local:1-00000000": "bad"}}',
    ],
)
def test_missing_or_bad_file_gives_empty_state(state_path: Path, content: str | None) -> None:
    if content is not None:
        state_path.write_text(content)
    assert load_state(state_path) == State(path=state_path)


def test_resolve_and_task_key(state: State) -> None:
    state.map(LOCAL_ID, "t1")
    assert state.resolve(LOCAL_ID) == "t1"
    assert state.resolve(OTHER_LOCAL_ID) is None
    assert state.resolve("abc123") == "abc123"
    assert state.task_key(LOCAL_ID) == "t1"
    assert state.task_key(OTHER_LOCAL_ID) == OTHER_LOCAL_ID


def test_map_clears_the_attempt_mark(state: State) -> None:
    state.insert_attempts[LOCAL_ID] = NOW
    state.map(LOCAL_ID, "t1")
    assert state.insert_attempts == {}
    assert state.local_ids() == {"t1": LOCAL_ID}


def test_keep_tasks(state: State) -> None:
    state.id_map = {LOCAL_ID: "t1", OTHER_LOCAL_ID: "t2"}
    assert state.keep_tasks({"t1", "t3"})
    assert state.id_map == {LOCAL_ID: "t1"}
    assert not state.keep_tasks({"t1"})
