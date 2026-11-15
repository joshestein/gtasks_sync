# Local ids, an id map, and adoption on replay

Google mints task ids, so the extension cannot know a task's id at capture. The extension mints a local id instead. The service maps local id to task id in `state.json`. `cache.json` carries `local_id`, so the extension matches a pending task to its synced copy.

`tasks.insert` can succeed while the client sees a timeout or crashes. A plain replay then makes a duplicate. So the service writes an attempt mark before insert. On replay with a mark and no map entry, it looks for unmapped open top-level tasks with the same title, notes, and due date, updated since the mark. If exactly one exists, it adopts that id. Else it inserts: a wrong adopt loses the capture, a duplicate does not.

The mark must survive a power loss, so state writes use `F_FULLFSYNC` and fsync the directory.

## Rejected

- Hidden marker in `notes`: other clients show it, phone edits remove it.
- No protection (syncall's approach): a timeout after insert makes a duplicate.

## Consequence

Two identical captures that both lose their insert response make duplicates. Accepted as rare.
