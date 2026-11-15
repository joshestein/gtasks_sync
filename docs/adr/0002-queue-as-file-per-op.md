# The queue is a directory with one file per op

A single `queue.jsonl` that the service renames before it reads races: Node's append is open, write, close, so a write to an fd opened before the rename lands in a file the service already read and deleted. Node has no built-in `flock`. So the extension writes each op to a temp file and renames it into `queue/` as `<ms>-<8 hex>.json`. The service applies files in name order.

The directory a file is in is its stage: `queue/` (not yet accepted by Google), `queue/accepted/` (accepted, the cache does not show it yet), `queue/failed/` (can never succeed). The service moves a file with one rename, and deletes accepted files only after the cache has their result. No other record of an op's stage exists, so nothing can disagree with the files.
