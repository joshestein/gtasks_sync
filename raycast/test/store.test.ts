import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import {
  createTask,
  loadTasks,
  mintLocalId,
  OP_FILE,
  overlay,
  readOps,
  requestSync,
  setCompleted,
  SYNC_NOW_FILE,
  syncWarning,
  Task,
  updateTask,
  writeOp,
} from "../src/lib/store";
import { AT, cached, staged, task } from "./fixtures";

const LOCAL = "local:1763208000000-3f9a0c1e";
const byId = (tasks: Task[]) => Object.fromEntries(tasks.map((t) => [t.id, t]));
const create = { op: "create", task: LOCAL, title: "milk", notes: "", due: null } as const;

describe("mintLocalId", () => {
  it("matches the service's LOCAL_ID_RE", () => {
    expect(mintLocalId(1763208000000)).toMatch(/^local:1763208000000-[0-9a-f]{8}$/);
    expect(mintLocalId()).not.toBe(mintLocalId());
  });
});

describe("files", () => {
  let dir: string;
  const queue = (...sub: string[]) => join(dir, "queue", ...sub);
  const put = (sub: string, name: string, body: unknown) => {
    mkdirSync(queue(sub), { recursive: true });
    writeFileSync(join(queue(sub), name), typeof body === "string" ? body : JSON.stringify(body));
  };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "gtasks-"));
  });

  it("writes one op per file, title trimmed, with no temp file left", () => {
    createTask({ title: "  milk  ", notes: "oat", due: "2026-11-20" }, dir);
    const [name, ...rest] = readdirSync(queue());
    expect(rest).toEqual([]);
    expect(name).toMatch(OP_FILE);
    const op = JSON.parse(readFileSync(queue(name), "utf8"));
    expect(op).toMatchObject({ op: "create", title: "milk", notes: "oat", due: "2026-11-20" });
    expect(op.task).toMatch(/^local:\d+-[0-9a-f]{8}$/);
  });

  it("never names an op before the newest pending op, also one already accepted", () => {
    put("accepted", "5000-aaaaaaaa.json", { op: "delete", task: "t1" });
    writeOp({ op: "delete", task: "t2" }, dir, 1000); // The clock stepped back.
    writeOp({ op: "delete", task: "t3" }, dir, 1000);
    const times = readdirSync(queue())
      .filter((n) => OP_FILE.test(n))
      .map((n) => Number(n.split("-")[0]))
      .sort();
    expect(times).toEqual([5001, 5002]);
  });

  it("reads all three stages in name order and skips temp, unreadable, and other files", () => {
    put("", "3-cc.json", { op: "delete", task: "c" });
    put("accepted", "2-bb.json", { op: "delete", task: "b" });
    put("failed", "1-aa.json", { op: "delete", task: "a" });
    put("", ".4-dd.json.tmp", "{}");
    put("", "5-ee.json", "{");
    put("", SYNC_NOW_FILE, "");
    expect(readOps(dir).map((s) => [s.at, s.op.task, s.state])).toEqual([
      [1, "a", "failed"],
      [2, "b", "pending"],
      [3, "c", "pending"],
    ]);
    expect(readOps(join(dir, "missing"))).toEqual([]);
  });

  it("names a new op after a failed op too", () => {
    put("failed", "5000-aaaaaaaa.json", { op: "delete", task: "t1" });
    writeOp({ op: "delete", task: "t2" }, dir, 1000);
    expect(readdirSync(queue()).filter((n) => OP_FILE.test(n))[0]).toMatch(/^5001-/);
  });

  it("skips ops with a bad shape, so a bad file in failed/ cannot break the list", () => {
    put("failed", "1-aa.json", "null");
    put("failed", "2-bb.json", { op: "create", task: LOCAL, notes: "", due: null }); // No title.
    put("failed", "3-cc.json", { op: "update", task: "t1", fields: { due: "tomorrow" } });
    put("failed", "4-dd.json", { op: "archive", task: "t1" });
    put("failed", "99999999999999999-ee.json", { op: "delete", task: "t1" }); // Not a valid date.
    put("failed", "5-ff.json", { op: "update", task: "t1", fields: { title: "ok", due: null } });
    expect(readOps(dir).map((s) => s.name)).toEqual(["5-ff.json"]);
  });

  it("requestSync touches the sync-now file", () => {
    requestSync(dir);
    expect(readdirSync(queue())).toEqual([SYNC_NOW_FILE]);
  });

  it("loadTasks reads the cache and every stage", () => {
    writeFileSync(
      join(dir, "cache.json"),
      JSON.stringify({ version: 1, synced_at: null, last_attempt_at: null, error: null, tasks: [cached("t1")] }),
    );
    put("accepted", "1-aa.json", { op: "update", task: "t1", fields: { title: "a" } });
    put("", "2-bb.json", { op: "update", task: "t1", fields: { notes: "b" } });
    put("failed", "0-cc.json", create);
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

  it("updateTask writes only changed fields, compares the trimmed title, and writes nothing when nothing changed", () => {
    const milk = task("t1", { title: "milk", notes: "n", due: "2026-11-20" });
    expect(updateTask(milk, { title: " milk ", notes: "n", due: "2026-11-20" }, dir)).toBe(false);
    expect(updateTask(milk, { title: "oat milk ", notes: "n", due: null }, dir)).toBe(true);
    setCompleted(milk, true, dir);
    expect(readOps(dir).map((s) => s.op)).toEqual([
      { op: "update", task: "t1", fields: { title: "oat milk", due: null } },
      { op: "complete", task: "t1" },
    ]);
  });
});

