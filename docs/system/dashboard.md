# Dashboards (agent-authored, pushed to a live session)

A **dashboard** is an HTML layout plus a set of named SQL queries. An AI agent
authors one and pushes it into a live, armed QueryView browser session over MCP;
it is also persisted so it can be reopened later by name.

Responsibilities mirror the [remote-control](./mcp.md) layer: the agent never
receives query results back. The **browser** (trusted code with a session) runs
the queries on its session's connection and feeds the results into the
agent-authored HTML, which renders inside an isolated iframe.

## The page (`/dashboard`)

`/dashboard` is a top-level page beside Connect (`/connect`), the
[explorer](./explorer.md) and [Scripts](./scripts.md); see
[queryview.md](./queryview.md). It has:

<!-- req: picker -->
- a **dropdown** of saved dashboards — selecting one sets `?name=<name>`, so the
  URL is shareable and the back button works; the button beside it copies the
  open dashboard's name;
- **Save** — writes the open dashboard to the store; reads **Saved**, disabled,
  while the open dashboard is the store's copy (no draft, agent push or
  SQL-panel edit);
  <!-- req: rename-delete -->
- **Rename** and **Delete** — for a saved dashboard; Rename asks for the new
  name and keeps unsaved SQL-panel edits, Delete asks to confirm. Both are
  the user's: no [MCP tool](./mcp.md#naming-and-saving) does either. A new
  name [its git-sync folder can't hold](./gitsync.md#repository-layout) is
  refused with the reason, on Save too;
- **Edit queries** — the [SQL panel](#the-sql-panel);
- **Snapshot** — downloads the dashboard as a [static file](#snapshot);
- a **sandboxed iframe** that renders the selected dashboard.

```
+-- /dashboard ------------------------------------------+
| [dashboard v] [Save] ... [Edit queries] ... [Snapshot] |
| +- sandboxed frame (the dashboard HTML) -------------+ |
| | <qv-param>   chart   <qv-select-view query=sales>  | |
| |   +- SQL panel (Edit queries popup) ----------+    | |
| |   | [ sales v ]      [Min][S][M][L][XL][Close]|    | |
| |   | SELECT ...                                |    | |
| |   | [Execute]                                 |    | |
| |   | results table over sales                  |    | |
| |   +-------------------------------------------+    | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

<!-- req: reopen-by-name -->
Open it from the corner nav, or by URL: `?name=<name>` jumps straight to one.
Reopening re-fetches the dashboard and re-runs its queries, so a reloaded or
shared link always shows live data.

<!-- req: new-query-draft -->
`/dashboard?new` opens a **New query** draft: an unsaved dashboard holding one
[`<qv-select-view>`](#widgets) over one query, for ad-hoc SQL, with the
[SQL panel](#the-sql-panel) open. [Scripts](./scripts.md)' **Open in
Dashboard** and `/studio` land there. **Save** asks for its name. The
[session](./session.md) remembers the draft's SQL across a reload; picking a
dashboard discards it.

## The SQL panel

**Edit queries** opens a popup over the page, outside the frame:

- a drop-down of the dashboard's queries (its `queries.yaml`);
- the picked query's SQL;
- on a federated dashboard, the query's connection;
- its rows, in a results table like a [`<qv-select-view>`](#widgets),
  whatever the dashboard's HTML does with that query.

<!-- req: execute -->
**Execute** re-runs the queries you edited (everything, when nothing was
edited): in the popup's table, on the page and in the widgets over them. A
page of rows the popup and a widget both show runs once. The frame is not
reloaded, so the page keeps its state; a failing page query shows its error
above the frame. Until **Execute**, everything runs the SQL as last executed.

<!-- req: sql-panel-connection -->
A **Federated** checkbox sets the dashboard's kind. Ticking it gives every
query and `options_sql` the session's active connection (else the first saved
one); unticking makes every query a string again and drops the params'
`connection` and `database`. While federated, a drop-down beside the query
picks its connection; a name the instance lacks stays listed and selected.
Editing the text changes only `sql`. **Execute** after a kind change re-runs
everything.

<!-- req: save-edits -->
**Close**, Escape or a press outside the popup keeps the edits; **Save**
persists the edited dashboard.

Focus in the panel holds the human [edit lock](./query.md#co-edit--edit-lock):
an agent push is refused with `blocked, user editing` while you type.

## The `push_dashboard` MCP tool

The MCP server at `/mcp` (see [mcp.md](./mcp.md) for arming and the
session id) exposes:

- `push_dashboard(session_id, html?, queries?, params?, name?, dir?)` — push the
  dashboard **draft** to the browser identified by `session_id`, which navigates
  to the dashboard view and renders it. Without `name` the draft is new:
  **Save** asks the user for its name. `name` must be a saved dashboard, which
  the push edits; the agent cannot name a new one. Only the user's **Save**
  writes it to the store. Returns
  `{ok, pushed, message, database}`; an unknown/disarmed
  `session_id` reports `pushed:false`, a disconnected one `not connected`.
- `run_dashboard` returns the rows of a draft's queries to the agent, to test
  them before a push: see [mcp.md](../architecture/mcp.md#tools).

<!-- req: viewing-connection -->
An unfederated dashboard (its queries are plain SQL strings) names no
[connection](./connect.md): it runs on the **viewing** session's connection and
selected database. So it is portable across sessions, instances and git sync;
opened in a disconnected session it asks you to connect, unless nothing in it
queries the database. Select a database first, or fully-qualify tables as
`db.table`.

<!-- req: federated -->
A **federated** dashboard names a connection per query, so one page shows
several databases. A query entry is a SQL string, or a map:

```yaml
orders:
  connection: warehouse    # required: a connection name
  database: sales_reporting  # optional
  sql: SELECT day, count(*) AS orders FROM orders GROUP BY day
```

- `connection` and `sql` are required, `database` is optional; any other key
  is malformed. A param with `options_sql` may carry `connection` and
  `database` the same way.
- The database is the entry's `database`; else the session's selected one when
  the name is its active connection; else the saved connection's own.
- A failing lookup fails that query with `orders: unknown connection
  "warehouse"`, `orders: connection "warehouse" is locked` (a locked
  connection runs only in a tab that unlocked it) or `orders: no database
  selected on "warehouse"`.
- Every query, widget queries and `options_sql` included, names a connection or
  none does; a mixed dashboard is refused with `every query and options_sql
  names a connection, or none does`.
- It needs no connected session. The page's [pill](./queryview.md)
  lists the connections.

The REST mirror `POST /api/dashboards` takes the inline fields (plus optional
`session_id`) and drives the same persist-and-push path (used by the e2e suite).
See [api.md](../architecture/api.md) for the full endpoint list.

## Pushing from a folder

An agent regenerates inline `html` and `queries` in full on every push. With
`dir`, it writes them once to a folder of its own (its scratchpad) and each
re-push is a short call; the server reads the folder, so both must share a
filesystem.

```
push_dashboard(session_id, dir="/tmp/agent-scratch/sales-overview")

sales-overview/
  dashboard.html
  queries.yaml     {query name: SQL, or {connection, database?, sql}}
  meta.yaml        optional: name, params
```

The layout is a dashboard's folder in [workspace git](./gitsync.md), except
for the name: git takes it from the folder, a draft from `meta.yaml` or the
inline `name`. `dir` is
an absolute path outside QueryView's data directory; only these three
names are read, and none through a symlink. Inline `name` and `params` win
over `meta.yaml`; `dir` together with `html` or `queries` is refused.

The symlink check runs just before the read, so it does not hold against a
process on the server's machine that swaps a file for a link in between.

## The `window.queries` contract for HTML authors

Before the dashboard HTML runs, the page injects the results as a `window.queries`
global — a **column-oriented** map:

```js
window.queries = {
  <query_name>: { <column_name>: [values, …] },
  …
}
```

So for a query named `sales` selecting a `revenue` column,
`window.queries.sales.revenue` is that column's values. Column order is preserved.
Values are typed as the driver returns them: numbers are numbers, 64-bit
integers and decimals are strings (so nothing rounds), and arrays, maps, and
tuples are JSON arrays and objects.
Load any chart library from a CDN inside the HTML. A minimal dashboard:

```html
<canvas id="c"></canvas>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  const { month, revenue } = window.queries.sales
  new Chart(document.getElementById('c'), {
    type: 'bar',
    data: { labels: month, datasets: [{ label: 'Revenue', data: revenue.map(Number) }] },
  })
</script>
```

## Bound values

<!-- req: bound-values -->
Any element with `data-qv-query` shows row 1 of that query's
`data-qv-column` (default: its first column) as text, and follows each
re-run, so a KPI needs no script:

```html
<span class="chip">Revenue <b data-qv-query="totals" data-qv-column="revenue"></b></span>
```

Styling is the page's own. `—` stands for no rows, a NULL, or a query with no
results in `window.queries`: one held back for an unchosen parameter, one
that failed, a misspelt name, or one a [`<qv-select-view>`](#widgets) owns. A
column the query lacks shows `Unknown column “…”`. An element a script adds
later is filled on the next re-run.

## Widgets

A `<qv-select-view>` over a federated query pages on that query's connection;
the widget still names only the query.

Dashboard HTML may use two tags anywhere in its own layout. They render in the
frame with the rest of the page; only dashboards that use one load them.

```html
<qv-param name="region"></qv-param>
<qv-select-view query="sales" limit="100" order-by="day desc" fields="day,revenue">
  <template column="revenue"><strong>{cell}</strong></template>
  <template column="name">
    <a href="https://example.internal/items/{row.id}" target="_blank">{cell}</a>
  </template>
</qv-select-view>
```

<!-- req: select-view -->
- **`<qv-select-view query>`** — a results table over the dashboard query it
  names: **Fields** (the select-fields and order-by pickers), **Limit**,
  **Offset**, **Previous** / **Next** and **Download CSV**, with the
  [default views](./query.md#default-views-for-complex-types) and
  [long-value popup](./query.md#long-values) of every results grid. `limit`
  (1–1000, default 100), `order-by` (`col` or `col desc`, comma-separated) and
  `fields` (the columns shown at first) set how it opens; changes made in the
  widget last for the visit.
  <!-- req: cell-template -->
- **`<template column>`** — designs one column's cells. Its HTML is used per
  row with `{cell}` (this column's value) and `{row.<column>}` (another
  column's) substituted: HTML-escaped, and URL-encoded inside `href` / `src`.
  An unknown `{row.<column>}` is left as written. Use placeholders in text and
  in `href` / `src` only: other attributes (`style`, `on…`) get no URL encoding.
  A column holding a whole URL can't fill an `href` by itself, since its `://`
  is encoded too; build the link around an id instead.
  <!-- req: qv-param -->
- **`<qv-param name>`** — the selector for one
  [dashboard parameter](#dashboard-parameters): a dropdown, or a checkbox for a
  `dimension`, a text box for a `text` (sent on Enter or on leaving it). A
  change re-runs the dashboard.

<!-- req: widget-owns-query -->
A query a `<qv-select-view>` names belongs to that widget: it runs per page
through `/api/db/query`, is **not** in `window.queries`, and a failure shows in
the widget, leaving the rest of the dashboard up. A name the dashboard doesn't
declare shows `Unknown query “…”`.

The widget sends the app a query name, limit, offset and order-by columns —
**never SQL**. The app looks the name up in the dashboard's `queries` and
posts it with the current parameter values; the backend substitutes them and
runs it.

## Dashboard parameters

A dashboard can declare **selectors** whose chosen values are substituted into
its queries, so an interactive dashboard re-queries per selection instead of
precomputing every result it might show. They live in a `params` list on the
dashboard (stored in `dashboards.params`, written to `meta.yaml` by
[git sync](./gitsync.md) and to [exports](./export-import.md)):

```yaml
params:
  - name: table
    kind: identifier
    default: none
    options_sql: SELECT name FROM system.tables WHERE database = currentDatabase()
  - name: field
    kind: identifier
    options_sql: SELECT name FROM system.columns WHERE table = {table:literal}
  - name: category
    kind: dimension
```

A param with `options_sql` on a federated dashboard may add `connection` and
`database`, as a query entry does.

with a query referencing the placeholders:

```sql
SELECT {field} AS value, {category} AS category, count() AS cnt
FROM {table} GROUP BY value, category
```

| kind | substitutes as | example |
| --- | --- | --- |
| `value` (default) | quoted string literal, single quotes doubled (and backslashes on ClickHouse) | `{region}` → `'eu'` |
| `identifier` | a quoted table/column, in the connection's own quoting | `{field}` → `"city"` (`` `city` `` on ClickHouse) |
| `dimension` | a checkbox: its own column when checked, `''` when not | `{category}` → `"category"` / `''` |
| `text` | whatever was typed, as a quoted string literal | `{note}` → `'o''k'` |
| `each` | every option in turn, as a `value` does: see [below](#a-query-run-once-per-value) | `{region}` → `'eu'`, then `'us'` |

A `text` param is free input:

- No options; up to 10,000 characters.
- Opens on its `default` string: empty without one, or with `default: none`.
- An empty one still substitutes, as `''`, so its queries run.
- A `setParams` that leaves it out keeps what was typed.
- Only ever a string: `{note:identifier}` is an error.
- An `options_sql` may reference it, so typed text can pick a scope computed
  in SQL.

A placeholder can override its param's kind in one spot: **`{table:literal}`**
gives a string where the SQL wants one while `FROM {table}` still gets the
identifier. The casts are `literal` and `identifier`; anything else is an error.
An identifier containing the quote character, or a backslash on ClickHouse, is
rejected. Write option values as they are stored (`CORP\alice`); never
pre-escape them.

<!-- req: malformed-param -->
Saving refuses a malformed declaration. One already in a stored dashboard
(saved before a rule existed) is left out when it opens, and the dashboard
page names each one above the dashboard.

`options` and `options_sql`
are mutually exclusive (a `dimension` needs neither), and the first option is
chosen for you unless the param says **`default: none`** — then the selector
starts empty and every query that needs it is held back until a choice is made.
`options_sql` runs on the viewing session's connection and database, and may
reference another param (`{table}`), so a field list can follow the selected
table; params resolve in dependency order, a cycle is an error, and one whose
dependency is still unchosen simply has no options yet.

## A query run once per value

<!-- req: each-param -->
An **`each`** param is a list nobody picks from. A query that names it runs
once per option, up to five at a time, and its result is the rows of every
run, stacked in the list's order. A heavy query over many partitions (a
database per tenant, a table per region) becomes several small ones:

```yaml
params:
  - name: region
    kind: each
    options_sql: SELECT DISTINCT region FROM orders ORDER BY region
```

```sql
SELECT {region} AS region, count() AS orders FROM orders WHERE region = {region}
```

- Needs `options` or `options_sql`, takes no `default`, and holds no value:
  `<qv-param>` draws nothing for it. At most 100 options; a repeated one runs
  once.
- Its `options_sql` may reference other params, never another `each`; no other
  param's `options_sql` may reference it. A query names at most one.
- The runs must return the same columns, in name and order.
- A failing run fails the query, named with its value: `sales[eu]: …`. So list
  only the values the query can run on.
- No options: an empty result with no columns.
- The 1,000-row cap applies to each run and to the stacked rows, which keep
  the first 1,000; values past a full cap are not run.
- While its list waits on another param's choice, the query waits too.
- A [widget](#widgets) cannot page such a query.

## Changing parameters: `window.params` and `setParams`

The resolved selectors are injected next to the results:

```js
window.params = [{ name, kind, options: [...], value }, …]
```

<!-- req: set-params -->
The page draws its own controls from that list and asks for a re-run with
`window.setParams({ field: 'city', category: true })`. The host posts the
values with the dashboard's **own** queries; the backend substitutes them and
runs the queries on the session's connection, and the host posts the results
back; `window.onQueryResults(queries, params,
message)` then fires with the new `window.queries` and `window.params`
(`message` is set when the run failed and the previous results were kept). The
iframe isn't reloaded, so the page keeps its state.

<!-- req: loading-mark -->
While that re-run is in flight the page's `<html>` carries
**`data-qv-loading`**, however it started (`setParams`, a `<qv-param>`,
**Execute**), until the last one queued has answered. A thin bar runs across
the top of the frame, and a dashboard can mark what is now stale with its own
CSS, e.g. `[data-qv-loading] .panel { opacity: .5 }`.

The page sends **values only, never SQL**, and the host answers only messages
from the dashboard's own frame — so a dashboard's SQL stays what `queries`
declares, reviewable in `queries.yaml`.

## Running the queries: `/api/runqueries`

The request the page sends to run a dashboard's queries is in [dashboards.md](../architecture/dashboards.md#running-the-queries-apirunqueries).

## Snapshot

<!-- req: snapshot -->
**Snapshot** downloads the open dashboard as one static `<name>.html`, as it
stands at the current parameters. Print the file for a PDF.

- Each widget shows every row it holds, without controls or a scroll box,
  under a caption of its row count, limit, offset and order. Raise its
  **Limit** first for more rows.
- A canvas chart becomes an image; a dropdown, its chosen value.
- Refused while the dashboard or a widget is still loading.
- The file runs no script and redirects nowhere, whatever the dashboard's
  HTML contains. Stylesheets, fonts and images from elsewhere are still
  fetched when it is opened; embedded frames are not.
- A WebGL chart or a canvas holding a cross-origin image comes out blank; a
  password field, empty.
- It holds rendered query results: treat the file as data.

## Isolation & security

The sandbox the dashboard HTML runs in is described in [dashboards.md](../architecture/dashboards.md#isolation--security).

## Related docs

- [queryview.md](./queryview.md) — the pages and the Connect page.
- [query.md](./query.md) — pagination, the results grid, CSV, the edit lock.
- [mcp.md](./mcp.md) — arming a session, the session id, the MCP server.
- [api.md](../architecture/api.md) — `/api/runqueries`, `/api/dashboards`, the `dashboard` SSE event.
- [connect.md](./connect.md) — connections and their stored database.
