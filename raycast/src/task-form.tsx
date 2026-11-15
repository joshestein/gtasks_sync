import { Action, ActionPanel, Form } from "@raycast/api";
import { useState } from "react";

import { parseDue, toDue } from "./lib/dates";
import type { TaskValues } from "./lib/store";

interface Props {
  submitTitle: string;
  initial?: TaskValues;
  enableDrafts?: boolean;
  onSubmit: (values: TaskValues) => Promise<void> | void;
}

export function TaskForm({ submitTitle, initial, enableDrafts, onSubmit }: Props) {
  const [titleError, setTitleError] = useState<string>();

  async function submit(values: { title: string; due: Date | null; notes: string }) {
    if (!values.title.trim()) {
      setTitleError("Write a title");
      return;
    }
    // The API keeps only the date, so take the date the user picked in their own time zone.
    await onSubmit({ title: values.title, due: values.due ? toDue(values.due) : null, notes: values.notes });
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
        defaultValue={initial?.due ? parseDue(initial.due) : null}
      />
      <Form.TextArea id="notes" title="Notes" placeholder="Optional" defaultValue={initial?.notes} />
    </Form>
  );
}
