# QueryView

A local SQL workbench for **ClickHouse**, **Postgres**, **DuckDB** and **SQLite** — and a
place to let an AI agent do the querying for you.

Pick a saved connection from its card to open a database, then **QueryView** to
run SQL, **Scripts** to run a script of statements as written, **Explorer** to
click through tables, **Dashboard** to open a saved dashboard. Saved queries and dashboards live in workspaces that can back
themselves up to a git remote. A built-in MCP server lets an agent run
read-only queries, push a query or a whole dashboard into your open browser tab,
and snapshot your work to git.

QueryView is a **single-user tool that runs on your own machine**. It has no
login and assumes it is reachable only from localhost — don't expose its port.

## Quick start

```bash
uvx queryview
```

`--port` (or the `PORT` env var) picks the listen port, default 8000: `uvx queryview --port 9000`.

Then register the MCP server with Claude Code:

```bash
claude mcp add --scope user --transport http queryview http://localhost:8000/mcp/
```

`--scope user` is recommended: QueryView is one local server, so registering it
once makes it available in every project instead of only the current one.

Prefer Docker? See [docker.md](docs/docker.md).

## What you can do

Open http://localhost:8000 — it lands on the **Connect** page:

| Page | What happens |
|---|---|
| **Connect** → *New connection* card | Create a ClickHouse, Postgres, DuckDB or SQLite connection — host, port and credentials, or a file path for DuckDB and SQLite. Passwords are encrypted at rest. |
| **Connect** → a saved card | Open a saved connection and pick a database — that opens the explorer. The last one reconnects automatically next time. |
| **QueryView** | Run SQL: paginated results, column picker, save/load reusable queries, download the page as CSV. |
| **Scripts** | A flat SQL scratchpad: run the statement under the cursor or the whole `;`-separated script as written — writes and DDL included, stopping at the first error — see the last statement's rows, hand it to QueryView. |
| **Explorer** | Browse tables without typing SQL — a sidebar of tables with row/size estimates, click to page through rows. |
| **Dashboard** | Open a saved dashboard: an HTML layout that re-runs its queries against live data every time you open it. |

Beyond those pages:

- **Workspaces** group your saved queries and dashboards, and each can sync to
  its own git remote for backup, history and restore —
  [workspace.md](docs/workspace.md), [gitsync.md](docs/gitsync.md).
- **YAML export/import** moves a single query, a dashboard, or a whole
  workspace between instances with no git involved —
  [export-import.md](docs/export-import.md).
- **MCP** lets an agent query your databases and author dashboards — see
  [below](#mcp-server).

## MCP server

The backend mounts a FastMCP server (Streamable HTTP) at
`http://localhost:8000/mcp/`. There is nothing extra to start — it runs inside
the server process (`uvx queryview`, `npm run dev`, ...). Registering the client
is a separate, one-time step on the machine running the agent: an HTTP MCP
server can't install itself into someone else's client.

```bash
claude mcp add --scope user --transport http queryview http://localhost:8000/mcp/
```

Three things to get right:

- **Prefer the trailing slash.** The mount serves `/mcp/`. The slashless
  `/mcp` also works — it 307-redirects — but registering the canonical path
  skips a round trip on every call.
- **Match the port.** The URL must point at the port QueryView actually
  listens on — `--port 9000` means `http://localhost:9000/mcp/`, and
  `docker run -p 9000:8000` means the *host* port, `9000`, not the container's
  `8000`.
- **Start QueryView first.** The client dials this URL when it starts; if
  nothing is listening it reports a connection error and stays failed until you
  reconnect it.

QueryView is a **local, single-user tool**: it assumes it is reachable only from
localhost. `/mcp/` is unauthenticated, and its tools can query every configured
connection and rewrite workspace git state, so don't publish the port. Bind the
container to loopback — `docker run -p 127.0.0.1:8000:8000 ...` — since a plain
`-p 8000:8000` listens on all interfaces.

Tools: `session_info` (the session's connection, database, databases,
workspace and tables), `run_sql` (read-only SQL on the session's connection,
rows returned to the agent), `run_script` (a script with writes, per-statement
results returned to the agent), `push_query`, `push_script` and `push_dashboard` (fill a live browser session),
`list_queries` / `list_dashboards`, and `git_store` / `git_history` /
`git_restore` (workspace git backups). `session_info`, `run_sql` and the push tools target an **armed** browser session: enable
"Allow remote control" from the agent icon next to the connection pill and use
the session id it shows. See [docs/remote.md](docs/remote.md) for the full
protocol.

## Where your data lives

All state lives in one data directory, `~/.queryview` on every OS, relocated
with `DATA_DIR`. Inside are the SQLite store `db.sqlite`, the local
password-encryption key `encryption.key`, and the workspace git-sync clones
under `gitsync/`. Back that directory up — or give each workspace a git remote
and let [git sync](docs/gitsync.md) do it.

## Documentation

- [queryview.md](docs/queryview.md) — the Connect page and the app's pages.
- [connect.md](docs/connect.md) — connections, drivers, storage.
- [session.md](docs/session.md) — sessions: what a tab remembers, refresh and
  new-tab behaviour, the session switcher.
- [query.md](docs/query.md) — the query panel: pagination, predefined queries, CSV.
- [explorer.md](docs/explorer.md) — the table navigator.
- [dashboard.md](docs/dashboard.md) — dashboards and how agents author them.
- [workspace.md](docs/workspace.md) — workspaces.
- [gitsync.md](docs/gitsync.md) — git backup, history and restore.
- [export-import.md](docs/export-import.md) — YAML export and import.
- [remote.md](docs/remote.md) — the remote-control protocol behind the MCP push tools.
- [api.md](docs/api.md) — the full HTTP endpoint reference.
- [docker.md](docs/docker.md) — running the container image and persisting its state.

## Contributing

Development setup, tests and the release process are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).
