# A connection per dashboard query

## Intent

A [dashboard](../../system/dashboard.md) runs every query on the viewing session's
connection, so one page cannot show data from two databases. A query that
names a connection runs there instead, and the page's own JavaScript combines
the results. Wanted: panels from, say, a ClickHouse and a Postgres side by
side on one page.

## Goals

- A query in `queries` is either SQL, as today, or a map naming its
  connection:

  ```yaml
  sales: SELECT day, revenue FROM sales        # the session's connection
  orders:
    connection: warehouse
    sql: SELECT day, count(*) AS orders FROM orders
    database: reporting                        # optional
  ```

- **Backward compatible.** *(Decided.)* A plain `name: SQL` entry runs on the
  session's connection and selected database exactly as today. No stored
  dashboard, git repository or export is migrated.
- The same shape works everywhere a dashboard's queries travel: the store,
  `queries.yaml`, export and import, `push_dashboard` and `run_dashboard`, the SQL panel, the
  app's run and widget requests, and the viewer server.
- A param's `options_sql` can name a connection the same way.

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
- The viewer server accepting SQL or a connection config from the browser.

## Approaches

1. **The backend picks the connection per query.** *(Decided.)* The browser
   posts the dashboard's queries in one run call, as today; the runner looks
   up each map entry's connection and runs it there. One request, so the
   concurrency limit, the error handling and the loading state stay single,
   and the viewer server reuses the runner with its own connection list.
2. The browser groups queries by connection and posts one run per group.
   Smaller backend change, but a failed group leaves partial panels, resolved
   params must be carried between calls, and both frontends need the grouping.
3. Queries name a role and `meta.yaml` maps roles to connections. Portable
   between instances with different connection names, at the cost of a second
   naming layer. It can be added on top of 1.

## Design

### The entry

A query entry is a non-empty SQL string, or a map with exactly:

| Key | | |
|---|---|---|
| `sql` | required | Non-empty string. |
| `connection` | required | A connection name, non-empty string. |
| `database` | optional | Non-empty string. |

