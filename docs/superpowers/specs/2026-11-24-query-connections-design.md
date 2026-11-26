# Federated dashboards

## Intent

A [dashboard](../../system/dashboard.md) runs every query on the viewing session's
connection, so one page cannot show data from two databases. A **federated**
dashboard names a connection on every query instead, and the page's own
JavaScript combines the results. Wanted: panels from, say, a ClickHouse and a
Postgres side by side on one page.

## Goals

- **A dashboard is one of two kinds.** *(Decided.)*
  - **Unfederated:** every query is SQL, as today. It runs on the session's
    connection and selected database, and the top-left pill shows them.
  - **Federated:** every query is a map naming its connection. The session's
    connection plays no part, and the top-left pill shows the dashboard's
    connections and their status instead.

  ```yaml
  sales:
    connection: analytics
    sql: SELECT day, revenue FROM sales
  orders:
    connection: warehouse
    sql: SELECT day, count(*) AS orders FROM orders
    database: reporting                        # optional
  ```

  A dashboard mixing the two is malformed.
- **Backward compatible.** *(Decided.)* Every existing dashboard is
  unfederated and behaves exactly as today. No stored dashboard, git
  repository or export is migrated.
- The same shape works everywhere a dashboard's queries travel: the store,
  `queries.yaml`, export and import, `push_dashboard` and `run_dashboard`, the SQL panel, the
  app's run and widget requests, and the viewer server.
- A federated dashboard's params name a connection on every `options_sql`
  the same way.

## Non-goals

- No query that reads two connections (a cross-connection join). *(Decided:
  same page is enough; JavaScript combines.)*
- No alias layer mapping a dashboard's connection names to a viewer's.
- No change to what the dashboard's HTML sees: `window.queries`,
  `window.params`, the widgets and bound values keep their meaning. The HTML
  never learns which connection a query ran on.
- Renaming or deleting a connection does not rewrite the dashboards naming it.

## Anti-goals

- A dashboard reaching a locked connection without the tab's unlock token.
- An existing dashboard behaving differently.
- A federated dashboard showing the session's connection or database as if
  it ran there.
- The viewer server accepting SQL or a connection config from the browser.

## Approaches

1. **The backend picks the connection per query.** *(Decided.)* The browser
   posts the dashboard's queries in one run call, as today; the runner looks
   up each query's connection and runs it there. One request, so the
   concurrency limit, the error handling and the loading state stay single,
   and the viewer server reuses the runner with its own connection list.
2. The browser groups queries by connection and posts one run per group.
   Smaller backend change, but a failed group leaves partial panels, resolved
   params must be carried between calls, and both frontends need the grouping.
3. Queries name a role and `meta.yaml` maps roles to connections. Portable
   between instances with different connection names, at the cost of a second
   naming layer. It can be added on top of 1.

## Design

### The entry and the two kinds

A query entry is a non-empty SQL string, or a map with exactly:

| Key | | |
|---|---|---|
| `sql` | required | Non-empty string. |
| `connection` | required | A connection name, non-empty string. |
| `database` | optional | Non-empty string. |

Any other shape or key is malformed. A param with `options_sql` may carry
`connection` and `database` the same way; either key without `options_sql`
is malformed.

A dashboard is **federated** when its queries are maps, **unfederated** when
they are strings. Every query, a widget's included, and every `options_sql`
must agree: all name a connection, or none does. Otherwise it is refused with
`every query and options_sql names a connection, or none does`. A dashboard
with no query and no `options_sql` is unfederated.

One validator, one kind check and one pair of accessors (an entry's SQL; its
connection and database) are shared by every reader.

- Strings are handled by each reader exactly as today, blank ones included:
  Save and a run request drop them, import and git sync accept them.
- A malformed map is refused, with the query's name, by both agent tools,
  import and git sync. Save and a run request drop it, as `clean_queries`
  drops any malformed entry today.
- A mixed dashboard is refused by every reader: Save, both agent tools,
  import, git sync (that one dashboard, as a malformed folder is), a run
  request (`400`), and the viewer server's repo load.
- Whether a connection exists is decided when the query runs, so a dashboard
  syncs to an instance that lacks it.

### Which connection, which database

In the app, for a federated query or param, on session `sid`:

1. The name resolves as `connect._resolve` does: this session's session
   connections first, then the saved ones. None: `unknown`, and the query
   fails with `orders: unknown connection "warehouse"`.
2. A locked saved connection needs this tab's unlock token
   (`_is_unlocked(sid, name)`; one token per tab covers every connection it
   unlocked). Without it: `locked`, and the query fails with
   `orders: connection "warehouse" is locked`.
3. The database is the entry's `database`; else, when the name is the
   session's active connection, the session's selected database; else the
   saved connection's stored database. A driver that requires one and has
   none fails with `orders: no database selected on "warehouse"`.

