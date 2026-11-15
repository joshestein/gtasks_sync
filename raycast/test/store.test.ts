import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import {
  CachedTask,
  changedFields,
  createTask,
  loadTasks,
  mintLocalId,
  Op,
  OP_FILE,
  overlay,
  QueuedOp,
  readOps,
  requestSync,
  setCompleted,
  SYNC_NOW_FILE,
  syncWarning,
  Task,
  updateTask,
  writeOp,
} from "../src/lib/store";

const cached = (id: string, fields: Partial<CachedTask> = {}): CachedTask => ({
  id,
  local_id: null,
  parent: null,
  position: "00000000000000000001",
  title: id,
  notes: "",
  due: null,
  status: "needsAction",
  completed: null,
  updated: "2026-11-01T00:00:00.000Z",
  url: `https://tasks.google.com/task/${id}`,
  ...fields,
});

const AT = Date.parse("2026-11-15T12:00:00.000Z");
let counter = 0;
const queued = (op: Op, at = AT): QueuedOp => ({ name: `${at}-${(counter++).toString(16)}.json`, at, op });
const LOCAL = "local:1763208000000-3f9a0c1e";
const byId = (tasks: Task[]) => Object.fromEntries(tasks.map((t) => [t.id, t]));

describe("mintLocalId", () => {
  it("matches the service's LOCAL_ID_RE", () => {
    expect(mintLocalId(1763208000000)).toMatch(/^local:1763208000000-[0-9a-f]{8}$/);
    expect(mintLocalId()).not.toBe(mintLocalId());
  });
});

describe("files", () => {
  let dir: string;
  const queue = () => join(dir, "queue");
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "gtasks-"));
  });

  it("writes one op per file with no temp file left", () => {
    createTask("  milk  ", "oat", "2026-11-20", dir);
    const [name, ...rest] = readdirSync(queue());
    expect(rest).toEqual([]);
    expect(name).toMatch(OP_FILE);
    const op = JSON.parse(readFileSync(join(queue(), name), "utf8"));
    expect(op).toMatchObject({ op: "create", title: "milk", notes: "oat", due: "2026-11-20" });
    expect(op.task).toMatch(/^local:\d+-[0-9a-f]{8}$/);
  });

  it("never names an op before the newest pending op, also one already accepted", () => {
    mkdirSync(join(queue(), "accepted"), { recursive: true });
    writeFileSync(join(queue(), "accepted", "5000-aaaaaaaa.json"), JSON.stringify({ op: "delete", task: "t1" }));
    writeOp({ op: "delete", task: "t2" }, dir, 1000); // The clock stepped back.
    writeOp({ op: "delete", task: "t3" }, dir, 1000);
    const names = readdirSync(queue())
      .filter((n) => OP_FILE.test(n))
      .sort();
    expect(names.map((n) => Number(n.split("-")[0]))).toEqual([5001, 5002]);
  });

  it("reads ops in name order and skips temp, unreadable, and other files", () => {
    mkdirSync(queue());
    writeFileSync(join(queue(), "2-bb.json"), JSON.stringify({ op: "delete", task: "b" }));
    writeFileSync(join(queue(), "1-aa.json"), JSON.stringify({ op: "delete", task: "a" }));
    writeFileSync(join(queue(), ".3-cc.json.tmp"), "{}");
    writeFileSync(join(queue(), "4-dd.json"), "{");
    writeFileSync(join(queue(), SYNC_NOW_FILE), "");
    expect(readOps(queue()).map((q) => [q.at, q.op.task])).toEqual([
      [1, "a"],
      [2, "b"],
    ]);
    expect(readOps(join(dir, "missing"))).toEqual([]);
  });

  it("requestSync touches the sync-now file", () => {
    requestSync(dir);
    expect(readdirSync(queue())).toEqual([SYNC_NOW_FILE]);
  });

  it("loadTasks reads the cache and the queue, accepted, and failed ops", () => {
    writeFileSync(
      join(dir, "cache.json"),
      JSON.stringify({ version: 1, synced_at: null, last_attempt_at: null, error: null, tasks: [cached("t1")] }),
    );
    mkdirSync(join(queue(), "accepted"), { recursive: true });
    mkdirSync(join(queue(), "failed"));
    writeFileSync(
      join(queue(), "accepted", "1-aa.json"),
      JSON.stringify({ op: "update", task: "t1", fields: { title: "a" } }),
    );
    writeFileSync(join(queue(), "2-bb.json"), JSON.stringify({ op: "update", task: "t1", fields: { notes: "b" } }));
    writeFileSync(
      join(queue(), "failed", "0-cc.json"),
      JSON.stringify({ op: "create", task: LOCAL, title: "x", notes: "", due: null }),
    );
    const { tasks, status } = loadTasks(dir);
    expect(status?.error).toBeNull();
    const t = byId(tasks);
    expect([t.t1.title, t.t1.notes, t.t1.state]).toEqual(["a", "b", "pending"]);
    expect(t[LOCAL].state).toBe("failed");
  });

  it("loadTasks ignores a cache of another version", () => {
    writeFileSync(join(dir, "cache.json"), JSON.stringify({ version: 99, tasks: [cached("t1")] }));
    expect(loadTasks(dir)).toEqual({ tasks: [], status: null });
  });

  it("updateTask writes only changed fields, and nothing when nothing changed", () => {
    const task: Task = { ...cached("t1", { title: "milk", notes: "n", due: "2026-11-20" }), state: "synced" };
    expect(updateTask(task, { title: " milk ", notes: "n", due: "2026-11-20" }, dir)).toBe(false);
    expect(updateTask(task, { title: "milk", notes: "n", due: null }, dir)).toBe(true);
    setCompleted(task, true, dir);
    const ops = readOps(queue()).map((q) => q.op);
    expect(ops).toEqual([
      { op: "update", task: "t1", fields: { due: null } },
      { op: "complete", task: "t1" },
    ]);
  });
});

