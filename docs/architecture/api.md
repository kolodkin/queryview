# API

The FastAPI backend exposes a small JSON API under `/api/*`. ClickHouse queries
run over the HTTP interface with HTTP Basic auth, within the session's
[query timeout](../user_guide/queryview.md#query-timeout). All
connection-config bodies validate `host` (non-empty) and `port` (integer
`1..65535`); validation errors return `400`.

**Locked connections:** a request on a session whose active connection is
[locked](../user_guide/connect.md#locked-connections) must also carry the tab's unlock
token as `X-QV-Token`, or every data route answers `403 {ok:false, message:
"connection is locked"}`. `POST /api/db/unlock` issues the token for the
passphrase.

**Sessions:** every `/api/*` request names its session with an `X-QV-Session`
header; there is no session cookie. A session is a persisted row holding one
tab's UI state — route, connection, database, workspace, view settings — so two
tabs can be on two different connections at once.

<!-- req: session-scoped-api -->
`/session`, `/connect`, `/open` and `/database` act on the header's session.

Saved connections are shared (SQLite). See [session.md](../user_guide/session.md).

| Method | Path                        | Body                                   | Description |
| ------ | --------------------------- | -------------------------------------- | ----------- |
| GET    | `/api/health`               | —                                      | Service health check. |
| GET    | `/api/session`              | —                                      | This session's connection state `{connected, name?, type?, databases?, database?, root?, locked?, unlocked?}` (`root` only for a DuckDB folder), reconnecting the connection the session is on; `unlocked` says whether this request's `X-QV-Token` opens a locked one. |
| POST   | `/api/db/test`      | `{type, …driver config}`               | Test a connection (test only — no save, no activation). `{ok, message}`. |
| POST   | `/api/db/connect`   | `{type, name, session?, …driver config}` | Create: open + save + activate for this session; lists databases (new-connection form). `session:true` keeps it session-only. `{ok, name, type, databases, database, root?}` \| `{ok:false, message}`. |
| GET    | `/api/db/connections` | —                                    | This session's connections, then the saved ones most recent first: `{connections:[{name, type, database, last_active_at, scope, created_by, locked}]}` — metadata only, never the config. |
| GET    | `/api/db/connections/<name>` | —                             | A saved connection's config for the edit form, password blanked: `{ok, name, type, config}`. Unknown → `404`; locked without this tab's token → `403`. Re-saving via `POST /api/db/connect` with a blank password keeps the saved one. |
| DELETE | `/api/db/connections` | `{name, passphrase?}`                | Delete a connection (this session's own, else a saved one) and disconnect every session on it. `{ok}`; a locked one takes its passphrase (`403` without). |
| POST   | `/api/db/open`      | `{name}`                               | Open a connection by name for this session, its own session connections first (a card on the Connect page). `{ok, …}` plus the `/api/session` state \| `{ok:false, message}`; a [locked](../user_guide/connect.md#locked-connections) one lands with `unlocked:false` until this tab unlocks it. |
| POST   | `/api/db/lock`      | `{name, passphrase}`                   | Lock a saved connection; `{ok, token}`. `DELETE` with the same body removes the lock; `POST /api/db/unlock` exchanges the passphrase for this session's token. Wrong passphrase → `403`; an empty passphrase, an unknown or already locked connection, or unlocking one that is not locked → `400`. See [connect.md](../user_guide/connect.md#locked-connections). |
| GET    | `/api/db/databases` | —                                      | Re-list this session's connection's databases. `{ok, name, databases, databases_truncated?}` (`databases_truncated` when a DuckDB folder list was cut at the Explorer's Max entries) \| `{ok:false, message}`. No session → `409`. |
| POST   | `/api/db/database`  | `{database}`                           | Select this session's active connection's database; a name not in the cached list is re-listed once. `{ok}`. |
| POST   | `/api/db/query`     | `{query, limit?, offset?, format?, order_by?, params?, values?, connection?, database?}` | Run SQL against this session's selected database, paginated by `limit`/`offset` (defaults 100/0). `order_by` is `[{name, dir}]` (`dir` ASC/DESC, names quoted with the driver's identifier quote; one holding that quote character, or a backslash where the dialect escapes with it, fails the query with `{ok:false, message}`) sorting the pagination wrapper. `{ok, meta:[{name, type}], data:[[…]]}` — ClickHouse's `JSONCompact` shape, 64-bit integers and decimals quoted, collections as JSON arrays/objects — \| `{ok:false, message}`. `format:"csv"` returns `{ok, output}` (CSV text) instead. With `params` (a dashboard's declaration) and `values`, `query` is a template: its `{name}` placeholders are substituted server-side from `values` as given; a bad value or one still unchosen → `400` (see [dashboard.md](../user_guide/dashboard.md#dashboard-parameters)). With `connection` (a [federated](../designs/dashboards.md#which-connection-which-database) widget's query) it runs on that connection and `database`, not the session's, and a failed lookup is a `400` `{ok:false, reason:"query", message}`. Empty query → `400`; no session → `409`. |
| POST   | `/api/db/execute`   | `{sql}`                                | Run a `;`-separated script as written on this session's selected database — writes and DDL included, no pagination — statement by statement on one connection, stopping at the first failure (the Scripts page). `{ok, database, results:[{sql, ok, meta, data, truncated, status, message, elapsed_ms}]}`, one entry per statement run; `meta`/`data` for a row-returning statement (`data` capped at 100 rows), else `status` is the driver's word (`OK`, `INSERT 0 3`). See [scripts.md](../user_guide/scripts.md). Empty `sql` → `400`; no session / no database → `409`. |
| POST   | `/api/db/describe`  | `{query, params?, values?, connection?, database?}` | Describe the query's output columns via ClickHouse `DESCRIBE` (no data scanned). `{ok, fields:[{name, type}]}` \| `{ok:false, message}`. `params`, `values`, `connection` and `database` as for `/api/db/query`. Empty query → `400`; without `connection`, no session / no database → `409`. |
| GET    | `/api/db/tables`    | `?union=1` (optional)                  | Tables of this session's selected database (the Explorer sidebar). `{ok, tables:[{name, rows, bytes, query}]}` — rows/bytes are engine estimates (null when untracked); `query` is the browse SELECT quoted with the driver's identifier quote, or the driver's own `read_*` call for a DuckDB folder, where `union=1` adds `union_by_name` to glob entries and `truncated: true` marks a file list cut at the Explorer's Max entries — \| `{ok:false, message}`. No session / no database → `409`. |
| POST   | `/api/sessions/attach`      | `{tab, session_id?, keep?}`            | Resolve and claim this tab's session: its own id if free, else the most recent unheld named session, else a new one. Also sweeps unnamed sessions unheld and idle for 90s. Doubles as the 90s-TTL claim heartbeat, sent with `keep`: then a session another live tab holds → `409` instead of a different one. `{ok, created, session}`. Missing `tab` → `400`. |
| POST   | `/api/sessions/select`      | `{tab, id?, force?}`                   | Switch this tab to session `id`, or to a brand-new session when `id` is omitted; sweeps as `attach` does. `{ok, session}`; a session another live tab holds → `409`, unless `force` takes it over. |
| GET    | `/api/sessions`             | —                                      | Every session, most recently active first: `{sessions:[{id, label, pinned, connection, database, held, last_active_at}]}`. |
| PATCH  | `/api/sessions/{id}`        | `{url?, ui?, label?, workspace?, table?}` | Update a session. `ui` merges per view namespace; the rest replace. An empty `label` unpins; a `Session <n>` one is refused with `400`. `table` is the Explorer's selection, kept as the open connection's last visited table (empty = none). `{ok}`; unknown id → `404`. |
| DELETE | `/api/sessions/{id}`        | —                                      | Delete a session. `{ok}`; held by a live tab → `409`, unknown → `404`. |
| POST   | `/api/sessions/release`     | `{tab}`                                | Free whatever this tab holds — the `pagehide` beacon. `{ok}`. |
| GET    | `/api/remote/events`        | `?session=<id>`                        | SSE stream a browser opens when "remote control" is armed; the channel is keyed by that session id (`EventSource` cannot send the header). Emits a `ready` event (`{id}`) then `script`, `dashboard` and `explorer` events with pushed payloads (each emitted under the SSE event named by the payload's `type`). |
| POST   | `/api/remote/lock`          | `{session_id, action:"acquire"\|"release"}` | The browser's [edit lock](../user_guide/query.md#co-edit--edit-lock) on a live session: acquired on editor focus with a ~10s heartbeat, released on blur. `{ok, message}`; bad action → `400`. |
| POST   | `/api/runqueries`           | `{queries:{name:SQL or {connection, sql, database?}}, params?, values?}` | Run a dashboard's named queries on this session's connection and selected database. Fail-fast: `{ok, results:{name:{col:[…]}}, meta:{name:[{name, type}]}}` (column-oriented, values typed as the driver returns them) on full success; on any failure an HTTP error with `{ok:false, message, reason}` — `409` not connected / no database selected (not when nothing needs the database: no queries and no `options_sql`), `400` bad body / a failing query (message prefixed with the panel name). With `params` (the dashboard's declaration) the queries are templates: the server resolves each selector's options and value from `values`, substitutes, skips a query still waiting on a choice, runs one naming an `each` param once per option, and adds `params:[{name, kind, options, value}]` to the reply (also to a failing query's); `queries` may then be empty, and a bad value is a `400` (values are matched as the page's text: [why](./mcp.md#why-a-param-value-is-matched-as-the-pages-text)). Each malformed declaration is left out and named in `warning`. A federated body runs each query on its own connection, without the session gate, and its reply, failed or not, adds `connections:[{name, database, status, queries, message?}]`; a mixed one → `400`. See [dashboards.md](../designs/dashboards.md#running-the-queries-apirunqueries) and [dashboard.md](../user_guide/dashboard.md#dashboard-parameters). |
| POST   | `/api/dashboards`           | `{name, html, queries, params?, session_id?, workspace?}` | Upsert a dashboard by name within a workspace; with `session_id`, also pushes it to that live session. In a workspace with a git remote, also one commit (see [gitsync.md](../user_guide/gitsync.md#committing)); a failed push → `502`, nothing saved. `{ok, persisted, pushed, committed, message}`. Missing `name`/`html` or malformed `params` → `400`. A new name [its folder can't hold](../user_guide/gitsync.md#repository-layout): too long → `400`, a case twin → `409`. |
| GET    | `/api/dashboards`           | `?workspace=`                          | List a workspace's dashboards (no payload): `{dashboards:[{name, updated_at, commit_sha}]}`, ordered by name. |
| GET    | `/api/dashboards/{name}`    | `?workspace=`                          | A saved dashboard `{name, html, queries, params, commit_sha}` (`queries` parsed to a dict; `commit_sha` is the git commit holding this content, `null` when unsynced or edited since), or `404 {error:"not found"}`. |
| POST   | `/api/dashboards/{name}/rename` | `{new_name, workspace?}`           | Rename a dashboard, committing when synced. `{ok, committed, sha, imported, conflicts}`; blank or too long `new_name` → `400`, unknown → `404`, taken or a case twin → `409`. |
| DELETE | `/api/dashboards/{name}`    | `?workspace=`                          | Delete a dashboard, committing when synced. `{ok, committed, sha, imported, conflicts}`; unknown → `404`. |

**Connecting:** `test`/`connect` resolve the driver from `type` and validate per driver
(ClickHouse/Postgres/MySQL require `host` + `port` `1..65535`, `database` optional;
DuckDB takes an optional `path`, SQLite a required file path); validation errors
return `400`. ClickHouse queries run over the HTTP interface with HTTP Basic auth,
within the session's [query timeout](../user_guide/queryview.md#query-timeout).

**MCP:** an MCP server is mounted at `/mcp/` (Streamable HTTP) exposing
`push_script` (push a script to a session's Scripts editor), `push_dashboard`
(push a dashboard draft to a session), `run_dashboard` (run a draft's queries for the agent), `session_info`,
`run_sql`, `run_script`, `list_dashboards`
and `git_history` / `git_restore`. They delegate to the in-process
hubs the matching REST endpoints call. See [mcp.md](../user_guide/mcp.md) and
[dashboard.md](../user_guide/dashboard.md).

<!-- req: mcp-mount -->
A slashless `/mcp` redirects to `/mcp/` for every MCP method (`POST`, `GET`,
`DELETE`), and `/mcp/` itself is not redirected.

## Persistence

Connections are stored in SQLite via SQLModel. See
[storage.md](./storage.md#persistence-sqlite) for the schema, and [session.md](../user_guide/session.md) for the session model.

## Workspaces

<!-- req: workspaces -->
Dashboards belong to a workspace; each workspace syncs
to its own git remote. The remote URL may embed a token — it is encrypted at
rest and never returned by the API. See [workspace.md](../user_guide/workspace.md).
Scoped endpoints (dashboards, export/import, `/api/git/*`) accept an optional
`workspace` name, defaulting to the fallback workspace.

| Method | Path                      | Body                          | Description |
| ------ | ------------------------- | ----------------------------- | ----------- |
| GET    | `/api/workspaces`         | —                             | List workspaces: `{workspaces:[{name, branch, configured, remote}]}`; `remote` has any embedded credential stripped. |
| POST   | `/api/workspaces`         | `{name, remote?, branch?}` | Create a workspace. `{ok}`, plus the merge-in result (`sync` or `sync_error`) when a remote is given; empty/`/`-containing name → `400`, duplicate → `409`. |
| PATCH  | `/api/workspaces/{name}`  | `{name?, remote?, branch?}` | Rename/reconfigure. A null `remote` clears it; an absent key leaves it unchanged. Entering a remote merges the repo in: `{ok, sync: {imported, conflicts}}`, or `{ok, sync_error}` if the repo is unreachable (the settings are saved either way). |
| DELETE | `/api/workspaces/{name}`  | —                             | Delete an empty workspace; its sessions move to the fallback workspace. `{ok, workspace}` (where they moved); unknown → `404`, still owns entities or is the last one → `409`. |

## YAML export / import

<!-- req: export-import -->
Dashboards can be downloaded as self-describing YAML
documents and imported back — one at a time or a whole workspace at once. See
[export-import.md](../user_guide/export-import.md) for the document shapes.

| Method | Path          | Body / params                              | Description |
| ------ | ------------- | ------------------------------------------ | ----------- |
| GET    | `/api/export` | `?kind=&name=&workspace=`                  | Download one dashboard (`kind=dashboard`, `name`) or the whole workspace (`kind=workspace`) as YAML, with a `Content-Disposition` filename (`{name}.dashboard.yaml` / `{workspace}.workspace.yaml`). `400` bad args, `404` unknown entity/workspace. |
| POST   | `/api/import` | raw YAML body, `?workspace=`               | Import a document into a workspace, upserting by name; the document's `kind` decides what is written. `{ok, kind, dashboards}`, `dashboards` being the count upserted. `400` malformed document, missing arguments, one carrying saved queries, a dashboard mixing named and unnamed queries, or a new name that is too long; `404` unknown workspace; `409` a new name that is a case twin of a saved dashboard or of an earlier entry. |

## Git sync

<!-- req: git-sync -->
Dashboards can be backed up to (and restored from) each
workspace's git repository, per entity. Connections are never written to the
repo. See [gitsync.md](../user_guide/gitsync.md) for configuration, repository layout, and
the UI.

| Method | Path              | Body                                            | Description |
| ------ | ----------------- | ------------------------------------------------ | ----------- |
| GET    | `/api/git/status`  | `?workspace=`                                    | Whether the workspace has a git remote configured, and the conflicts the last sync recorded. `{configured, conflicts: [{kind, name}]}`. |
| POST   | `/api/git/sync`    | `{workspace?}`                                   | Merge the repo in (see [gitsync.md](../user_guide/gitsync.md#merge-in)). `{ok, imported, conflicts}`; no remote → `409`. |
| GET    | `/api/git/history` | `?kind=&name=&before=&limit=10&workspace=` | The entity's revisions, newest first. `{ok, revisions: [{sha, date, message}], has_more}`. |
| POST   | `/api/git/restore` | `{kind, name, ref?, workspace?}`                | Overwrite the local DB row with the entity's content at `ref`: a sha from history or a branch name (read as `origin/<name>`), by default the remote branch head. `{ok, restored, sha, imported, conflicts}`. Bringing back a name [its folder can't hold](../user_guide/gitsync.md#repository-layout) → `400` / `409`, as on Save. |

`kind` is `"dashboard"`;
`workspace` defaults to the fallback workspace (see [workspace.md](../user_guide/workspace.md)). MCP tools `git_history` and
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](../user_guide/workspace.md)).

## Related docs

- [queryview.md](../user_guide/queryview.md) — the Connect page and the app's pages.
- [connect.md](../user_guide/connect.md) — connecting (new and saved connection cards), storage, sessions.
- [query.md](../user_guide/query.md) — querying: pagination, the results grid, CSV.
- [mcp.md](../user_guide/mcp.md) — driving a live session over MCP.
- [dashboard.md](../user_guide/dashboard.md) — the dashboard page, `upsert_dashboard`, and the `window.queries` contract.
- [gitsync.md](../user_guide/gitsync.md) — backing up and restoring dashboards via git.
- [export-import.md](../user_guide/export-import.md) — YAML export/import of dashboards and workspaces.
- [workspace.md](../user_guide/workspace.md) — workspaces: entity ownership and per-workspace remotes.
- [viewer_server_api.md](./viewer_server_api.md) — the viewer server's own API.