A federated dashboard never goes through the session gate: it runs in a
disconnected session, and one on a locked connection. An unfederated one goes
through it exactly as today.

On the viewer server, a federated dashboard's names are looked up in the
config file's `connections`, each on its configured `database` unless the
entry gives one; the request names no connection. An unknown name fails the
same way. Every dashboard in the repo may name every configured connection:
the config file is the boundary. An unfederated one runs on the viewer's pick,
as today.

### Running

- The runner takes a lookup from an entry to its target (driver, config,
  database) in place of one target for the call. The lookup is the only part
  the app, the agent tools and the viewer server supply differently.
- Each connection is looked up once per run, before any query runs.
- `DASHBOARD_CONCURRENCY` stays per run, across connections.
- Failure handling is whatever the run path has when this lands (fail-fast
  today). A connection that cannot be resolved is a failing query, with the
  messages above.
- An `each` query fans out on its own connection.
- Placeholders are quoted in the dialect of the connection the SQL runs on:
  a query's in its query's, an `options_sql`'s in its param's. One param
  value may be quoted two ways in one run. A failing lookup for a param's
  connection is a params error (`reason: params`).
- A federated run's reply, failed or not, carries `connections`: one entry
  per connection the dashboard names, in first-use order:

  ```
  connections: [{name, database, status, queries, message?}]
  ```

  `status` is `ok` (looked up, and none of its queries failed), `failed` (one
  of its queries failed, or it has no database; `message` says why), `locked`
  or `unknown`. `queries` names the dashboard's queries on it. Over MCP a
  locked connection reports `unknown`.

### The connection pill on a federated dashboard

While `/dashboard` shows a federated dashboard, the top-left pill shows the
dashboard's connections instead of the session's; leaving the page, or
opening an unfederated dashboard, shows the session's again. The session's
connection is not changed.

```
Unfederated:  [🟢 analytics · sales_reporting ▾] [Timeout 30s]

Federated:    [⛓ Federated · 2 connections ▾]   [Timeout 30s]
              +--------------------------------------------------+
              | 🟢 analytics  · sales_reporting        2 queries |
              | 🔒 warehouse  · reporting   [Unlock]   1 query   |
              +--------------------------------------------------+
```

- The pill reads **Federated** with a ⛓ icon and the connection count, in
  any session state, a disconnected one included.
- Its list has one row per connection: the status icon, the name, the
  database, the query count, and per status:
  - 🟢 `ok`;
  - 🔴 `failed`, with the message under the row;
  - 🔒 `locked`, with **Unlock**, which opens the existing passphrase prompt
    (`POST /api/db/unlock`) and re-runs the dashboard on success;
  - ⚪ `unknown`: "Not a connection here".
- Before the first reply the rows show the names only. The **Timeout** chip
  and the agent icon stay.

On the viewer server's page a federated dashboard hides the connection
picker and shows the same list, without **Unlock** (the viewer server has no
locks). `GET /api/dashboards/{name}` adds `connections: [names]` for a
federated dashboard, names only.

### Widgets

A `<qv-select-view>` over a federated query pages on its connection. The
widget still sends a name and a page, never SQL or a connection. The request
the app builds for it carries `connection` and `database` beside the SQL, and
the same lookup applies; the describe request likewise. Explorer and Scripts
calls to the same endpoints are unchanged.

### The agent: `push_dashboard` and `run_dashboard`

