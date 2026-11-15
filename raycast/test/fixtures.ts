import type { CachedTask, Op, StagedOp, Task } from "../src/lib/store";

export const cached = (id: string, fields: Partial<CachedTask> = {}): CachedTask => ({
  id,
  local_id: null,
  parent: null,
  position: "00000000000000000005",
  title: id,
  notes: "",
  due: null,
  status: "needsAction",
  completed: null,
  updated: "2026-11-01T00:00:00.000Z",
  url: `https://tasks.google.com/task/${id}`,
  ...fields,
});

export const task = (id: string, fields: Partial<Task> = {}): Task => ({ ...cached(id), state: "synced", ...fields });

export const AT = Date.parse("2026-11-15T12:00:00.000Z");
let counter = 0;

/** An op as readOps returns it. Each call sorts after the one before. */
export const staged = (op: Op, state: StagedOp["state"] = "pending", at = AT): StagedOp => ({
  name: `${at}-${(counter++).toString(16).padStart(8, "0")}.json`,
  at,
  op,
  state,
});
