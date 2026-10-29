# Remote control (MCP push to a live session)

An MCP client (e.g. an AI agent) can push a SQL query into a **live** QueryView
browser session. The targeted browser fills its query panel and auto-runs the
query — the browser is the consumer; the agent does not get results back.

## Arming a session

Remote control is **opt-in**, per browser session, and off by default. Once a
database is selected, an **agent icon** sits next to the connection status pill.
Click it and toggle **Allow remote control**. The popover then shows this
session's **id** and a copyable command, e.g.:

> Use the queryview mcp to connect to session "a1b2c3" (Session 1)

Turning the toggle off (or closing the tab) disarms the session immediately —
pushes to its id are then reported as not delivered.

Without a copied id the agent uses the standing
[Agent session](./session.md#the-agent-session); arm it the same way.

**Default workflow.** Asked to run a query, the agent evaluates with `run_sql`
(`run_script` for writes), iterates on the results, and finishes with
`push_script` of the final SQL, so it lands in the [Scripts](./scripts.md)
page — unless you name another tool (e.g. `push_query`). The server's MCP
instructions say so; no clarifying question is needed.

## Connecting a client

The server runs inside the backend process — nothing extra to start — but the
client registration is a separate one-time step: point it at
`http://localhost:8000/mcp/` (the slashless `/mcp` redirects there; match the
port QueryView listens on, and start it first). See
[the README](../README.md#mcp-server).

## MCP tools

The backend mounts a FastMCP server (Streamable HTTP) at `/mcp/` exposing these
tools (among others):

- `push_query(session_id, query, limit?=100, offset?=0, order_by?, fields?, cell_view?, name?)` —
  push a query. `order_by` is `[{name, dir}]`; `fields` are the columns to show
  (omit for all); `cell_view` is raw YAML for this push only (not persisted);
  `name` selects a saved query. Returns `{ok, message, database}` (`database` is
  the session's currently-selected DB, reported by the browser) — `ok:false` for
  an unknown id, a held lock (`"blocked, user editing"`), or malformed
  `order_by`/`fields` (`"invalid …"`).
- `list_queries(conn_type?="clickhouse")` — list saved queries:
  `{queries: [{query_name, query, cell_view, order_by, fields}]}`. Pass a
  `query_name` back as `push_query`'s `name`.
- `session_info(session_id)` — what the session is on: `{ok, connected,
  connection, type, database, databases, workspace, tables: [{name, …}]}`
  (`tables` lists the selected database's). The starting point for schema
  discovery. The agent switches only to its own session connections (below).
- Connections ([access rule](./connect.md#session-connections)):
  `list_connections(session_id)` tags each with `scope`, `created_by`,
  `active`, leaving out [locked](./connect.md#locked-connections) ones;
  `list_databases(session_id, connection?)` lists the databases of each listed
  connection, or of `connection` only.
  `add_connection(session_id, name, type, config)` adds a ClickHouse or
  Postgres session connection; `use_connection(session_id, name, database?)`,
  `select_database(session_id, database)` and `remove_connection(session_id,
  name)` act only on the agent's own. In the browser, an add/remove refreshes an
  armed tab's connection lists (pill menu, Connect). A `use_connection` marks
  the session row `connection_by: agent`; every tab picks it up on its next
  heartbeat, toasts "Agent switched to <name>", and the pill reads
  `<connection> · <database>` with the menu entry marked active and badged
  `agent`. Switches made in the UI never toast.
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
- `push_dashboard(session_id, name, html, queries, params?)` — push a dashboard
  **draft** on the session's connection; the browser navigates to it and
  renders it. Only the user's **Save** persists it, unless the workspace has
  [autosave](./workspace.md#autosave) on. Returns
  `{ok, pushed, persisted, message, database}`; a disconnected session fails with
  `not connected`. See [dashboard.md](./dashboard.md).

The pushed query runs through the normal `POST /api/db/query`, so all of
that path's pagination and order-by safety applies; the push layer never talks
to ClickHouse directly.

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
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — running queries: pagination, fields, order-by, CSV.
