"""Check the API behaviors the design depends on, against the real default task list.

Run after `gtasks-sync setup`:  uv run python scripts/check_api.py
It makes a few tasks named "gtasks-sync check ...", then deletes them.
"""

import sys
from datetime import UTC, datetime, timedelta

from gtasks_sync.api import ApiError, HttpTasksApi, NotFound, Task, due_from_api, due_to_api
from gtasks_sync.auth import open_api
from gtasks_sync.keychain import read_secrets

PREFIX = "gtasks-sync check"


class Checks:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.count = 0

    def check(self, name: str, ok: bool, seen: object) -> None:
        self.count += 1
        if not ok:
            self.failed.append(name)
        print(f"{'PASS' if ok else 'FAIL'}  {name}  (seen: {seen!r})", flush=True)


def get(api: HttpTasksApi, task_id: str) -> Task:
    return api.call("GET", task_id)


def run(api: HttpTasksApi, checks: Checks, created: list[str]) -> None:
    start = datetime.now(UTC)
    completed_min = start - timedelta(hours=1)
    check = checks.check

    # Round trips. Adoption (ADR 0001) needs title and notes back exactly as sent.
    title = f"{PREFIX} title"
    notes = "line 1\nline 2\n  indented ✓ é"
    task = api.insert({"title": title, "notes": notes, "due": due_to_api("2026-12-01")})
    created.append(task["id"])
    check("title round trip", task.get("title") == title, task.get("title"))
    check("notes round trip", task.get("notes") == notes, task.get("notes"))
    check("due date round trip", due_from_api(task.get("due")) == "2026-12-01", task.get("due"))
    check("webViewLink present", bool(task.get("webViewLink")), task.get("webViewLink"))
    top = min(t["position"] for t in api.list_open() if not t.get("parent"))
    check("a new task goes to the top", task.get("position") == top, (task.get("position"), top))

    patched = api.call("PATCH", task["id"], body={"due": None})
    check("patch due=null clears due", "due" not in patched, patched.get("due"))

    # completedMin and open tasks
    listed = {t["id"] for t in api.list_completed_since(completed_min)}
    check("completedMin leaves out open tasks", task["id"] not in listed, task["id"] in listed)
    api.patch(task["id"], {"status": "completed"})
    listed = {t["id"] for t in api.list_completed_since(completed_min)}
    check("completedMin includes a task completed now", task["id"] in listed, task["id"] in listed)
    check(
        "list_open leaves out completed tasks",
        task["id"] not in {t["id"] for t in api.list_open()},
        "completed task listed as open",
    )

    # Uncomplete
    reopened = api.call("PATCH", task["id"], body={"status": "needsAction"})
    check("uncomplete without completed=null clears completed", "completed" not in reopened, reopened.get("completed"))

    # Subtasks
    parent = api.insert({"title": f"{PREFIX} parent"})
    created.append(parent["id"])
    child = api.call("POST", params={"parent": parent["id"]}, body={"title": f"{PREFIX} child"})
    created.append(child["id"])
    check("child has parent", child.get("parent") == parent["id"], child.get("parent"))
    api.patch(parent["id"], {"status": "completed"})
    child_after = get(api, child["id"])
    check(
        "completing a parent completes its subtask (so the service does not)",
        child_after.get("status") == "completed",
        child_after.get("status"),
    )

    # Deleted tasks
    api.delete(child["id"])
    updated = {t["id"] for t in api.list_updated_since(start - timedelta(minutes=5))}
    check("list_updated_since includes a new task", task["id"] in updated, task["id"] in updated)
    check("list_updated_since leaves out deleted tasks", child["id"] not in updated, child["id"] in updated)
    after = api.call("PATCH", child["id"], body={"title": f"{PREFIX} child edited"})
    check("patch on a deleted task succeeds and returns deleted: true", after.get("deleted") is True, after.get("deleted"))
    api.call("DELETE", child["id"])
    check("delete of a deleted task is not an error", True, "no error")

    # Deleting a parent deletes its subtasks
    parent2 = api.insert({"title": f"{PREFIX} parent 2"})
    created.append(parent2["id"])
    child2 = api.call("POST", params={"parent": parent2["id"]}, body={"title": f"{PREFIX} child 2"})
    created.append(child2["id"])
    api.delete(parent2["id"])
    try:
        child2_after = get(api, child2["id"])
        check("deleting a parent deletes its subtask", bool(child2_after.get("deleted")), child2_after)
    except NotFound:
        check("deleting a parent deletes its subtask", True, "404")


def main() -> None:
    api = open_api(read_secrets())
    checks = Checks()
    created: list[str] = []
    try:
        run(api, checks, created)
    finally:
        left = []
        for task_id in created:
            try:
                api.delete(task_id)  # A second delete is not an error.
            except ApiError as e:
                left.append(f"{task_id} ({type(e).__name__})")
        print(f"\nCleaned up {len(created) - len(left)} of {len(created)} tasks.")
        if left:
            print(f"Delete these by hand: {', '.join(left)}")
    print(f"{checks.count - len(checks.failed)} passed, {len(checks.failed)} failed.")
    if checks.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
