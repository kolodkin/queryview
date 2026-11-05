# QueryView

A local SQL workbench for **ClickHouse**, **Postgres**, **DuckDB** and **SQLite** — and a
place to let an AI agent do the querying for you.

Pick a saved connection from its card to open a database, then **Studio** to
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

Ask your agent ([MCP usage](docs/mcp.md)) — it drives the page for you in your open tab at
http://localhost:8000. Or do it by hand on that page:

| Ask your agent | Or open this page | What happens |
|---|---|---|
| *Use queryview to add a Postgres connection to db.example.internal:5432 user: read-only pwd: xxx* | **Connect** → *New connection* card | Create a ClickHouse, Postgres, DuckDB or SQLite connection — host, port and credentials, or a file path for DuckDB and SQLite. Passwords are encrypted at rest. |
| *Use queryview to switch to the sales_reporting database* | **Connect** → a saved card | Open a saved connection and pick a database — that opens the explorer. The last one reconnects automatically next time. |
| *Use queryview to show me the top 10 customers by revenue this month* | **Studio** | Run SQL: paginated results, column picker, save/load reusable queries, download the page as CSV. |
| *Use queryview to create a staging table and copy last week's orders into it* | **Scripts** | A flat SQL scratchpad: run the statement under the cursor or the whole `;`-separated script as written — writes and DDL included, stopping at the first error — see the last statement's rows, hand it to Studio. |
| *Use queryview to open the orders table in the explorer* | **Explorer** | Browse tables without typing SQL — a sidebar of tables with row/size estimates, click to page through rows. |
| *Use queryview to build a dashboard of daily signups and revenue for the last 30 days* | **Dashboard** | Open a saved dashboard: an HTML layout that re-runs its queries against live data every time you open it. |

Beyond those pages:

- **Workspaces** group your saved queries and dashboards, and each can sync to
  its own git remote for backup, history and restore —
  [workspace.md](docs/workspace.md), [gitsync.md](docs/gitsync.md).
- **YAML export/import** moves a single query, a dashboard, or a whole
  workspace between instances with no git involved —
  [export-import.md](docs/export-import.md).
- **MCP** lets an agent query your databases and author dashboards — see
  [mcp.md](docs/mcp.md).

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
- [mcp.md](docs/mcp.md) — connecting an agent and what it can do.
- [remote.md](docs/remote.md) — the remote-control protocol behind the MCP push tools.
- [api.md](docs/api.md) — the full HTTP endpoint reference.
- [docker.md](docs/docker.md) — running the container image and persisting its state.

## Contributing

Development setup, tests and the release process are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).
