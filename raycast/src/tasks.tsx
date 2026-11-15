import {
  Action,
  ActionPanel,
  Alert,
  Color,
  confirmAlert,
  Icon,
  Image,
  Keyboard,
  List,
  showToast,
  Toast,
  useNavigation,
} from "@raycast/api";
import { useCallback, useEffect, useMemo, useState } from "react";

import { arrange, isOverdue, localDate, Row } from "./lib/list";
import { escapeMarkdown, renderTask } from "./lib/markdown";
import {
  createTask,
  deleteTask,
  loadTasks,
  requestSync,
  setCompleted,
  syncWarning,
  Task,
  updateTask,
} from "./lib/store";
import { TaskForm } from "./task-form";

const RELOAD_MS = 3000;

function load(): { tasks: Task[]; warning: string | null } {
  const { tasks, status } = loadTasks();
  return { tasks, warning: syncWarning(status) };
}

export default function Command() {
  const [{ tasks, warning }, setData] = useState(load);
  const [query, setQuery] = useState("");
  const [showDetail, setShowDetail] = useState(false);
  // Keep the old state when nothing changed, so the list does not jump.
  const reload = useCallback(
    () =>
      setData((prev) => {
        const next = load();
        return JSON.stringify(next) === JSON.stringify(prev) ? prev : next;
      }),
    [],
  );
  // The service changes the files in the background: poll so pending states and the sync warning stay current.
  useEffect(() => {
    const timer = setInterval(reload, RELOAD_MS);
    return () => clearInterval(timer);
  }, [reload]);
  const { open, completed } = useMemo(() => arrange(tasks, query), [tasks, query]);
  const shared = { tasks, query, reload, showDetail, toggleDetail: () => setShowDetail((s) => !s) };

  return (
    <List
      isShowingDetail={showDetail}
      filtering={false}
      onSearchTextChange={setQuery}
      searchBarPlaceholder="Search tasks"
    >
      {warning && (
        <List.Section title="Sync">
          <List.Item
            icon={{ source: Icon.Warning, tintColor: Color.Orange }}
            title={warning}
            detail={
              <List.Item.Detail
                markdown={`${escapeMarkdown(warning)}\n\nRun \`gtasks-sync status\` or check \`~/Library/Logs/gtasks-sync.log\`.`}
              />
            }
            actions={
              <ActionPanel>
                <SyncNowAction />
                <NewTaskAction query={query} reload={reload} />
              </ActionPanel>
            }
          />
        </List.Section>
      )}
      <List.EmptyView
        title="No tasks"
        description={query ? "Press Return to make a task from your search." : undefined}
        actions={
          <ActionPanel>
            <NewTaskAction query={query} reload={reload} />
          </ActionPanel>
        }
      />
      <List.Section title="Open" subtitle={String(open.length)}>
        {open.map((row) => (
          <TaskItem key={row.task.id} row={row} {...shared} />
        ))}
      </List.Section>
      <List.Section title="Completed" subtitle={String(completed.length)}>
        {completed.map((row) => (
          <TaskItem key={row.task.id} row={row} {...shared} />
        ))}
      </List.Section>
    </List>
  );
}

interface ItemProps {
  row: Row;
  tasks: Task[];
  query: string;
  reload: () => void;
  showDetail: boolean;
  toggleDetail: () => void;
}

function TaskItem({ row: { task, parentTitle }, tasks, query, reload, showDetail, toggleDetail }: ItemProps) {
  const done = task.status === "completed";

  async function toggleCompleted() {
    setCompleted(task, !done);
    reload();
    await showToast({ style: Toast.Style.Success, title: done ? "Reopened" : "Completed" });
  }

  async function remove() {
    const subtasks = tasks.filter((t) => t.parent === task.id).length;
    const confirmed = await confirmAlert({
      title: "Delete task?",
      message: subtasks ? `This also deletes ${subtasks} subtask${subtasks === 1 ? "" : "s"}.` : undefined,
      primaryAction: { title: "Delete", style: Alert.ActionStyle.Destructive },
    });
    if (!confirmed) return;
    deleteTask(task);
    reload();
  }

  return (
    <List.Item
      title={parentTitle ? `↳ ${task.title}` : task.title}
      // Under its parent the parent title adds nothing. In a search, the subtask shows alone.
      subtitle={parentTitle && query ? parentTitle : undefined}
      icon={rowIcon(task)}
      accessories={accessories(task)}
      detail={
        <List.Item.Detail
          markdown={renderTask(task)}
          metadata={<TaskMetadata task={task} parentTitle={parentTitle} />}
        />
      }
      actions={
        <ActionPanel>
          <Action
            title={done ? "Reopen Task" : "Complete Task"}
            icon={done ? Icon.Circle : Icon.CheckCircle}
            onAction={toggleCompleted}
          />
          <Action.Push
            title="Edit Task"
            icon={Icon.Pencil}
            shortcut={Keyboard.Shortcut.Common.Edit}
            target={<TaskEditor task={task} onSaved={reload} />}
          />
          <Action.CopyToClipboard title="Copy Title" content={task.title} shortcut={Keyboard.Shortcut.Common.Copy} />
          <NewTaskAction query={query} reload={reload} />
          {task.url && (
            <Action.OpenInBrowser
              title="Open in Google Tasks"
              url={task.url}
              shortcut={Keyboard.Shortcut.Common.Open}
            />
          )}
          <Action
            title={showDetail ? "Hide Details" : "Show Details"}
            icon={Icon.Sidebar}
            shortcut={{ modifiers: ["cmd"], key: "d" }}
            onAction={toggleDetail}
          />
          <Action
            title="Delete Task"
            icon={Icon.Trash}
            style={Action.Style.Destructive}
            shortcut={Keyboard.Shortcut.Common.Remove}
            onAction={remove}
          />
          <SyncNowAction />
        </ActionPanel>
      }
    />
  );
}