describe("changedFields", () => {
  const task: Task = { ...cached("t1", { title: "milk", notes: "", due: null }), state: "synced" };
  it("compares the trimmed title", () => {
    expect(changedFields(task, { title: "oat milk ", notes: "", due: "2026-11-20" })).toEqual({
      title: "oat milk",
      due: "2026-11-20",
    });
  });
});

describe("overlay", () => {
  it("shows a capture at once, at the top of Google's order", () => {
    const [task] = overlay([], [queued({ op: "create", task: LOCAL, title: "milk", notes: "", due: null })], []);
    expect(task).toMatchObject({ id: LOCAL, local_id: LOCAL, title: "milk", position: "", state: "pending" });
  });

  it("does not show a capture twice once the cache has it", () => {
    const tasks = overlay(
      [cached("t1", { local_id: LOCAL })],
      [queued({ op: "create", task: LOCAL, title: "milk", notes: "", due: null })],
      [],
    );
    expect(tasks.map((t) => t.id)).toEqual(["t1"]);
  });

  it("matches ops by task id or local id", () => {
    const tasks = overlay(
      [cached("t1", { local_id: LOCAL })],
      [
        queued({ op: "update", task: LOCAL, fields: { title: "a" } }),
        queued({ op: "update", task: "t1", fields: { notes: "b" } }),
      ],
      [],
    );
    expect(tasks[0]).toMatchObject({ title: "a", notes: "b", state: "pending" });
  });

  it("an update changes only its fields", () => {
    const [task] = overlay(
      [cached("t1", { notes: "keep", due: "2026-11-20" })],
      [queued({ op: "update", task: "t1", fields: { due: null } })],
      [],
    );
    expect(task).toMatchObject({ notes: "keep", due: null });
  });

  it("complete also completes the subtasks; uncomplete reopens only the task", () => {
    const tasks = [cached("p"), cached("c", { parent: "p" }), cached("other")];
    const done = byId(overlay(tasks, [queued({ op: "complete", task: "p" })], []));
    expect([done.p.status, done.c.status, done.other.status]).toEqual(["completed", "completed", "needsAction"]);
    expect(done.p.completed).toBe(new Date(AT).toISOString());

    const reopened = byId(
      overlay(tasks, [queued({ op: "complete", task: "p" }), queued({ op: "uncomplete", task: "p" })], []),
    );
    expect([reopened.p.status, reopened.p.completed, reopened.c.status]).toEqual(["needsAction", null, "completed"]);
  });

  it("delete hides the task and its subtasks", () => {
    const tasks = overlay(
      [cached("p"), cached("c", { parent: "p" }), cached("other")],
      [queued({ op: "delete", task: "p" })],
      [],
    );
    expect(tasks.map((t) => t.id)).toEqual(["other"]);
  });

  it("ignores ops on a task that is not there", () => {
    expect(overlay([], [queued({ op: "complete", task: "gone" })], [])).toEqual([]);
  });

  it("shows a failed capture and lets a later delete dismiss it", () => {
    const create = queued({ op: "create", task: LOCAL, title: "milk", notes: "", due: null });
    expect(overlay([], [], [create])[0].state).toBe("failed");
    expect(overlay([], [queued({ op: "delete", task: LOCAL })], [create])).toEqual([]);
  });

  it("shows a failed edit's content, but only while the cache is not newer", () => {
    const edit = queued({ op: "update", task: "t1", fields: { title: "x" } }, Date.parse("2026-11-10T00:00:00.000Z"));
    expect(overlay([cached("t1")], [], [edit])[0]).toMatchObject({ title: "x", state: "failed" });
    expect(overlay([cached("t1", { updated: "2026-11-12T00:00:00.000Z" })], [], [edit])[0]).toMatchObject({
      title: "t1",
      state: "synced",
    });
  });

  it("a failed complete or delete only marks the task", () => {
    const [task] = overlay([cached("t1")], [], [queued({ op: "delete", task: "t1" })]);
    expect(task).toMatchObject({ id: "t1", status: "needsAction", state: "failed" });
  });
});

describe("syncWarning", () => {
  const ok = { synced_at: new Date(AT).toISOString(), last_attempt_at: null, error: null };
  it("is null when sync is healthy", () => {
    expect(syncWarning(ok, AT + 60_000)).toBeNull();
  });
  it("names setup for an auth error", () => {
    expect(syncWarning({ ...ok, error: { kind: "auth", message: "x" } })).toContain("gtasks-sync setup");
  });
  it("warns when there is no sync or it is old", () => {
    expect(syncWarning(null)).toContain("No sync yet");
    expect(syncWarning(ok, AT + 11 * 60_000)).toBe("Last sync 11 min ago.");
  });
});
