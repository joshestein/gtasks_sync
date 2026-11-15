import type { Task } from "./store";

/**
 * Show plain task text exactly as written. Google Tasks does not render markdown, so every markdown
 * character is escaped, line breaks are kept, and leading spaces and tabs cannot start a code block.
 */
export function escapeMarkdown(text: string): string {
  return text
    .split("\n")
    .map((line) =>
      line
        .replace(/[\\`*_{}[\]()#+\-.!|<>~=&]/g, "\\$&")
        .replace(/^[ \t]+/, (indent) => indent.replace(/ /g, " ").replace(/\t/g, " ".repeat(4))),
    )
    .join("  \n");
}

export function renderTask(task: Task): string {
  return `# ${escapeMarkdown(task.title)}` + (task.notes ? `\n\n${escapeMarkdown(task.notes)}` : "");
}
