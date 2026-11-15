/**
 * Local files shared with the gtasks-sync service. This module never touches the network.
 * The extension writes only op files (into queue/) and the sync-now file. The service writes everything else.
 *
 * The directory an op file is in is its stage (ADR 0002): queue/ (not yet accepted by Google),
 * queue/accepted/ (accepted, the cache does not show it yet), queue/failed/ (can never succeed).
 */
import { randomBytes } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const APP_DIR = join(homedir(), "Library", "Application Support", "gtasks-sync");

/** For messages only. Must match LOG_FILE in service/src/gtasks_sync/paths.py. */
export const LOG_FILE = "~/Library/Logs/gtasks-sync.log";

/** The fields an op can set. Due is YYYY-MM-DD; null clears it. */
export interface Fields {
  title?: string;
  notes?: string;
  due?: string | null;
}

/** A task as the forms edit it. */
export type TaskValues = Required<Fields>;

export type Op =
  | ({ op: "create"; task: string } & TaskValues)
  | { op: "update"; task: string; fields: Fields }
  | { op: "complete" | "uncomplete" | "delete"; task: string };

/** One task as the service writes it to cache.json. */
export interface CachedTask {
  id: string;
  /** Set on tasks the Mac captured, while the service still maps the local id. */
  local_id: string | null;
  parent: string | null;
  position: string;
  title: string;
  notes: string;
  due: string | null;
  status: "needsAction" | "completed";
  completed: string | null;
  updated: string | null;
  url: string | null;
}

export interface SyncStatus {
  synced_at: string | null;
  last_attempt_at: string | null;
  error: { kind: "auth" | "network" | "other"; message: string } | null;
}

/** Must match CACHE_VERSION in service/src/gtasks_sync/cache.py. */
const CACHE_VERSION = 1;

interface Cache extends SyncStatus {
  version: number;
  tasks: CachedTask[];
}

/**
 * A task as the Mac shows it. `id` is the task id, or the local id of a capture Google has not accepted yet.
 * Ops name the task by `id`. "pending": ops in queue/ or accepted/. "failed": an op in failed/.
 */
export interface Task extends CachedTask {
  state: "synced" | "pending" | "failed";
}

/** Op file names: "<ms>-<hex>.json". Must match OP_FILE_RE in service/src/gtasks_sync/queue.py. */
export const OP_FILE = /^(\d+)-[0-9a-f]+\.json$/;

/** Touched in the queue directory to ask the service for a round now. Must match SYNC_NOW_FILE in queue.py. */
export const SYNC_NOW_FILE = "sync-now";

/** An op, its file name, the time it was written, and the stage its directory gives it. */
export interface StagedOp {
  name: string;
  at: number;
  op: Op;
  state: "pending" | "failed";
}

const STAGES: [string, StagedOp["state"]][] = [
  ["", "pending"],
  ["accepted", "pending"],
  ["failed", "failed"],
];

/** A local id: "local:<ms>-<8 hex>" (ADR 0001). Must match LOCAL_ID_RE in queue.py. */
export function mintLocalId(now = Date.now()): string {
  return `local:${now}-${randomBytes(4).toString("hex")}`;
}

function opNames(dir: string): string[] {
  try {
    return readdirSync(dir).filter((name) => OP_FILE.test(name));
  } catch {
    return [];
  }
}

/** Every op file in the three stage directories, in name order. Unreadable files are skipped. */
export function readOps(appDir = APP_DIR): StagedOp[] {
  return STAGES.flatMap(([sub, state]) => {
    const dir = join(appDir, "queue", sub);
    return opNames(dir).flatMap((name) => {
      try {
        const op = JSON.parse(readFileSync(join(dir, name), "utf8")) as Op;
        return [{ name, at: Number(OP_FILE.exec(name)?.[1]), op, state }];
      } catch {
        return [];
      }
    });
  }).sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Write one op file: temp file, then rename, so the service never reads a partial op (ADR 0002).
 * The time in the name is never before the newest pending op, so a clock step back cannot reorder ops.
 */
export function writeOp(op: Op, appDir = APP_DIR, now = Date.now()): void {
  const dir = join(appDir, "queue");
  mkdirSync(dir, { recursive: true });
  const times = [...opNames(dir), ...opNames(join(dir, "accepted"))].map((n) => Number(OP_FILE.exec(n)?.[1]));
  const name = `${Math.max(now, ...times.map((t) => t + 1))}-${randomBytes(4).toString("hex")}.json`;
  const tmp = join(dir, `.${name}.tmp`);
  writeFileSync(tmp, JSON.stringify(op), { mode: 0o600, flush: true });
  renameSync(tmp, join(dir, name));
}

/** Ask the service to sync now, even during a backoff. The content does not matter, so no atomic write. */
export function requestSync(appDir = APP_DIR): void {
  const dir = join(appDir, "queue");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, SYNC_NOW_FILE), "");
}

