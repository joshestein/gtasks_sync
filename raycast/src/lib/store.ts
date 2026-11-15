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

export const APP_DIR = join(homedir(), "Library", "Application Support", "gtasks-sync");

/** The fields an op can set. Due is YYYY-MM-DD; null clears it. */
export interface Fields {
  title?: string;
  notes?: string;
  due?: string | null;
}

export type Op =
  | { op: "create"; task: string; title: string; notes: string; due: string | null }
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

/** An op, its file name, and the time it was written. */
export interface QueuedOp {
  name: string;
  at: number;
  op: Op;
}

const queueDir = (appDir: string) => join(appDir, "queue");

/** A local id: "local:<ms>-<8 hex>" (ADR 0001). Must match LOCAL_ID_RE in queue.py. */
export function mintLocalId(now = Date.now()): string {
  return `local:${now}-${randomBytes(4).toString("hex")}`;
}

/** Ops in one directory, in apply order. Unreadable files are skipped: the service moves them to failed/. */
export function readOps(dir: string): QueuedOp[] {
  let names: string[];
  try {
    names = readdirSync(dir).sort();
  } catch {
    return [];
  }
  return names.flatMap((name) => {
    const match = OP_FILE.exec(name);
    if (!match) return [];
    try {
      return [{ name, at: Number(match[1]), op: JSON.parse(readFileSync(join(dir, name), "utf8")) as Op }];
    } catch {
      return [];
    }
  });
}

/** The ops the Mac still shows as pending: queue/ and accepted/ together, in name order. */
function pendingOps(appDir: string): QueuedOp[] {
  const queue = queueDir(appDir);
  return [...readOps(queue), ...readOps(join(queue, "accepted"))].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Write one op file: temp file, then rename, so the service never reads a partial op (ADR 0002).
 * The time in the name is never before the newest pending op, so a clock step back cannot reorder ops.
 */
export function writeOp(op: Op, appDir = APP_DIR, now = Date.now()): void {
  const dir = queueDir(appDir);
  mkdirSync(dir, { recursive: true });
  const newest = pendingOps(appDir).at(-1)?.at ?? 0;
  const name = `${Math.max(now, newest + 1)}-${randomBytes(4).toString("hex")}.json`;
  const tmp = join(dir, `.${name}.tmp`);
  writeFileSync(tmp, JSON.stringify(op), { mode: 0o600, flush: true });
  renameSync(tmp, join(dir, name));
}

/** Ask the service to sync now, even during a backoff. The content does not matter, so no atomic write. */
export function requestSync(appDir = APP_DIR): void {
  const dir = queueDir(appDir);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, SYNC_NOW_FILE), "");
}

/** Capture a task. The title is trimmed here, so the pending task and its synced copy show the same title. */
export function createTask(title: string, notes: string, due: string | null, appDir = APP_DIR): void {
  writeOp({ op: "create", task: mintLocalId(), title: title.trim(), notes, due }, appDir);
}

/** The fields of `edited` that differ from `task`. Empty if nothing changed. */
export function changedFields(task: Task, edited: Required<Fields>): Fields {
  const fields: Fields = {};
  const title = edited.title.trim();
  if (title !== task.title) fields.title = title;
  if (edited.notes !== task.notes) fields.notes = edited.notes;
  if (edited.due !== task.due) fields.due = edited.due;
  return fields;
}

/** Write an update with only the changed fields. Return false if nothing changed, so no op is written. */
export function updateTask(task: Task, edited: Required<Fields>, appDir = APP_DIR): boolean {
  const fields = changedFields(task, edited);
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

const matches = (task: CachedTask, ref: string) => task.id === ref || task.local_id === ref;

/**
 * The cache with failed ops, then pending ops, applied on top, so captures and changes show at once.
 * A failed op shows only while Google has no newer version of the task: the service removes a failed op
 * only when a later op for the same task is accepted, so an old one must not hide newer changes.
 */
export function overlay(cached: CachedTask[], pending: QueuedOp[], failed: QueuedOp[]): Task[] {
  let tasks: Task[] = cached.map((t) => ({ ...t, state: "synced" }));
  const find = (ref: string) => tasks.find((t) => matches(t, ref));
  const replace = (task: Task) => (tasks = tasks.map((t) => (t.id === task.id ? task : t)));
  const children = (task: Task) => tasks.filter((t) => t.parent === task.id);

  const apply = ({ at, op }: QueuedOp, state: Task["state"]) => {
    const task = find(op.task);
    const when = new Date(at).toISOString();
    if (op.op === "create") {
      // An accepted create whose result the cache already shows.
      if (task) return;
      tasks.push({
        id: op.task,
        local_id: op.task,
        parent: null,
        position: "", // Before every real position: a new task goes to the top, as in Google Tasks.
        title: op.title,
        notes: op.notes,
        due: op.due,
        status: "needsAction",
        completed: null,
        updated: when,
        url: null,
        state,
      });
      return;
    }
    if (!task) return;
    if (state === "failed") {
      if (task.updated && Date.parse(task.updated) > at) return;
      // Show the edit that failed. For the other ops, Google did not change the task: only mark it.
      replace(op.op === "update" ? { ...task, ...op.fields, state } : { ...task, state });
      return;
    }
    switch (op.op) {
      case "update":
        replace({ ...task, ...op.fields, state });
        break;
      case "complete":
        // Google completes the subtasks with the parent.
        for (const t of [task, ...children(task)]) {
          if (t.status !== "completed") replace({ ...t, status: "completed", completed: when, state });
        }
        break;
      case "uncomplete":
        replace({ ...task, status: "needsAction", completed: null, state });
        break;
      case "delete": {
        // Google deletes the subtasks with the parent.
        const gone = new Set([task.id, ...children(task).map((t) => t.id)]);
        tasks = tasks.filter((t) => !gone.has(t.id));
        break;
      }
    }
  };
  failed.forEach((op) => apply(op, "failed"));
  pending.forEach((op) => apply(op, "pending"));
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
  const tasks = overlay(cache?.tasks ?? [], pendingOps(appDir), readOps(join(queueDir(appDir), "failed")));
  return { tasks, status: cache };
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