describe("updateTask on a failed task", () => {
  it("sends every field, so a save retries the failed edit", () => {
    const dir = mkdtempSync(join(tmpdir(), "gtasks-"));
    const failed = task("t1", { title: "x", notes: "n", due: null, state: "failed" });
    expect(updateTask(failed, { title: "x", notes: "n", due: null }, dir)).toBe(true);
    expect(readOps(dir)[0].op).toEqual({ op: "update", task: "t1", fields: { title: "x", notes: "n", due: null } });
  });
});

describe("overlay", () => {
  it("shows a capture at once, at the top of Google's order", () => {
    const [shown] = overlay([], [staged(create)]);
    expect(shown).toMatchObject({ id: LOCAL, local_id: LOCAL, title: "milk", position: "", state: "pending" });
  });

  it("does not show a capture twice once the cache has it", () => {
    const tasks = overlay([cached("t1", { local_id: LOCAL })], [staged(create)]);
    expect(tasks.map((t) => t.id)).toEqual(["t1"]);
  });

  it("matches ops by task id or local id, and an update changes only its fields", () => {
    const tasks = overlay(
      [cached("t1", { local_id: LOCAL, due: "2026-11-20" })],
      [
        staged({ op: "update", task: LOCAL, fields: { title: "a" } }),
        staged({ op: "update", task: "t1", fields: { notes: "b" } }),
      ],
    );
    expect(tasks[0]).toMatchObject({ title: "a", notes: "b", due: "2026-11-20", state: "pending" });
  });

  it("complete also completes the subtasks; uncomplete reopens only the task", () => {
    const tasks = [cached("p"), cached("c", { parent: "p" }), cached("other")];
    const done = byId(overlay(tasks, [staged({ op: "complete", task: "p" })]));
    expect([done.p.status, done.c.status, done.other.status]).toEqual(["completed", "completed", "needsAction"]);
    expect(done.p.completed).toBe(new Date(AT).toISOString());

    const reopened = byId(
      overlay(tasks, [staged({ op: "complete", task: "p" }), staged({ op: "uncomplete", task: "p" })]),
    );
    expect([reopened.p.status, reopened.p.completed, reopened.c.status]).toEqual(["needsAction", null, "completed"]);
  });

  it("delete hides the task and its subtasks", () => {
    const tasks = overlay(
      [cached("p"), cached("c", { parent: "p" }), cached("other")],
      [staged({ op: "delete", task: "p" })],
    );
    expect(tasks.map((t) => t.id)).toEqual(["other"]);
  });

  it("ignores ops on a task that is not there", () => {
    expect(overlay([], [staged({ op: "complete", task: "gone" })])).toEqual([]);
  });

  it("shows a failed capture, and a later delete dismisses it", () => {
    const failed = staged(create, "failed");
    expect(overlay([], [failed])[0].state).toBe("failed");
    expect(overlay([], [failed, staged({ op: "delete", task: LOCAL })])).toEqual([]);
  });

  it("shows a failed edit's content; a failed complete or delete only marks the task", () => {
    expect(
      overlay([cached("t1")], [staged({ op: "update", task: "t1", fields: { title: "x" } }, "failed")])[0],
    ).toMatchObject({
      title: "x",
      state: "failed",
    });
    expect(overlay([cached("t1")], [staged({ op: "delete", task: "t1" }, "failed")])[0]).toMatchObject({
      status: "needsAction",
      state: "failed",
    });
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
