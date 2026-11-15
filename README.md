# gtasks-sync

Fast Google Tasks capture and search on macOS. A Python service syncs your default task list ("My Tasks") in the background. A Raycast extension reads and writes only local files, so it never waits on the network.

## Setup

Requires macOS, [uv](https://docs.astral.sh/uv/), Node, and Raycast.

1. In [Google Cloud Console](https://console.cloud.google.com), make a project and enable the **Google Tasks API**.
2. Under **Google Auth Platform**: set the user type to External, add the scope `.../auth/tasks`, and **publish the app** (status "In production"). In "Testing", Google expires the token after 7 days.
3. Under **Clients**, make a client of type **Desktop app** and download its JSON file.
4. Run:

```sh
cd service && uv sync
uv run gtasks-sync setup --client-secret path/to/client_secret.json   # browser sign-in, Keychain, launchd agent
cd ../raycast && npm install && npm run dev
```

At sign-in, Google shows "unverified app". Click **Advanced**, then **Go to … (unsafe)**. This is your own app.

## Use

- **New Task**: title, optional due date and notes. Submit, and the window closes at once.
- **Tasks**: open tasks by due date, then tasks completed in the last 7 days. Return completes or reopens. ⌘E edit, ⌘N new, ⌘O open in Google Tasks, ⌃X delete, ⌘D details, ⌘R sync now.
- **Other programs**: write `{"text": "buy milk"}` to `inbox/<name>.json` in the data folder (write `<name>.json.part`, then rename it), then touch `queue/sync-now`. Each file becomes a new task. A bad file goes to `inbox/failed/` ([ADR 0004](docs/adr/0004-inbox-for-captures-from-other-programs.md)).

A clock on a task means Google has not received the change yet. A red mark means the change failed: see the log.

## Commands

```sh
uv run gtasks-sync status            # agent, last sync, error, queued / accepted / failed ops, inbox files
uv run gtasks-sync install           # reload the agent, for example after a code change
uv run gtasks-sync uninstall [--purge]   # remove the agent; --purge also removes the Keychain item and local data
```

Log: `~/Library/Logs/gtasks-sync.log`. Data: `~/Library/Application Support/gtasks-sync/`.

## Develop

```sh
cd service && uv run pytest && uvx pyright
cd raycast && npm test && npm run typecheck && npm run lint
cd service && uv run python scripts/check_api.py   # checks the API behaviors the design depends on, on your real list
```

Terms: [CONTEXT.md](CONTEXT.md). Decisions: [docs/adr/](docs/adr/).
