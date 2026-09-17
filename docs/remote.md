# Remote control (MCP push to a live session)

An MCP client (e.g. an AI agent) can push a SQL query into a **live** QueryView
browser session. The targeted browser fills its query panel and auto-runs the
query — the browser is the consumer; the agent does not get results back.

## Arming a session

Remote control is **opt-in**, per browser session, and off by default. Once a
database is selected, an **agent icon** sits next to the connection status pill.
Click it and toggle **Allow remote control**. The popover then shows this
session's **id** and a copyable command, e.g.:

> Use the queryview mcp to connect to session "a1b2c3"

Turning the toggle off (or closing the tab) disarms the session immediately —
pushes to its id are then reported as not delivered.

## Connecting a client

The server runs inside the backend process — nothing extra to start — but the
client registration is a separate one-time step: point it at
`http://localhost:8000/mcp/` (the slashless `/mcp` redirects there; match the
port QueryView listens on, and start it first). See
[the README](../README.md#mcp-server).

## MCP tools

The backend mounts a FastMCP server (Streamable HTTP) at `/mcp/` exposing four
tools:

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
- `run_query(query, connection?="clickhouse", limit?=1000, offset?=0)` — run a
  read-only query and return rows to the agent (not the browser):
  `{ok, connection, database, columns, types, rows}` — values typed as the
  driver returns them (64-bit integers and decimals as strings, collections as
  JSON). `database` is the connection's
  currently-selected database
  (the user can change it from the pill), so the agent can tell what it's querying
  and whether to fully-qualify tables. For schema discovery / data inspection.
- `push_dashboard(session_id, name, connection, html, queries)` — push a
  dashboard **draft** to the session, which navigates to it and renders it.
  Does **not** persist — only the user's **Save** button in the dashboard view
  writes it to the store (mirrors `push_query`). Returns
  `{ok, pushed, message, database}`. See [dashboard.md](./dashboard.md).

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

**Arming is the gate, not the id.** Disarming closes the channel, and any later
push fails with `unknown or inactive session`. The id is stable across refreshes
and re-arms, so the command you copy stops changing under you; equally, an id
you have shared stays usable whenever that session is armed.

State is in-memory and per-process (like the active-connection session map): a
backend restart drops channels; the browser reconnects while armed and gets a
new id.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [queryview.md](./queryview.md) — the single-prompt page concept.
- [query.md](./query.md) — running queries: pagination, fields, order-by, CSV.
