import { describe, expect, it } from "vitest";

import { arrange, isOverdue, localDate, Row } from "../src/lib/list";
import { escapeMarkdown, renderTask } from "../src/lib/markdown";
import { Task } from "../src/lib/store";

const task = (id: string, fields: Partial<Task> = {}): Task => ({
  id,
  local_id: null,
  parent: null,
  position: "00000000000000000005",
  title: id,
  notes: "",
  due: null,
  status: "needsAction",
  completed: null,
  updated: null,
  url: null,
  state: "synced",
  ...fields,
});

const ids = (rows: Row[]) => rows.map((r) => r.task.id);

describe("arrange", () => {
  it("sorts open tasks by due date, no due date last, then Google's order", () => {
    const { open } = arrange([
      task("none-b", { position: "2" }),
      task("late", { due: "2026-12-01" }),
      task("none-a", { position: "1" }),
      task("soon", { due: "2026-11-20" }),
      task("capture", { position: "" }),
    ]);
    expect(ids(open)).toEqual(["soon", "late", "capture", "none-a", "none-b"]);
  });

  it("puts subtasks right after their parent, in Google's order, with the parent title", () => {
    const { open } = arrange([
      task("p", { title: "Parent", due: "2026-11-20" }),
      task("c2", { parent: "p", position: "2" }),
      task("c1", { parent: "p", position: "1" }),
      task("q"),
    ]);
    expect(ids(open)).toEqual(["p", "c1", "c2", "q"]);
    expect(open[1].parentTitle).toBe("Parent");
    expect(open[0].parentTitle).toBeUndefined();
  });

  it("shows a subtask as top-level when its parent is in the other section", () => {
    const { open, completed } = arrange([
      task("p", { status: "completed", completed: "2026-11-15T00:00:00.000Z" }),
      task("c", { parent: "p" }),
    ]);
    expect(ids(open)).toEqual(["c"]);
    expect(ids(completed)).toEqual(["p"]);
  });

  it("sorts completed tasks newest first, with subtasks after their parent", () => {
    const done = (completed: string, fields: Partial<Task> = {}) => ({
      status: "completed" as const,
      completed,
      ...fields,
    });
    const { completed } = arrange([
      task("old", done("2026-11-10T00:00:00.000Z")),
      task("new", done("2026-11-14T00:00:00.000Z")),
      task("new-child", done("2026-11-14T00:00:00.000Z", { parent: "new" })),
    ]);
    expect(ids(completed)).toEqual(["new", "new-child", "old"]);
  });

  it("search matches every word in title or notes, ignoring case, and shows a matching subtask alone", () => {
    const tasks = [
      task("p", { title: "Groceries" }),
      task("c", { title: "Oat Milk", parent: "p", notes: "the barista one" }),
    ];
    const { open } = arrange(tasks, "milk BARISTA");
    expect(ids(open)).toEqual(["c"]);
    expect(open[0].parentTitle).toBe("Groceries");
    expect(ids(arrange(tasks, "milk cheese").open)).toEqual([]);
    expect(ids(arrange(tasks, "  ").open)).toEqual(["p", "c"]);
  });
});

describe("dates", () => {
  it("localDate uses the local time zone", () => {
    expect(localDate(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("an open task is overdue the day after its due date", () => {
    expect(isOverdue(task("t", { due: "2026-11-14" }), "2026-11-15")).toBe(true);
    expect(isOverdue(task("t", { due: "2026-11-15" }), "2026-11-15")).toBe(false);
    expect(isOverdue(task("t", { due: "2026-11-14", status: "completed" }), "2026-11-15")).toBe(false);
    expect(isOverdue(task("t"), "2026-11-15")).toBe(false);
  });
});

describe("markdown", () => {
  it("escapes markdown so text shows as written, and keeps line breaks and indents", () => {
    expect(escapeMarkdown("# a *b*")).toBe("\\# a \\*b\\*");
    expect(escapeMarkdown("x\n  y")).toBe("x  \n  y");
  });

  it("renders the title as a heading, then the notes", () => {
    expect(renderTask(task("t", { title: "milk", notes: "oat" }))).toBe("# milk\n\noat");
    expect(renderTask(task("t", { title: "milk" }))).toBe("# milk");
  });
});
