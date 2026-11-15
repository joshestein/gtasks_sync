import { describe, expect, it } from "vitest";

import { addDays, formatDue, isOverdue, parseDue, toDue } from "../src/lib/dates";
import { arrange, Row } from "../src/lib/list";
import { escapeMarkdown, renderTask } from "../src/lib/markdown";
import { task } from "./fixtures";

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

  it("puts subtasks right after their parent, in Google's order, nested", () => {
    const { open } = arrange([
      task("p", { title: "Parent", due: "2026-11-20" }),
      task("c2", { parent: "p", position: "2" }),
      task("c1", { parent: "p", position: "1" }),
      task("q"),
    ]);
    expect(ids(open)).toEqual(["p", "c1", "c2", "q"]);
    expect(open[1]).toMatchObject({ parentTitle: "Parent", nested: true });
    expect(open[0]).toMatchObject({ parentTitle: undefined, nested: false });
  });

  it("shows a subtask alone, with its parent title, when its parent is in the other section", () => {
    const { open, completed } = arrange([
      task("p", { title: "Parent", status: "completed", completed: "2026-11-15T00:00:00.000Z" }),
      task("c", { parent: "p" }),
    ]);
    expect(open).toEqual([expect.objectContaining({ parentTitle: "Parent", nested: false })]);
    expect(ids(completed)).toEqual(["p"]);
  });

  it("sorts completed tasks newest first, with subtasks after their parent", () => {
    const done = (completed: string) => ({ status: "completed" as const, completed });
    const { completed } = arrange([
      task("old", done("2026-11-10T00:00:00.000Z")),
      task("new", done("2026-11-14T00:00:00.000Z")),
      task("new-child", { ...done("2026-11-14T00:00:00.000Z"), parent: "new" }),
    ]);
    expect(ids(completed)).toEqual(["new", "new-child", "old"]);
  });

  it("search matches every word in title or notes, ignoring case, and shows a subtask without its parent alone", () => {
    const tasks = [
      task("p", { title: "Groceries" }),
      task("c", { title: "Oat Milk", parent: "p", notes: "the barista one" }),
    ];
    const { open } = arrange(tasks, "milk BARISTA");
    expect(open).toEqual([expect.objectContaining({ parentTitle: "Groceries", nested: false })]);
    expect(ids(arrange(tasks, "milk cheese").open)).toEqual([]);
    expect(arrange(tasks, "  ").open.map((r) => r.nested)).toEqual([false, true]);
  });
});

describe("dates", () => {
  it("toDue and parseDue use the local time zone", () => {
    expect(toDue(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
    expect(toDue(parseDue("2026-03-08"))).toBe("2026-03-08");
  });

  it("addDays counts calendar days, also across a month, a year, and a DST change", () => {
    expect(addDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addDays("2026-03-08", 1)).toBe("2026-03-09");
    expect(addDays("2026-10-25", 1)).toBe("2026-10-26");
  });

  it("formatDue names the near days", () => {
    expect(formatDue("2026-11-15", "2026-11-15")).toBe("Today");
    expect(formatDue("2026-11-16", "2026-11-15")).toBe("Tomorrow");
    expect(formatDue("2026-11-14", "2026-11-15")).toBe("Yesterday");
    expect(formatDue("2026-11-20", "2026-11-15")).toMatch(/20/);
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
    expect(escapeMarkdown("&copy;")).toBe("\\&copy;");
    expect(escapeMarkdown("x\n  y")).toBe("x  \n  y");
  });

  it("renders the title as a heading, then the notes", () => {
    expect(renderTask(task("t", { title: "milk", notes: "oat" }))).toBe("# milk\n\noat");
    expect(renderTask(task("t", { title: "milk" }))).toBe("# milk");
  });
});
