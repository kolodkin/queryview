# MCP server

QueryView serves an MCP server (Streamable HTTP) at `http://localhost:8000/mcp/`,
inside the same process — nothing extra to start. Register it once with your
agent:

```bash
claude mcp add --scope user --transport http queryview http://localhost:8000/mcp/
```

- **Match the port:** `--port 9000` or `docker run -p 127.0.0.1:9000:8000`
  means `http://localhost:9000/mcp/`.
- **Start QueryView first:** a client that finds nothing listening stays failed
  until you reconnect it.
- **Keep the trailing slash:** `/mcp` works too, but costs a redirect per call.
- **Localhost only:** `/mcp/` has no auth and can query every connection and
  rewrite workspace git state. Don't expose the port.

## Tabs

An agent works in browser tabs of its own, one per task, and leaves your
sessions alone unless you hand it an id. `new_tab(name)` creates a
[tab session](./session.md#tabs) and returns its `session_id` and `url`,
`<origin>/?session=<id>`. The agent opens the link in your browser (`open` on
macOS, `xdg-open` on Linux) or gives it to you; the tab lists as
**Agent › orders**, arms itself on load, and is gone once closed. The agent
connects it with `use_connection` or `add_connection`, then pushes into it as
into any session; a push made before the link is opened waits for it, a minute
at most, and every reply about a tab carries its `url`.

## Arming a session

Remote control is **opt-in**, per browser session, and off by default. Once a
database is selected, an **agent icon** sits next to the connection status pill.
Click it and toggle **Allow remote control**. The popover then shows this
session's **id** and a copyable command, e.g.:

> Use the queryview mcp to connect to session "a1b2c3" (Session 1)

Turning the toggle off (or closing the tab) disarms the session immediately —
pushes to its id are then reported as not delivered.

Without a copied id the agent works in a [tab](#tabs) of its own.

## Agent skill

The server publishes one skill over the MCP Skills extension,
`skill://queryview/SKILL.md` ([source](../backend/queryview/skills/queryview/SKILL.md)):
the default workflow for tabs, connections, SQL, Studio results and dashboards.
Naming a tool overrides it.

## Tools

Every tool acts on a browser session: a [tab](#tabs) of the agent's own, or one
you [armed](#arming-a-session).

- `push_query(session_id, query, limit?=100, offset?=0, order_by?, fields?, cell_view?, name?)` —
  push a query. `order_by` is `[{name, dir}]`; `fields` are the columns to show
  (omit for all); `cell_view` is raw YAML for this push only (not persisted);
  `name` selects a saved query to [edit](#naming-and-saving). Returns
  `{ok, message, database}` (`database` is the session's selected DB) —
  `ok:false` for
  an unknown id, a held lock (`"blocked, user editing"`), or malformed
  `order_by`/`fields` (`"invalid …"`).
- `list_queries(conn_type?="clickhouse")` — list saved queries:
  `{queries: [{query_name, query, cell_view, order_by, fields}]}`. Pass a
  `query_name` back as `push_query`'s `name`.
- `session_info(session_id)` — what the session is on: `{ok, connected,
  connection, type, database, databases, workspace, tables: [{name, …}]}`
  (`tables` lists the selected database's). The starting point for schema
  discovery. The agent may switch to any listed connection (below).
- Connections ([access rule](./connect.md#session-connections)):
  `list_connections(session_id)` tags each with `scope`, `created_by`,
  `active`, leaving out [locked](./connect.md#locked-connections) ones;
  `list_databases(session_id, connection?)` lists the databases of each listed
  connection, or of `connection` only.
  `add_connection(session_id, name, type, config)` adds a ClickHouse or
  Postgres session connection; `use_connection(session_id, name, database?)`
  works on any unlocked ClickHouse or Postgres one (not DuckDB or SQLite: they
  read local files), `select_database(session_id, database)` on any unlocked
  active one; `remove_connection(session_id, name)` only on the agent's own.
  In the browser, an add/remove refreshes an armed tab's connection lists
  (pill menu, Connect). A `use_connection` marks the session row `connection_by: agent`;
  every tab picks it up on its next heartbeat, toasts "Agent switched to
  <name>", and the pill reads `<connection> · <database>` with the menu entry
  marked active and badged `agent`. Switches made in the UI never toast.
- `run_sql(session_id, sql, limit?=1000)` — run one read-only statement as
  written (so `DESCRIBE`/`SHOW`/`EXPLAIN` work; page with your own
  `LIMIT`/`OFFSET`) on the session's connection and database, returning
  `{ok, database, columns, types, rows, truncated}` to the agent. Values are
  typed as the driver returns them (64-bit integers and decimals as strings,
  collections as JSON); `truncated` means rows past `limit` were dropped. Fails
  with `not connected` on a disconnected session; stops after 60s, server-side
  too. ClickHouse errors name the `query_id` to look up in `system.query_log`.
- `run_script(session_id, sql)` — run a script like the [Scripts](./scripts.md)
  page's Run all, **writes included**, returning `{ok, database, results: [{sql,
  ok, status, message, columns, types, rows, truncated, elapsed_ms}]}` to the
  agent. Stops at the first failure; `columns`/`types`/`rows` are null for a
  statement without rows.
- `push_script(session_id, sql, run?=false)` — replace the Scripts editor's
  text; the browser navigates there and, with `run`, runs it all (results stay
  in the browser). Returns
  `{ok, message, database}`; `ok:false` for an unknown id, a held lock
  (`"blocked, user editing"`), or a session whose Scripts page can't open yet
  (`"not connected"`, `"select a database first"`).
- `open_explorer(session_id, database, table?)` —
  switch the session to `database` and send the browser to its
  [Explorer](./explorer.md), on `table` when given (refused when the database
  doesn't list it). Returns `{ok, message, database}`; past the switch, a
  failure still leaves the session on `database`.
- `push_dashboard(session_id, html, queries, params?, name?)` — push a dashboard
  **draft** on the session's connection; the browser navigates to it and
  renders it. `name` selects a saved dashboard to
  [edit](#naming-and-saving). Returns
  `{ok, pushed, persisted, message, database}`; a disconnected session fails with
  `not connected`. See [dashboard.md](./dashboard.md).
- `new_tab(name)` — a session of the agent's own; see [Tabs](#tabs).
- `list_dashboards()` — list saved dashboards: `{dashboards: [{name, updated_at}]}`.
- `git_store` / `git_history` / `git_restore` — back up, list and restore a
  saved query or dashboard through [workspace git](./gitsync.md).

The pushed query runs through the normal `POST /api/db/query`, so all of
that path's pagination and order-by safety applies; the push layer never talks
to ClickHouse directly.

## Naming and saving

The agent drafts and edits; the user names and saves.

- **New work is unnamed.** `push_query` and `push_dashboard` without `name`
  push a draft. The user names it: **+ New name…** in the Studio, the prompt
  of the dashboard's **Save**, which refuses a name already taken.
- **`name` only edits.** It must be a saved query (`list_queries`) or dashboard
  (`list_dashboards`); any other is refused with `no saved query named "…"`.
- **A push persists nothing.** The user's **Save** does. An unnamed query push
  also deselects the open query, so Save cannot write the draft over it.
- **Autosave is the exception.** In an [autosave](./workspace.md#autosave)
  workspace a push naming a saved item saves over it: a dashboard on delivery
  (`persisted: true`), a query once its auto-run succeeds. An unnamed draft
  still waits for the user.

## How it works

When armed, the browser opens an SSE stream
(`GET /api/remote/events?session=<id>`); the backend registers an in-memory
channel **keyed by that session's id** (see [session.md](./session.md)).
`push_query` (and the test-only `POST /api/remote/push`) enqueue onto that
channel; the SSE stream delivers the payload and the panel fills `query` /
`limit` / `offset` / `order_by` / selected `fields` and runs.

Because the channel is named after a session, the agent's session-scoped tools
read that session's database and workspace straight from its row — the browser
reports nothing (see [workspace.md](./workspace.md)).

A push to a [tab](#tabs) nobody has opened yet lands in a channel `new_tab`
opened in advance, which answers `queued for the tab`; arming takes that
channel over with its pushes queued. One whose tab never comes is dropped
after a minute.

**Locked connections keep the agent out.** A saved connection the user
[locked](./connect.md#locked-connections) behind a passphrase refuses every
tool above while a session is on it (`connection is locked`), and refuses REST
calls without the tab's unlock token too, so copying a session id into
`/api/db/query` gets the agent nowhere.

**Arming is the gate, not the id.** Disarming closes the channel, and any later
push fails with `unknown or inactive session`. The id is stable across refreshes
and re-arms, so the command you copy stops changing under you; equally, an id
you have shared stays usable whenever that session is armed.

State is in-memory and per-process (like the active-connection session map): a
backend restart drops channels; the browser reconnects while armed and gets a
new id.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [session.md](./session.md) — sessions and agent tabs.
- [dashboard.md](./dashboard.md) — how agents author dashboards.
- [query.md](./query.md) — running queries: pagination, fields, order-by, CSV.
- [docker.md](./docker.md) — port mapping when running the container.
