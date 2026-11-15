/**
 * Due dates are calendar dates, "YYYY-MM-DD", in the user's time zone. Google keeps only the date.
 * All arithmetic is on calendar days, never on milliseconds: a day is not always 24 hours.
 */
import type { Task } from "./store";

const pad = (n: number) => String(n).padStart(2, "0");

/** The calendar date of `date` in the local time zone. */
export function toDue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Local midnight of a due date: what a date picker shows. */
export function parseDue(due: string): Date {
  const [y, m, d] = due.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(due: string, days: number): string {
  const date = parseDue(due);
  return toDue(new Date(date.getFullYear(), date.getMonth(), date.getDate() + days));
}

export function isOverdue(task: Task, today: string): boolean {
  return task.status === "needsAction" && task.due !== null && task.due < today;
}

const SHORT_DATE = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });
const DATE_TIME = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** "Today", "Tomorrow", "Yesterday", or a short date such as "Fri 20 Nov". */
export function formatDue(due: string, today: string): string {
  if (due === today) return "Today";
  if (due === addDays(today, 1)) return "Tomorrow";
  if (due === addDays(today, -1)) return "Yesterday";
  return SHORT_DATE.format(parseDue(due));
}

/** An RFC 3339 time from the cache, in the local time zone. */
export function formatTime(iso: string): string {
  return DATE_TIME.format(new Date(iso));
}
