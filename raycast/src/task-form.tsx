import { Action, ActionPanel, Form } from "@raycast/api";
import { useState } from "react";

import { localDate } from "./lib/list";

/** Form values in the form an op takes: title trimmed, due as YYYY-MM-DD or null. */
export interface TaskFormValues {
  title: string;
  due: string | null;
  notes: string;
}

interface Props {
  submitTitle: string;
  initial?: TaskFormValues;
  enableDrafts?: boolean;
  onSubmit: (values: TaskFormValues) => Promise<void> | void;
}

/** A due date "YYYY-MM-DD" as local midnight, which is what the date picker shows. */
function dueToDate(due: string | null): Date | null {
  if (!due) return null;
  const [y, m, d] = due.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function TaskForm({ submitTitle, initial, enableDrafts, onSubmit }: Props) {
  const [titleError, setTitleError] = useState<string>();

  async function submit(values: { title: string; due: Date | null; notes: string }) {
    const title = values.title.trim();
    if (!title) {
      setTitleError("Write a title");
      return;
    }
    // The API keeps only the date, so take the date the user picked in their own time zone.
    await onSubmit({ title, due: values.due ? localDate(values.due) : null, notes: values.notes });
  }

  return (
    <Form
      enableDrafts={enableDrafts}
      actions={
        <ActionPanel>
          <Action.SubmitForm title={submitTitle} onSubmit={submit} />
        </ActionPanel>
      }
    >
      <Form.TextField
        id="title"
        title="Title"
        autoFocus
        defaultValue={initial?.title}
        error={titleError}
        onChange={() => setTitleError(undefined)}
      />
      <Form.DatePicker
        id="due"
        title="Due"
        type={Form.DatePicker.Type.Date}
        defaultValue={dueToDate(initial?.due ?? null)}
      />
      <Form.TextArea id="notes" title="Notes" placeholder="Optional" defaultValue={initial?.notes} />
    </Form>
  );
}