Both take `queries` in either shape and refuse a mixed dashboard.
`run_dashboard` returns rows to the agent, and a pushed page's own script can
send its `window.queries` anywhere it can fetch, so a federated dashboard is a
read path for the agent either way. Both hold its connections to what the
agent can already reach with `use_connection`, and to the
[locked-connection rule](../../architecture/mcp.md#how-it-works) that the
agent learns nothing about a locked one:

- A name `list_connections` does not show the agent (it does not exist, or it
  is locked) fails as `unknown connection "warehouse"`: `run_dashboard` fails
  that query; `push_dashboard` refuses the push.
- A DuckDB or SQLite connection the agent did not add is refused with
  `use_connection`'s message, by both.
- Neither needs the session to be on a connection for a federated dashboard.

A federated dashboard naming a connection this instance lacks cannot be
pushed by the agent; the user's **Save** and import still take it. This keeps
a cooperating agent in its lane and is not a security boundary, as
[connect.md](../../system/connect.md#session-connections) says of the rest.

### The SQL panel

```
+- SQL panel ------------------------------------------------------+
| [ orders v ]  on [ warehouse v ]  [x] Federated  [Min][S][M][L]  |
| SELECT day, count(*) AS orders FROM orders                       |
| [Execute]                                                        |
+------------------------------------------------------------------+
```

- A **Federated** checkbox sets the dashboard's kind. Turning it on gives
  every query and `options_sql` the session's active connection, or the
  first in `GET /api/db/connections` when there is none; turning it off
  makes every query a string again and drops the params' `connection` and
  `database`. The panel cannot build a mixed dashboard.
- While federated, a drop-down beside the query's picks its connection from
  `GET /api/db/connections`. A name the instance lacks stays listed and
  selected, so opening the panel never rewrites an entry.
- Editing the text changes the entry's `sql` only. `database` and the params'
  connections are kept as written and have no control.
- **Execute** after a kind change re-runs everything.

### Storage and files

- `dashboards.queries` is JSON text already; no migration.
- `queries.yaml` and the export document hold the entry as written. A string
  entry is dumped as a string, so an untouched repo produces no diff.

### Docs and tests, by layer

Each statement below is written, with its `<!-- req: … -->` ID, before its
failing test (the project `vmodel` skill).

| Layer | Statement (page, ID) | Proved in |
|---|---|---|
| User | `requirements/queryview.md`, new `dashboard-many-connections`: a user can open one dashboard showing data from several connections, and sees which connections it uses and whether each answered. | `e2e/acceptance.spec.ts`: a federated dashboard over ClickHouse and Postgres renders both, and its pill lists both as 🟢. |
| System | `system/dashboard.md`: `viewing-connection` rewritten (an unfederated dashboard runs on the viewing session; the slug stays, its test names it); new `federated` (the two kinds, the map entry, `database`, the three messages, mixed refused, no session needed); new `sql-panel-connection` (the checkbox and drop-down). `system/queryview.md`: `connection-status` gains the federated pill; new `federated-pill` (rows, statuses, **Unlock**). `system/viewer_server.md`: new `federated`. Params, widgets and `queries.yaml` sections gain the entry. | `e2e/dashboard.spec.ts`, `e2e/server.spec.ts` |
| Integration | `architecture/dashboards.md`: `runqueries` extended (the `connections` reply), new `named-connection` (lookup, database rule, lock, per-connection quoting). `architecture/mcp.md`: `push-dashboard`, `run-dashboard`, `locked-refuses-both`. `architecture/viewer_server_api.md`: new `named-connection`. `architecture/api.md`: `/api/runqueries`' reply, `/api/db/query` and `/api/db/describe`'s `connection` and `database`. | backend `test_*.py` beside each route and tool |
| Unit | Docstrings of the entry module, `dashboard_params.py`, `dashboard_queries.py`; the leading comment of the frontend entry module. | the test file beside each |

Pages edited without a new ID: `system/gitsync.md`, `system/export-import.md`
(the file shapes and the mixed refusal), `system/connect.md` (a locked
connection a federated dashboard names).

Behaviors each layer's tests must cover:

- Kinds: all strings and all maps pass; a mixed one, counting widget queries
  and `options_sql`, is refused by Save, push, run, import, git sync and the
  viewer server's repo.
- Runner: two fake drivers, each query reaches its own; unknown, locked and
  database-less connections fail with the messages above and the matching
  `connections` status; a value is quoted per connection dialect.
- Locked: a federated query on a locked connection runs only with the token;
  **Unlock** in the pill re-runs it; both agent tools see it as unknown.
- Agent: `run_dashboard` and `push_dashboard` refuse a file connection the
  agent did not add.
- Viewer server: a federated dashboard runs on the configured connections it
  names and hides the picker; an unknown name fails.
- An unfederated dashboard: every existing test passes unchanged.

This spec and its plan are deleted when the work ships.

## Calls made while writing this up

These were not discussed; each is open to correction.

- The optional `database` key, and the three-step database rule.
- Existence of a connection is checked at run time, not on save.
- Both agent tools are held to `use_connection`'s rules, and a locked
  connection reads as unknown to them.
- Strings keep each reader's leniency; maps are checked strictly; a mixed
  dashboard is refused everywhere.
- The SQL panel's **Federated** checkbox picks the session's connection (or
  the first saved one) for every query when turned on.
- The pill keeps the **Timeout** chip and the agent icon beside it.
- On the viewer server any dashboard may name any configured connection.
- Concurrency stays five per run.
- A deleted or renamed connection leaves its dashboards failing with
  `unknown connection`.

## Order against one run for a dashboard page

[That pending design](./2026-11-24-one-run-per-page-design.md) replaces
`/api/runqueries` and the widget requests with one `/api/run`. None of it is
built, so this lands first, on today's endpoints. *(My call, not discussed.)*
The entry, its accessors, the lookup and the per-param dialect are shared by
both run paths; only the few lines that read entries from a request are
rewritten later. The one-run plan must carry map entries and the
`connections` reply through its shared run, as it already must for `each`.

## Left to the builder

- Names and placement of the validator, the accessors and the lookup.
- How `resolve` takes a dialect and a runner per param.
- How the dashboard page hands the pill its connections (context, a store,
  or props through the shell).
- How a DuckDB folder connection's root reaches a named entry.
- The request field that carries entries on whichever run path is current.
