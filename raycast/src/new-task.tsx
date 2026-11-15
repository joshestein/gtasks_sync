import { popToRoot, showHUD } from "@raycast/api";

import { createTask } from "./lib/store";
import { TaskForm } from "./task-form";

export default function Command() {
  return (
    <TaskForm
      submitTitle="Save Task"
      enableDrafts
      onSubmit={async ({ title, due, notes }) => {
        // Only a local file write: the service syncs it in the background.
        createTask(title, notes, due);
        await showHUD("Task saved", { clearRootSearch: true });
        await popToRoot();
      }}
    />
  );
}
