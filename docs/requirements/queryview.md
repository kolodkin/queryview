# QueryView — what a user needs

What a user can do with QueryView, each proven by a test in
`e2e/acceptance.spec.ts`. How it looks and behaves is on the system page each
section links; [queryview.md](../system/queryview.md) lists the app's pages.

## Add a connection

<!-- req: add-connection -->
A user can save a connection to a ClickHouse, Postgres, MySQL, DuckDB or SQLite
database.

- Each of the five drivers offers a new-connection form: host, port and
  credentials, or a file path for DuckDB and SQLite.
- Connecting saves the connection under the name given; it is listed among the
  saved connections when the user comes back.

See [connect.md](../system/connect.md#creating-a-connection).

## Open a database

<!-- req: open-database -->
A user can open a saved connection, pick a database, and find it reconnected
next time.

- Opening a saved connection offers its databases to pick from, narrowed by
  typing.
- Picking one opens its tables and shows the connection and database in use.
- Opening the app again reconnects to the same connection and database; the
  saved connection is marked active and reopens on that database.
- The database can be switched from any page.

See [connect.md](../system/connect.md#database-picker) and
[session.md](../system/session.md).

## Run SQL

<!-- req: run-sql -->
A user can run SQL, page through the rows, pick columns, and download CSV.

- Running a query shows its rows under its column names.
- A page size splits the rows into pages the user steps through.
- Hiding a column removes it from the results; showing it brings it back.
- The current page downloads as a CSV file.

See [query.md](../system/query.md).

## Run a script

<!-- req: run-script -->
A user can run a multi-statement script, writes included, that stops at the
first error.

- A `;`-separated script runs as written, `CREATE` and `INSERT` included, and
  shows the last statement's rows.
- A failing statement stops the run: the user is told which one failed and
  why, and the statements after it do not run.

See [scripts.md](../system/scripts.md).

## Browse tables

<!-- req: browse-tables -->
A user can browse tables and page through their rows without typing SQL.

- The connected database's tables are listed, with row estimates where the
  database keeps them.
- Picking a table shows its rows.
- The rows can be ordered by a column, a column hidden, and the rows paged.

See [explorer.md](../system/explorer.md).

## Live dashboard

<!-- req: live-dashboard -->
A user can open a saved dashboard that re-runs its queries against live data.

- A saved dashboard is listed and opens by its link.
- Opening it shows its queries' results as they are now: rows added since it
  was saved appear.

<!-- req: dashboard-many-connections -->
A user can open one dashboard that shows data from several connections side
by side, and see which connections it uses and whether each answered.

See [dashboard.md](../system/dashboard.md).

## Back up a workspace to git

<!-- req: workspace-git -->
A user can back a workspace up to a git remote and restore a dashboard from it.

- Each save of a dashboard is a commit on the workspace's remote.
- A dashboard changed outside git is marked as such.
- The dashboard's revisions are listed; restoring one brings that version back
  and clears the mark.

See [gitsync.md](../system/gitsync.md) and [workspace.md](../system/workspace.md).

## Move a dashboard as YAML

<!-- req: yaml-export-import -->
A user can move a dashboard between instances as YAML.

- Export downloads the dashboard as a YAML file.
- Importing that file saves the dashboard as it was exported, over any copy of
  the same name.

See [export-import.md](../system/export-import.md).

## Let an agent drive the tab

<!-- req: agent-drives -->
A user can have an agent run a query in the user's open tab over MCP.

- Once the user allows remote control, a script the agent sends appears in the
  tab and runs there.
- While the user is typing, the agent's script is refused and the user's text
  kept.
- Once the user withdraws remote control, the agent can no longer reach the
  tab.

See [mcp.md](../system/mcp.md).

## Design principles

- **Click, don't type.** Every connection is a card; nothing needs a name
  remembered or a command learned.
- **One thing at a time.** The cards, a form or a picker — never two at once.
- **State is visible.** Once a database is selected, the top-left indicator
  makes the active connection and database obvious from anywhere.
- **Resumable.** A session restores where you left off — page, connection and
  query — so a refresh costs nothing and the common case needs no typing at all.

## Related docs

- [queryview.md](../system/queryview.md) — the Connect page and the app's pages.
- [connect.md](../system/connect.md) — connections, drivers and the database picker.
- [session.md](../system/session.md) — what a session remembers.
- [query.md](../system/query.md) — querying: pagination, the results grid, CSV.
- [scripts.md](../system/scripts.md) — the SQL scratchpad.
- [explorer.md](../system/explorer.md) — the table navigator.
- [dashboard.md](../system/dashboard.md) — dashboards.
- [gitsync.md](../system/gitsync.md) — git backup and restore.
- [workspace.md](../system/workspace.md) — workspaces.
- [export-import.md](../system/export-import.md) — YAML export and import.
- [mcp.md](../system/mcp.md) — the MCP server.
