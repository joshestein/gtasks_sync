# Local ids, an id map, and adoption on replay

Google mints task ids, so the extension cannot know a task's id at capture. The extension mints a local id instead. The service maps local id to task id in `state.json`. `cache.json` carries `local_id`, so the extension matches a pending task to its synced copy.

`tasks.insert` can succeed while the client sees a timeout or crashes. A plain replay then makes a duplicate. So the service writes an attempt mark before insert. On replay with a mark and no map entry, it looks for one unmapped task with the same title, notes, and due date, updated since the mark. If found, it adopts that id. Else it inserts.

## Rejected

- Hidden marker in `notes`: other clients show it, phone edits remove it.
- No protection (syncall's approach): a timeout after insert makes a duplicate.

## Consequence

Two identical captures that both fail in the insert window can merge. Accepted as rare.
