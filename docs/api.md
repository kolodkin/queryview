# API

The FastAPI backend exposes a small JSON API under `/api/*`. ClickHouse queries
run over the HTTP interface with HTTP Basic auth and a 5s timeout. All
connection-config bodies validate `host` (non-empty) and `port` (integer
`1..65535`); validation errors return `400`.

**Sessions:** every `/api/*` request names its session with an `X-QV-Session`
header; there is no session cookie. A session is a persisted row holding one
tab's UI state — route, connection, database, workspace, view settings — so two
tabs can be on two different connections at once. `/session`, `/connect`,
`/open` and `/database` act on the header's session. Saved connections are
shared (SQLite). See [session.md](./session.md).

| Method | Path                        | Body                                   | Description |
| ------ | --------------------------- | -------------------------------------- | ----------- |
| GET    | `/api/health`               | —                                      | Service health check. |
| GET    | `/api/session`              | —                                      | This session's connection state `{connected, name?, type?, databases?, database?}`, reconnecting the connection the session is on. |
| POST   | `/api/db/test`      | `{host,port,username,password}`        | Test a connection (test only — no save, no activation). `{ok, message}`. |
| POST   | `/api/db/connect`   | `{name,host,port,username,password}`   | Create: open + save + activate for this session; lists databases (`new <type>` form). `{ok, name, databases}` \| `{ok:false, message}`. |
| POST   | `/api/db/open`      | `{name}`                               | Open a saved connection by name for this session; lists databases (`connect <name>`). `{ok, name, databases}` \| `{ok:false, message}`. |
| POST   | `/api/db/database`  | `{database}`                           | Select this session's active connection's database. `{ok}`. |
| POST   | `/api/db/query`     | `{query, limit?, offset?, format?, order_by?}` | Run SQL against this session's selected database, paginated by `limit`/`offset` (defaults 100/0). `order_by` is `[{name, dir}]` (`dir` ASC/DESC, names quoted with the driver's identifier quote) sorting the pagination wrapper. `{ok, meta:[{name, type}], data:[[…]]}` — ClickHouse's `JSONCompact` shape, 64-bit integers and decimals quoted, collections as JSON arrays/objects — \| `{ok:false, message}`. `format:"csv"` returns `{ok, output}` (CSV text) instead. Empty query → `400`; no session → `409`. |
| POST   | `/api/db/describe`  | `{query}`                              | Describe the query's output columns via ClickHouse `DESCRIBE` (no data scanned). `{ok, fields:[{name, type}]}` \| `{ok:false, message}`. Empty query → `400`; no session / no database → `409`. |
| GET    | `/api/db/tables`    | —                                      | Tables of this session's selected database (the Explorer sidebar). `{ok, tables:[{name, rows, bytes, query}]}` — rows/bytes are engine estimates (null when untracked); `query` is the browse SELECT quoted with the driver's identifier quote — \| `{ok:false, message}`. No session / no database → `409`. |
| GET    | `/api/predefined-queries`   | `?type=<connType>&workspace=`          | A workspace's predefined queries for a connection type (`workspace` defaults to `default`). `{queries:[{query_name, query, cell_view}]}`. `cell_view` is raw YAML text (or `null`) — see [query.md](./query.md#cell-views). |
| POST   | `/api/predefined-queries`   | `{query_name, type, query, cell_view?, workspace?}` | Upsert a predefined query in a workspace. `cell_view` is optional raw YAML text, validated against the contract in [query.md](./query.md#cell-views); empty/missing clears it. `{ok}`; missing required fields or malformed `cell_view` → `400`. |
| POST   | `/api/sessions/attach`      | `{tab, session_id?}`                   | Resolve and claim this tab's session: its own id if free, else the most recent unheld session, else a new one. Doubles as the 30s-TTL claim heartbeat. `{ok, created, session}`. Missing `tab` → `400`. |
| POST   | `/api/sessions/select`      | `{tab, id?}`                           | Switch this tab to session `id`, or to a brand-new session when `id` is omitted. `{ok, session}`; a session another live tab holds → `409`. |
| GET    | `/api/sessions`             | —                                      | Every session, most recently active first: `{sessions:[{id, label, pinned, connection, database, held, last_active_at}]}`. |
| PATCH  | `/api/sessions/{id}`        | `{url?, ui?, label?, workspace?}`      | Update a session. `ui` merges per view namespace; the rest replace. An empty `label` unpins. `{ok}`; unknown id → `404`. |
| DELETE | `/api/sessions/{id}`        | —                                      | Delete a session. `{ok}`; held by a live tab → `409`, unknown → `404`. |
| POST   | `/api/sessions/release`     | `{tab}`                                | Free whatever this tab holds — the `pagehide` beacon. `{ok}`. |
| GET    | `/api/remote/events`        | `?session=<id>`                        | SSE stream a browser opens when "remote control" is armed; the channel is keyed by that session id (`EventSource` cannot send the header). Emits a `ready` event (`{id}`) then `query` and `dashboard` events with pushed payloads (each emitted under the SSE event named by the payload's `type`). |
| POST   | `/api/remote/push`          | `{session_id, query, limit?, offset?, order_by?, fields?}` | Push a query to a live armed session (`session_id` is the session's id) (the surface `push_query` and the e2e suite use). `{ok}` \| `{ok:false, message}` (unknown session). Empty `query`/`session_id` → `400`. |
| POST   | `/api/runqueries`           | `{connection, queries:{name:SQL}}`     | Run a dashboard's named queries against a saved connection (by name), using its stored database. Fail-fast: `{ok, results:{name:{col:[…]}}, meta:{name:[{name, type}]}}` (column-oriented, values typed as the driver returns them) on full success; on any failure an HTTP error with `{ok:false, message}` — `404` unknown connection, `400` bad body / no selected database / a failing query (message prefixed with the panel name). See [dashboard.md](./dashboard.md). |
| POST   | `/api/dashboards`           | `{name, connection, html, queries, session_id?, workspace?}` | Upsert a dashboard by name within a workspace; with `session_id`, also pushes it to that live session. `{ok, persisted, pushed, message}`. Missing `name`/`connection`/`html` → `400`. |
| GET    | `/api/dashboards`           | `?workspace=`                          | List a workspace's dashboards (no payload): `{dashboards:[{name, connection, updated_at}]}`, ordered by name. |
| GET    | `/api/dashboards/{name}`    | `?workspace=`                          | A saved dashboard `{name, connection, html, queries}` (`queries` parsed to a dict), or `404 {error:"not found"}`. |

**MCP:** a FastMCP server is mounted at `/mcp/` (Streamable HTTP) exposing
`push_query` (push SQL to a session's query panel), `push_dashboard` (push a
dashboard draft to a session), `run_query`, `list_queries` / `list_dashboards`
and `git_store` / `git_history` / `git_restore`. They delegate to the in-process
hubs the matching REST endpoints call. See [remote.md](./remote.md) and
[dashboard.md](./dashboard.md).

## Persistence

Connections are stored in SQLite via SQLModel. See [connect.md](./connect.md)
for the schema, and [session.md](./session.md) for the session model.

## Workspaces

Predefined queries and dashboards belong to a workspace; each workspace syncs
to its own git remote. The remote URL may embed a token — it is encrypted at
rest and never returned by the API. See [workspace.md](./workspace.md).

| Method | Path                      | Body                          | Description |
| ------ | ------------------------- | ----------------------------- | ----------- |
| GET    | `/api/workspaces`         | —                             | List workspaces: `{workspaces:[{name, branch, configured}]}` (never the remote URL). |
| POST   | `/api/workspaces`         | `{name, remote?, branch?}`    | Create a workspace. `{ok}`; empty/`/`-containing name → `400`, duplicate → `409`. |
| PATCH  | `/api/workspaces/{name}`  | `{name?, remote?, branch?}`   | Rename/reconfigure. A null `remote` clears it; an absent key leaves it unchanged. `{ok}`. |
| DELETE | `/api/workspaces/{name}`  | —                             | Delete an empty workspace. `{ok}`; unknown → `404`, still owns entities → `409`. |

## YAML export / import

Predefined queries and dashboards can be downloaded as self-describing YAML
documents and imported back — per entity or a whole workspace at once. See
[export-import.md](./export-import.md) for the document shapes.

| Method | Path          | Body / params                              | Description |
| ------ | ------------- | ------------------------------------------ | ----------- |
| GET    | `/api/export` | `?kind=&name=&conn_type=&workspace=`       | Download one entity (`kind` `query`/`dashboard`, `name`, `conn_type` for queries) or the whole workspace (`kind=workspace`) as YAML, with a `Content-Disposition` filename. `400` bad args, `404` unknown entity/workspace. |
| POST   | `/api/import` | raw YAML body, `?workspace=`               | Import a document into a workspace, upserting by name; the document's `kind` decides what is written. `{ok, kind, queries, dashboards}`. `400` malformed document. |

## Git sync

Predefined queries and dashboards can be backed up to (and restored from) each
workspace's git repository, per entity. Connections are never written to the
repo. See [gitsync.md](./gitsync.md) for configuration, repository layout, and
the UI.

| Method | Path              | Body                                            | Description |
| ------ | ----------------- | ------------------------------------------------ | ----------- |
| GET    | `/api/git/status`  | `?workspace=`                                    | Whether the workspace has a git remote configured. `{configured}`. |
| POST   | `/api/git/store`   | `{kind, name, conn_type?, message?, workspace?}` | Commit the entity's saved DB state and push. `{ok, committed, sha, message}`. |
| GET    | `/api/git/history` | `?kind=&name=&conn_type=&before=&limit=10&workspace=` | The entity's revisions, newest first. `{ok, revisions: [{sha, date, message}], has_more}`. |
| POST   | `/api/git/restore` | `{kind, name, conn_type?, ref?, workspace?}`     | Overwrite the local DB row with the entity's content at `ref`. `{ok, restored, sha}`. |

`kind` is `"query"` or `"dashboard"`; `conn_type` is required for queries;
`workspace` defaults to `default`. MCP tools `git_store`, `git_history`,
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](./workspace.md)).

## Related docs

- [queryview.md](./queryview.md) — the single-prompt page concept.
- [connect.md](./connect.md) — connecting (`new <type>` / `connect <name>`), storage, sessions.
- [query.md](./query.md) — running queries: pagination, predefined queries, CSV.
- [remote.md](./remote.md) — pushing queries to a live session over MCP.
- [dashboard.md](./dashboard.md) — the dashboard page, `upsert_dashboard`, and the `window.queries` contract.
- [gitsync.md](./gitsync.md) — backing up and restoring queries and dashboards via git.
- [export-import.md](./export-import.md) — YAML export/import of queries, dashboards and workspaces.
- [workspace.md](./workspace.md) — workspaces: entity ownership and per-workspace remotes.
