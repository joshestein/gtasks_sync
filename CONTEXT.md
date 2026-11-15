# Glossary

**Task**: A Google Tasks task: title, notes, due date, status (open or completed).

**Task list**: A Google Tasks list. The Mac uses only the default list ("My Tasks").

**Subtask**: A task with a parent task. The Mac can complete, edit, and delete a subtask. It does not create or move one.

**Task id**: The id that Google gives a task.

**Local id**: The id that the Mac gives a captured task before Google gives it a task id.

**Capture**: To make a new task on the Mac. A capture never waits for the network.

**Op**: One change to a task, made on the Mac: `create`, `update`, `complete`, `uncomplete`, or `delete`. An `update` carries only the changed fields.

**Complete**: To mark a task as done. Completing a parent also completes its subtasks. To uncomplete makes the task open again.

**Delete**: To remove a task from Google Tasks, with its subtasks. An op on a task deleted elsewhere does nothing. To delete a failed capture removes it from the Mac.

**Queue**: The ops that the Mac has made and Google has not yet accepted.

**Accepted op**: An op that Google has accepted and the Cache does not yet show. It leaves the Mac once the Cache has its result.

**Failed op**: An op that can never succeed, for example a bad file. It leaves the queue, does not block later ops, and stays visible.

**Pending task**: A task with ops in the Queue or Accepted ops. The Mac shows the result of those ops at once.

**Cache**: The last copy of the task list from Google: all open tasks, and tasks completed in the last 7 days.

**Sync**: One round: send the queue, then get the full task list.
