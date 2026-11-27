# MCP tools and channels

The MCP tools and the channel they push through. Connecting an agent and arming a session are in [mcp.md](../user_guide/mcp.md).

## Tools

Every tool acts on a browser session: a [tab](../user_guide/mcp.md#tabs) of the agent's own, or one
you [armed](../user_guide/mcp.md#arming-a-session).

<!-- req: session-info -->
- `session_info(session_id)` — what the session is on: `{ok, connected,
  connection, type, database, databases, workspace, tables: [{name, …}]}`
  (`tables` lists the selected database's). The starting point for schema
  discovery. The agent may switch to any listed connection (below). On a
  [locked](../user_guide/connect.md#locked-connections) connection it returns
  only `{ok, connected, locked: true, workspace, tables: []}`.
  <!-- req: connections -->
- Connections ([access rule](../user_guide/connect.md#session-connections)):
  `list_connections(session_id)` tags each with `scope`, `created_by`,
  `active`, leaving out [locked](../user_guide/connect.md#locked-connections) ones;
  `list_databases(session_id, connection?)` lists the databases of each listed
  connection, or of `connection` only.
  `add_connection(session_id, name, type, config)` adds a ClickHouse,
  Postgres or MySQL session connection; `use_connection(session_id, name, database?)`
  works on any unlocked ClickHouse, Postgres or MySQL one (not DuckDB or SQLite: they
  read local files), `select_database(session_id, database)` on any unlocked
  active one; `remove_connection(session_id, name)` only on the agent's own.
  In the browser, an add/remove refreshes an armed tab's connection lists
  (pill menu, Connect). A `use_connection` marks the session row `connection_by: agent`;
  every tab picks it up on its next heartbeat, toasts "Agent switched to
  <name>", and the pill reads `<connection> · <database>` with the menu entry
  marked active and badged `agent`. Switches made in the UI never toast.
  <!-- req: run-sql -->
- `run_sql(session_id, sql, limit?=1000)` — run one read-only statement as
  written (so `DESCRIBE`/`SHOW`/`EXPLAIN` work; page with your own
  `LIMIT`/`OFFSET`) on the session's connection and database, returning
  `{ok, database, columns, types, rows, truncated}` to the agent. Values are
  typed as the driver returns them (64-bit integers and decimals as strings,
  collections as JSON); `truncated` means rows past `limit` were dropped. Fails
  with `not connected` on a disconnected session; stops after 60s, server-side
  too. ClickHouse errors name the `query_id` to look up in `system.query_log`.
  <!-- req: run-script -->
- `run_script(session_id, sql)` — run a script like the [Scripts](../user_guide/scripts.md)
  page's Run all, **writes included**, returning `{ok, database, results: [{sql,
  ok, status, message, columns, types, rows, truncated, elapsed_ms}]}` to the
  agent. Stops at the first failure; `columns`/`types`/`rows` are null for a
  statement without rows.
  <!-- req: push-script -->
- `push_script(session_id, sql, run?=false)` — replace the Scripts editor's
  text; the browser navigates there and, with `run`, runs it all (results stay
  in the browser). Returns
  `{ok, message, database}`; `ok:false` for an unknown id, a held lock
  (`"blocked, user editing"`), or a session whose Scripts page can't open yet
  (`"not connected"`, `"select a database first"`).
  <!-- req: open-explorer -->
- `open_explorer(session_id, database, table?)` —
  switch the session to `database` and send the browser to its
  [Explorer](../user_guide/explorer.md), on `table` when given (refused when the database
  doesn't list it). Returns `{ok, message, database}`; past the switch, a
  failure still leaves the session on `database`.
  <!-- req: push-dashboard -->
- `push_dashboard(session_id, html?, queries?, params?, name?, dir?)` — push a
  dashboard **draft**; the browser navigates to it and renders it. Without
  `name` the push is an unnamed draft; `name` selects a saved dashboard to
  [edit](../user_guide/mcp.md#naming-and-saving): it must be one `list_dashboards`
  returns, and any other is refused. `dir` reads the draft from
  [a folder](../user_guide/dashboard.md#pushing-from-a-folder) instead of `html` and
  `queries`. Returns
  `{ok, pushed, message, database}`; a disconnected session fails with
  `not connected` unless the draft is [federated](#federated-drafts). See
  [dashboard.md](../user_guide/dashboard.md).
  <!-- req: run-dashboard -->
- `run_dashboard(session_id, queries?, params?, values?, dir?, limit?=100)` — run
  a draft's queries with `values` substituted into their
  [placeholders](../user_guide/dashboard.md#dashboard-parameters), as the page would,
  returning `{ok, database, results, meta, params}` to the agent: `results` in
  the `window.queries` shape, at most `limit` rows a query (max 1000). A param
  without a value takes its default; a number or boolean value is read as its
  text (`2`, `true`); see [why](#why-a-param-value-is-matched-as-the-pages-text). Stops at the first failing query, whose
  name opens the `message`, and after 60s; nothing reaches the browser. A
  [federated](#federated-drafts) run needs a known session (else
  `unknown session`) but no session connection, adds `connections: [{name,
  database, status, queries, message?}]` and has a null `database`.
- `new_tab(name)` — a session of the agent's own; see [Tabs](../user_guide/mcp.md#tabs).
- `list_dashboards()` — list saved dashboards: `{dashboards: [{name, updated_at}]}`.
  <!-- req: git-tools -->
- `git_history` / `git_restore` — list and restore a saved dashboard's
  versions in [workspace git](../user_guide/gitsync.md); only the user's Save commits.

A pushed dashboard's queries run through the browser's own `/api/runqueries`
and `/api/db/query` calls; the push layer never talks to a database.

## Federated drafts

Both dashboard tools take a query as SQL or as a
[federated](../user_guide/dashboard.md#federated-dashboards)
`{connection, sql, database?}` map, and refuse a malformed entry or a mixed
dashboard before anything runs. A pushed page's script can send
`window.queries` anywhere, so either tool reads data, and a named connection
obeys `use_connection`'s rules: one `list_connections` does not show is
`unknown connection "warehouse"`, and a DuckDB or SQLite one the agent did not
add gets `use_connection`'s refusal. `run_dashboard` fails that query;
`push_dashboard` refuses the push, naming the first query or param that names
it (`orders: unknown connection "warehouse"`).

## How it works

When armed, the browser opens an SSE stream
(`GET /api/remote/events?session=<id>`); the backend registers an in-memory
channel **keyed by that session's id** (see [session.md](../user_guide/session.md)).
The push tools enqueue onto that channel; the SSE stream delivers the payload
and the page renders it.

Because the channel is named after a session, the agent's session-scoped tools
read that session's database and workspace straight from its row — the browser
reports nothing (see [workspace.md](../user_guide/workspace.md)).

<!-- req: tab-queue -->
A push to a [tab](../user_guide/mcp.md#tabs) nobody has opened yet lands in a channel `new_tab`
opened in advance, which answers `queued for the tab`; arming takes that
channel over with its pushes queued. One whose tab never comes is dropped
after a minute.

<!-- req: locked-refuses-both -->
**Locked connections keep the agent out.** While a session is on a saved
connection the user [locked](../user_guide/connect.md#locked-connections) behind a
passphrase, the tools that query it, push to its tab, pick its database or
switch to it refuse with `connection is locked`: `run_sql`, `run_script`,
an unfederated `run_dashboard`, `push_script`, `push_dashboard`,
`open_explorer`,
`select_database` and `use_connection`. `session_info` reports only that it is locked, with no name,
type, database or tables, and a refused tool names no database;
`list_connections` leaves it out, and a dashboard query naming it reads as
`unknown connection`, never `locked`. REST calls without the tab's unlock token are
refused too, so copying a session id into `/api/db/query` gets the agent
nowhere.

`list_dashboards`, `git_history`, `git_restore` and `new_tab` work on the
workspace or open a tab, never on a connection, so the lock does not reach
them.

<!-- req: remote-channel -->
**Arming is the gate, not the id.** Disarming closes the channel, and any later
push fails with `unknown or inactive session`.

The id is stable across refreshes
and re-arms, so the command you copy stops changing under you; equally, an id
you have shared stays usable whenever that session is armed.

State is in-memory and per-process (like the active-connection session map): a
backend restart drops channels; the browser reconnects while armed and gets a
new id.

## Why a param value is matched as the page's text

A request's param value (`run_dashboard` above, [api.md](./api.md),
[viewer_server_api.md](./viewer_server_api.md)) is compared with the options
as the text the page shows for them. A number or boolean becomes that text
(`2`, `true`), and a value no option offers takes the param's default without
an error:

- **One rule for every caller.** The page sends the option text it showed, so
  an agent or a script sending `2` selects the same option the page would.
- **No guessing across spellings.** `false` does not select an option declared
  as the string `"False"`: matching case-insensitively would make `"false"`
  and `"False"` one option where a dashboard declares both.
- **A stale value is not an error.** A selection saved before the options
  changed falls back to the default, so an unoffered value has to do the same.
- The cost: a mistyped value runs the default silently. The reply's `params`
  carries each param's `options` and chosen `value`, which is where a caller
  sees it.

## Related docs

- [mcp.md](../user_guide/mcp.md) — connecting an agent, arming a session, naming and saving.
- [session.md](../user_guide/session.md) — sessions and agent tabs.
- [api.md](./api.md) — backend JSON API.
- [dashboard.md](../user_guide/dashboard.md#dashboard-parameters) — dashboard parameters.
