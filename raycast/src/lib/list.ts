/** Sections, order, and search for the Tasks list. */
import { subtasks, type Task } from "./store";

export interface Row {
  task: Task;
  /** Set on every subtask: the title of its parent. */
  parentTitle?: string;
  /** True when the row comes right after its parent, so the parent title need not show. */
  nested: boolean;
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
function section(tasks: Task[], order: (a: Task, b: Task) => number, titles: Map<string, string>): Row[] {
  const ids = new Set(tasks.map((t) => t.id));
  const row = (task: Task, nested: boolean): Row => ({
    task,
    parentTitle: task.parent ? titles.get(task.parent) : undefined,
    nested,
  });
  return tasks
    .filter((t) => t.parent === null || !ids.has(t.parent))
    .sort(order)
    .flatMap((top) => [
      row(top, false),
      ...subtasks(tasks, top)
        .sort(byPosition)
        .map((t) => row(t, true)),
    ]);
}

/** The list: open tasks, then completed tasks. A search keeps the order; a subtask without its parent shows alone. */
export function arrange(tasks: Task[], query = ""): { open: Row[]; completed: Row[] } {
  const titles = new Map(tasks.map((t) => [t.id, t.title]));
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (task: Task) => {
    const haystack = `${task.title}\n${task.notes}`.toLowerCase();
    return words.every((w) => haystack.includes(w));
  };
  const build = (status: Task["status"], order: (a: Task, b: Task) => number): Row[] => {
    const rows = section(
      tasks.filter((t) => t.status === status),
      order,
      titles,
    ).filter((r) => matches(r.task));
    const shown = new Set(rows.map((r) => r.task.id));
    return rows.map((r) => ({ ...r, nested: r.nested && shown.has(r.task.parent ?? "") }));
  };
  return { open: build("needsAction", byDueThenPosition), completed: build("completed", byCompletedDesc) };
}