/** Capture a task. Titles are trimmed here, at the op boundary, so the pending and synced copies match. */
export function createTask(values: TaskValues, appDir = APP_DIR): void {
  writeOp({ op: "create", task: mintLocalId(), ...values, title: values.title.trim() }, appDir);
}

/** Write an update with only the changed fields. Return false if nothing changed, so no op is written. */
export function updateTask(task: Task, edited: TaskValues, appDir = APP_DIR): boolean {
  const fields: Fields = {};
  const title = edited.title.trim();
  if (title !== task.title) fields.title = title;
  if (edited.notes !== task.notes) fields.notes = edited.notes;
  if (edited.due !== task.due) fields.due = edited.due;
  if (Object.keys(fields).length === 0) return false;
  writeOp({ op: "update", task: task.id, fields }, appDir);
  return true;
}

export function setCompleted(task: Task, completed: boolean, appDir = APP_DIR): void {
  writeOp({ op: completed ? "complete" : "uncomplete", task: task.id }, appDir);
}

export function deleteTask(task: Task, appDir = APP_DIR): void {
  writeOp({ op: "delete", task: task.id }, appDir);
}

/** A task's subtasks. Google completes and deletes them with the parent. */
export function subtasks(tasks: Task[], task: Task): Task[] {
  return tasks.filter((t) => t.parent === task.id);
}

/**
 * The cache with every op on top, in name order, so captures and changes show at once.
 * The service removes a failed op once it no longer means anything, so every file in failed/ shows.
 */
export function overlay(cached: CachedTask[], ops: StagedOp[]): Task[] {
  let tasks: Task[] = cached.map((t) => ({ ...t, state: "synced" }));
  const replace = (task: Task) => (tasks = tasks.map((t) => (t.id === task.id ? task : t)));

  for (const { at, op, state } of ops) {
    const task = tasks.find((t) => t.id === op.task || t.local_id === op.task);
    const when = new Date(at).toISOString();
    if (op.op === "create") {
      // A capture whose result the cache already shows needs nothing.
      if (!task) {
        const { title, notes, due } = op;
        // Position "" sorts before every real one: a new task goes to the top, as in Google Tasks.
        tasks.push({
          id: op.task,
          local_id: op.task,
          parent: null,
          position: "",
          title,
          notes,
          due,
          status: "needsAction",
          completed: null,
          updated: when,
          url: null,
          state,
        });
      }
      continue;
    }
    if (!task) continue;
    if (op.op === "update") {
      // A failed edit shows too, so the text is not lost.
      replace({ ...task, ...op.fields, state });
      continue;
    }
    if (state === "failed") {
      // Google did not change the task: only mark it.
      replace({ ...task, state });
      continue;
    }
    switch (op.op) {
      case "complete":
        for (const t of [task, ...subtasks(tasks, task)]) {
          if (t.status !== "completed") replace({ ...t, status: "completed", completed: when, state });
        }
        break;
      case "uncomplete":
        replace({ ...task, status: "needsAction", completed: null, state });
        break;
      case "delete": {
        const gone = new Set([task.id, ...subtasks(tasks, task).map((t) => t.id)]);
        tasks = tasks.filter((t) => !gone.has(t.id));
        break;
      }
    }
  }
  return tasks;
}

export function loadTasks(appDir = APP_DIR): { tasks: Task[]; status: SyncStatus | null } {
  let cache: Cache | null = null;
  try {
    const parsed = JSON.parse(readFileSync(join(appDir, "cache.json"), "utf8")) as Cache;
    if (parsed.version === CACHE_VERSION) cache = parsed;
  } catch {
    // No cache yet: the service has not synced. Pending ops still show.
  }
  return { tasks: overlay(cache?.tasks ?? [], readOps(appDir)), status: cache };
}

const STALE_MS = 10 * 60 * 1000;

/** A warning for the list, or null when sync is healthy. */
export function syncWarning(status: SyncStatus | null, now = Date.now()): string | null {
  if (status?.error?.kind === "auth") return "Google Tasks sync failing (auth). Run `gtasks-sync setup`.";
  if (status?.error) return `Google Tasks sync failing (${status.error.kind}): ${status.error.message}`;
  if (!status?.synced_at) return "No sync yet. Is the gtasks-sync service running?";
  const age = now - Date.parse(status.synced_at);
  return age > STALE_MS ? `Last sync ${Math.round(age / 60_000)} min ago.` : null;
}