Any other shape or key is malformed. One validator and one pair of accessors
(an entry's SQL; its connection and database, or none) are shared by every
reader, so no caller checks `isinstance(entry, str)` itself.

- String entries are handled by each reader exactly as today, blank ones
  included: Save and a run request drop them, import and git sync accept
  them.
- A malformed map is refused, with the query's name, by both agent tools,
  import and git sync. Save and a run request drop it, as `clean_queries`
  drops any malformed entry today.
- Validation checks the shape only. Whether the connection exists is decided
  when the query runs, so a dashboard syncs to an instance that lacks it.

### Which connection, which database

In the app, for a map entry, on session `sid`:

1. The name resolves as `connect._resolve` does: this session's session
   connections first, then the saved ones. None: the query fails with
   `orders: unknown connection "warehouse"`.
2. A locked saved connection needs this tab's unlock token for it
   (`_is_unlocked(sid, name)`); without one the query fails with
   `orders: connection "warehouse" is locked`. The token is per session and
   connection, so unlocking it once on Connect is enough.
3. The database is the entry's `database`; else, when the name is the
   session's active connection, the session's selected database; else the
   saved connection's stored database. A driver that requires one and has
   none fails with `orders: no database selected on "warehouse"`.

A string entry goes through the session gate unchanged. When the gate refuses
(not connected, locked, no database) and the run holds any string entry or
connection-less `options_sql`, the whole run fails as today, map entries
included: the page shows its connect prompt, not partial panels. A dashboard
with no
string entry and no connection-less `options_sql` needs no session
connection: it opens in a disconnected session, extending today's "nothing
touches the database" rule.

On the viewer server the request still names one connection, the viewer's
pick; string entries run on it. A map entry's name is looked up in the config
file's `connections` and runs on that connection's configured `database`
unless the entry gives one. An unknown name fails the same way. Every
dashboard in the repo may name every configured connection: the config file
is the boundary.

### Running

- The runner takes a lookup from an entry to its target (driver, config,
  database) in place of one target for the call. The lookup is the only part
  the app and the viewer server supply differently.
- Each connection is looked up once per run.
- `DASHBOARD_CONCURRENCY` stays per run, across connections.
- Failure handling is whatever the run path has when this lands (fail-fast
  today). A connection that cannot be resolved is a failing query, with the
  messages above, not a failed request.
- An `each` query fans out on its own connection.

### Params

- A param with `options_sql` may carry `connection` and `database`, with the
  same meaning and lookup as on a query. Either key without `options_sql` is
  a malformed declaration.
- Placeholders are quoted in the dialect of the connection the SQL runs on:
  a query's in its query's, an `options_sql`'s in its param's. One param
  value may be quoted two ways in one run.
- A failing lookup for a param's connection is a params error
  (`reason: params`), like a failing `options_sql`.

### Widgets

A `<qv-select-view>` over a map entry pages on that entry's connection. The
widget still sends a name and a page, never SQL or a connection. The request
the app builds for it carries the entry instead of bare SQL, and the same
lookup applies; the describe request likewise. Explorer and Scripts calls to
the same endpoints are unchanged.

### The agent: `push_dashboard` and `run_dashboard`

Both take `queries` in either shape. `run_dashboard` returns rows to the
agent, and a pushed page's own script can send its `window.queries` anywhere
it can fetch, so a named connection is a read path for the agent either way.
Both hold a named connection to what the agent can already reach with
`use_connection`, and to the
[locked-connection rule](../../architecture/mcp.md#how-it-works) that the
agent learns nothing about a locked one:

- A name `list_connections` does not show the agent (it does not exist, or it
  is locked) fails as `unknown connection "warehouse"`: `run_dashboard` fails
  that query; `push_dashboard` refuses the push.
- A DuckDB or SQLite connection the agent did not add is refused with
  `use_connection`'s message, by both.
- Neither needs the session to be on any connection when every query and
  `options_sql` names one.

A dashboard naming a connection this instance lacks cannot be pushed by the
agent; the user's **Save** and import still take it. This keeps a cooperating
agent in its lane and is not a security boundary, as
[connect.md](../../system/connect.md#session-connections) says of the rest.

### The SQL panel

```
+- SQL panel -------------------------------------------+
| [ orders v ]  on [ warehouse v ]   [Min][S][M][L][XL] |
| SELECT day, count(*) AS orders FROM orders            |
| [Execute]                                             |
+-------------------------------------------------------+
```

A second drop-down beside the query's holds **Session connection** (first,
the default) and the names from `GET /api/db/connections`. Picking a name
turns the entry into a map; picking **Session connection** turns it back into
a string. A name the instance lacks stays listed and selected, so opening the
panel never rewrites an entry. Editing the text changes the entry's `sql`
only. `database` is kept when present and has no control.

The viewer page has no panel and changes only through the server.

### Storage and files

- `dashboards.queries` is JSON text already; no migration.
- `queries.yaml` and the export document hold the entry as written. A string
  entry is dumped as a string, so an untouched repo produces no diff.

### Docs and tests, by layer

Each statement below is written, with its `<!-- req: … -->` ID, before its
failing test (the project `vmodel` skill).

| Layer | Statement (page, ID) | Proved in |
|---|---|---|
| User | `requirements/queryview.md`, new `dashboard-many-connections`: a user can open one dashboard showing data from several connections. | `e2e/acceptance.spec.ts`: a dashboard over ClickHouse and Postgres renders both. |
| System | `system/dashboard.md`: `viewing-connection` rewritten (a string entry runs on the viewing session; the slug stays, its test names it); new `query-connection` (the map entry, `database`, the three messages, locked, no-session rule); new `sql-panel-connection`. Params, widgets and `queries.yaml` sections gain the entry. | `e2e/dashboard.spec.ts` |
| Integration | `architecture/dashboards.md`: `runqueries` extended, new `named-connection` (lookup, database rule, lock, per-connection quoting). `architecture/mcp.md`: `push-dashboard`, `run-dashboard`, `locked-refuses-both`. `architecture/viewer_server_api.md`: new `named-connection`. `architecture/api.md`: `/api/db/query` and `/api/db/describe` take `connection` and `database`. | backend `test_*.py` beside each route and tool |
| Unit | Docstrings of the entry module, `dashboard_params.py`, `dashboard_queries.py`; the leading comment of the frontend entry module. | the test file beside each |

Pages edited without a new ID: `system/gitsync.md`, `system/export-import.md`
(the file shapes), `system/connect.md` (a locked connection a dashboard
names).

Behaviors each layer's tests must cover:

- Runner: two fake drivers, a string entry and a map entry each reach their
  own; unknown, locked and database-less connections fail with the messages
  above; a value is quoted per connection dialect.
- Validation: both shapes accepted, each malformed shape refused, through
  push, import and git sync.
- Locked: a map entry on a locked connection runs only with the token, and
  reads as unknown to both agent tools.
- Agent: `run_dashboard` and `push_dashboard` refuse a file connection the
  agent did not add.
- Viewer server: a map entry runs on the configured connection; an unknown
  one fails.
- A dashboard of string entries: every existing test passes unchanged.

This spec and its plan are deleted when the work ships.

## Calls made while writing this up

These were not discussed; each is open to correction.

- The optional `database` key, and the three-step database rule.
- A dashboard naming every connection opens without a session connection.
- Existence of a connection is checked at run time, not on save.
- Locked: the query fails with a message; no passphrase prompt is added to
  the dashboard page.
- Both agent tools are held to `use_connection`'s rules, and a locked
  connection reads as unknown to them.
- String entries keep each reader's leniency; only maps are checked strictly.
- A refused session gate fails a mixed run whole.
- Params get `connection` and `database`.
- The SQL panel gets a connection drop-down; `database` has no control.
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
rewritten later. The one-run plan must carry map entries through its shared
run, as it already must for `each`.

## Left to the builder

- Names and placement of the validator, the accessors and the lookup.
- How `resolve` takes a dialect and a runner per param.
- How a DuckDB folder connection's root reaches a named entry.
- The request field that carries entries on whichever run path is current.