/** The list already polls the files, so this asks the service for a round. The poll shows the result. */
function SyncNowAction() {
  async function syncNow() {
    try {
      requestSync();
    } catch (error) {
      await showToast({ style: Toast.Style.Failure, title: "Could not request sync", message: String(error) });
      return;
    }
    await showToast({ style: Toast.Style.Success, title: "Sync requested" });
  }
  return (
    <Action
      title="Sync Now"
      icon={Icon.ArrowClockwise}
      shortcut={Keyboard.Shortcut.Common.Refresh}
      onAction={syncNow}
    />
  );
}

/** The search text becomes the title of the new task. */
function NewTaskAction({ query, reload }: { query: string; reload: () => void }) {
  return (
    <Action.Push
      title="New Task"
      icon={Icon.Plus}
      shortcut={Keyboard.Shortcut.Common.New}
      target={<TaskEditor initialTitle={query.trim()} onSaved={reload} />}
    />
  );
}

/** Edits `task`, or makes a new task when there is none. */
function TaskEditor({ task, initialTitle = "", onSaved }: { task?: Task; initialTitle?: string; onSaved: () => void }) {
  const { pop } = useNavigation();
  return (
    <TaskForm
      submitTitle={task ? "Save Changes" : "Save Task"}
      initial={
        task ? { title: task.title, due: task.due, notes: task.notes } : { title: initialTitle, due: null, notes: "" }
      }
      onSubmit={async (values) => {
        const changed = task ? updateTask(task, values) : (createTask(values.title, values.notes, values.due), true);
        onSaved();
        pop();
        await showToast({
          style: Toast.Style.Success,
          title: changed ? "Saved" : "No changes",
          message: changed ? "Syncs in the background" : undefined,
        });
      }}
    />
  );
}

function TaskMetadata({ task, parentTitle }: { task: Task; parentTitle?: string }) {
  const { Metadata } = List.Item.Detail;
  return (
    <Metadata>
      <Metadata.Label title="Sync" text={STATE_LABEL[task.state]} />
      {task.due && <Metadata.Label title="Due" text={formatDue(task.due)} />}
      {task.completed && <Metadata.Label title="Completed" text={new Date(task.completed).toLocaleString()} />}
      {parentTitle && <Metadata.Label title="Subtask of" text={parentTitle} />}
      {task.updated && <Metadata.Label title="Updated" text={new Date(task.updated).toLocaleString()} />}
    </Metadata>
  );
}

const STATE_LABEL: Record<Task["state"], string> = {
  synced: "Synced",
  pending: "Pending sync",
  failed: "Failed: see ~/Library/Logs/gtasks-sync.log",
};

function rowIcon(task: Task): Image.ImageLike {
  return task.status === "completed"
    ? { source: Icon.CheckCircle, tintColor: Color.Green }
    : { source: Icon.Circle, tintColor: Color.SecondaryText };
}

function accessories(task: Task): List.Item.Accessory[] {
  const list: List.Item.Accessory[] = [];
  if (task.due) {
    list.push({ tag: { value: formatDue(task.due), color: isOverdue(task) ? Color.Red : undefined } });
  }
  if (task.state === "failed") {
    list.push({ icon: { source: Icon.ExclamationMark, tintColor: Color.Red }, tooltip: STATE_LABEL.failed });
  } else if (task.state === "pending") {
    list.push({ icon: { source: Icon.Clock, tintColor: Color.SecondaryText }, tooltip: STATE_LABEL.pending });
  }
  return list;
}

/** "Today", "Tomorrow", "Yesterday", or a short date such as "Fri 20 Nov". */
function formatDue(due: string): string {
  const [y, m, d] = due.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const offset = (days: number) => localDate(new Date(Date.now() + days * 86_400_000));
  if (due === offset(0)) return "Today";
  if (due === offset(1)) return "Tomorrow";
  if (due === offset(-1)) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}
