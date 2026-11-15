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
import { ReactElement, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatDue, formatTime, isOverdue, toDue } from "./lib/dates";
import { arrange, Row } from "./lib/list";
import { escapeMarkdown, renderTask } from "./lib/markdown";
import {
  createTask,
  deleteTask,
  loadTasks,
  LOG_FILE,
  requestSync,
  setCompleted,
  subtasks,
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
  // Set new state only when something changed, so the list does not jump.
  const lastJson = useRef("");
  const reload = useCallback(() => {
    const next = load();
    const json = JSON.stringify(next);
    if (json !== lastJson.current) {
      lastJson.current = json;
      setData(next);
    }
  }, []);
  // The service changes the files in the background: poll so pending states and the sync warning stay current.
  useEffect(() => {
    const timer = setInterval(reload, RELOAD_MS);
    return () => clearInterval(timer);
  }, [reload]);
  const { open, completed } = useMemo(() => arrange(tasks, query), [tasks, query]);
  const today = toDue(new Date());
  const newTask = <NewTaskAction title={query.trim()} reload={reload} />;
  const item = (row: Row) => (
    <TaskItem
      key={row.task.id}
      row={row}
      subtaskCount={subtasks(tasks, row.task).length}
      today={today}
      reload={reload}
      newTask={newTask}
      showDetail={showDetail}
      toggleDetail={() => setShowDetail((s) => !s)}
    />
  );

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
                markdown={`${escapeMarkdown(warning)}\n\nRun \`gtasks-sync status\` or check \`${LOG_FILE}\`.`}
              />
            }
            actions={
              <ActionPanel>
                <SyncNowAction />
                {newTask}
              </ActionPanel>
            }
          />
        </List.Section>
      )}
      <List.EmptyView
        title="No tasks"
        description={query ? "Press Return to make a task from your search." : undefined}
        actions={<ActionPanel>{newTask}</ActionPanel>}
      />
      {(
        [
          ["Open", open],
          ["Completed", completed],
        ] as const
      ).map(([title, rows]) => (
        <List.Section key={title} title={title} subtitle={String(rows.length)}>
          {rows.map(item)}
        </List.Section>
      ))}
    </List>
  );
}

interface ItemProps {
  row: Row;
  subtaskCount: number;
  today: string;
  reload: () => void;
  newTask: ReactElement;
  showDetail: boolean;
  toggleDetail: () => void;
}

function TaskItem({ row, subtaskCount, today, reload, newTask, showDetail, toggleDetail }: ItemProps) {
  const { task, parentTitle, nested } = row;
  const done = task.status === "completed";

  async function toggleCompleted() {
    setCompleted(task, !done);
    reload();
    await showToast({ style: Toast.Style.Success, title: done ? "Reopened" : "Completed" });
  }

  async function remove() {
    const confirmed = await confirmAlert({
      title: "Delete task?",
      message: subtaskCount ? `This also deletes ${subtaskCount} subtask${subtaskCount === 1 ? "" : "s"}.` : undefined,
      primaryAction: { title: "Delete", style: Alert.ActionStyle.Destructive },
    });
    if (!confirmed) return;
    deleteTask(task);
    reload();
  }

  return (
    <List.Item
      title={nested ? `↳ ${task.title}` : task.title}
      // Under its parent the parent title adds nothing.
      subtitle={nested ? undefined : parentTitle}
      icon={rowIcon(task)}
      accessories={accessories(task, today)}
      // Built only while the pane shows: it is the costliest part of a row.
      detail={
        showDetail ? (
          <List.Item.Detail
            markdown={renderTask(task)}
            metadata={<TaskMetadata task={task} parentTitle={parentTitle} today={today} />}
          />
        ) : undefined
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
          {newTask}
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

/** `title`, usually the search text, becomes the title of the new task. */
function NewTaskAction({ title, reload }: { title: string; reload: () => void }) {
  return (
    <Action.Push
      title="New Task"
      icon={Icon.Plus}
      shortcut={Keyboard.Shortcut.Common.New}
      target={<TaskEditor initialTitle={title} onSaved={reload} />}
    />
  );
}

/** Edits `task`, or makes a new task when there is none. */
function TaskEditor({ task, initialTitle = "", onSaved }: { task?: Task; initialTitle?: string; onSaved: () => void }) {
  const { pop } = useNavigation();
  return (
    <TaskForm
      submitTitle={task ? "Save Changes" : "Save Task"}
      initial={task ?? { title: initialTitle, due: null, notes: "" }}
      onSubmit={async (values) => {
        let changed = true;
        if (task) changed = updateTask(task, values);
        else createTask(values);
        onSaved();
        pop();
        await showToast(
          changed
            ? { style: Toast.Style.Success, title: "Saved", message: "Syncs in the background" }
            : { style: Toast.Style.Success, title: "No changes" },
        );
      }}
    />
  );
}

function TaskMetadata({ task, parentTitle, today }: { task: Task; parentTitle?: string; today: string }) {
  const { Metadata } = List.Item.Detail;
  return (
    <Metadata>
      <Metadata.Label title="Sync" text={STATE_LABEL[task.state]} />
      {task.due && <Metadata.Label title="Due" text={formatDue(task.due, today)} />}
      {task.completed && <Metadata.Label title="Completed" text={formatTime(task.completed)} />}
      {parentTitle && <Metadata.Label title="Subtask of" text={parentTitle} />}
      {task.updated && <Metadata.Label title="Updated" text={formatTime(task.updated)} />}
    </Metadata>
  );
}

const STATE_LABEL: Record<Task["state"], string> = {
  synced: "Synced",
  pending: "Pending sync",
  failed: `Failed: see ${LOG_FILE}`,
};

function rowIcon(task: Task): Image.ImageLike {
  return task.status === "completed"
    ? { source: Icon.CheckCircle, tintColor: Color.Green }
    : { source: Icon.Circle, tintColor: Color.SecondaryText };
}

function accessories(task: Task, today: string): List.Item.Accessory[] {
  const list: List.Item.Accessory[] = [];
  if (task.due) {
    list.push({ tag: { value: formatDue(task.due, today), color: isOverdue(task, today) ? Color.Red : undefined } });
  }
  if (task.state === "failed") {
    list.push({ icon: { source: Icon.ExclamationMark, tintColor: Color.Red }, tooltip: STATE_LABEL.failed });
  } else if (task.state === "pending") {
    list.push({ icon: { source: Icon.Clock, tintColor: Color.SecondaryText }, tooltip: STATE_LABEL.pending });
  }
  return list;
}
