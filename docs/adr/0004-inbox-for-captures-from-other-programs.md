# inbox/ takes captures from other programs

Another program writes a JSON file to `inbox/<name>.json` and touches `queue/sync-now`. At the start of each round, the service turns each file into a `create` op in `queue/`, then deletes the file. A caller needs only a path, and the op format stays in two places.

The file is JSON, not plain text, so fields can be added later (notes, due date, capture time) without a change to every caller. `text` is required. The service ignores fields it does not know.

Raycast stays on `queue/`. It needs the local id at capture time (ADR 0001), and it writes ops other than `create`.

A crash between the op write and the delete makes a duplicate task. Accepted.
