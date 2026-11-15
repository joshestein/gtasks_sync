/** Sections, order, and search for the Tasks list. */
import type { Task } from "./store";

export interface Row {
  task: Task;
  /** Set on a subtask: the title of its parent. */
  parentTitle?: string;
}

export interface Sections {
  open: Row[];
  completed: Row[];
}

/** A date as YYYY-MM-DD in the local time zone: the form of a due date. */
export function localDate(date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isOverdue(task: Task, today = localDate()): boolean {
  return task.status === "needsAction" && task.due !== null && task.due < today;
}

const byPosition = (a: Task, b: Task) => a.position.localeCompare(b.position);

/** Due date first (no due date last), then Google's order. */
const byDueThenPosition = (a: Task, b: Task) => (a.due ?? "9999").localeCompare(b.due ?? "9999") || byPosition(a, b);

/** Newest completion first. */
const byCompletedDesc = (a: Task, b: Task) => (b.completed ?? "").localeCompare(a.completed ?? "");

/**
 * One section: top-level tasks in `order`, each followed by its subtasks in Google's order.
 * A subtask whose parent is not in the section shows as a top-level task.
 */
function section(tasks: Task[], order: (a: Task, b: Task) => number): Row[] {
  const ids = new Set(tasks.map((t) => t.id));
  const isTop = (t: Task) => t.parent === null || !ids.has(t.parent);
  return tasks
    .filter(isTop)
    .sort(order)
    .flatMap((parent) => [
      { task: parent },
      ...tasks
        .filter((t) => t.parent === parent.id)
        .sort(byPosition)
        .map((task) => ({ task, parentTitle: parent.title })),
    ]);
}

/** Tasks whose title or notes contain every word of the query, ignoring case. */
function matchesQuery(task: Task, words: string[]): boolean {
  const haystack = `${task.title}\n${task.notes}`.toLowerCase();
  return words.every((w) => haystack.includes(w));
}

/** The list: open tasks, then completed tasks. A search keeps the order and shows a matching subtask alone. */
export function arrange(tasks: Task[], query = ""): Sections {
  const parentTitle = new Map(tasks.map((t) => [t.id, t.title]));
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const build = (status: Task["status"], order: (a: Task, b: Task) => number): Row[] => {
    const rows = section(
      tasks.filter((t) => t.status === status),
      order,
    );
    if (words.length === 0) return rows;
    return rows
      .filter((r) => matchesQuery(r.task, words))
      .map((r) => {
        const parent = r.task.parent ? parentTitle.get(r.task.parent) : undefined;
        return parent === undefined ? r : { ...r, parentTitle: parent };
      });
  };
  return { open: build("needsAction", byDueThenPosition), completed: build("completed", byCompletedDesc) };
}
