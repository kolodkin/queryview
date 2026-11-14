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

- a **dropdown** of saved dashboards — selecting one sets `?name=<name>`, so the
  URL is shareable and the back button works;
- **New query** — an unsaved draft holding one [`<qv-select-view>`](#widgets)
  over one query, for ad-hoc SQL; **Save** asks for its name. The
  [session](./session.md) remembers the draft's SQL, so it survives leaving
  the page and a reload; picking a dashboard discards it;
- **Edit queries** — the [SQL panel](#the-sql-panel);
- a **sandboxed iframe** that renders the selected dashboard.

```
+-- /dashboard ------------------------------------------+
| [ dashboard v ] [New query] [Save] [Edit queries] ...  |
| +- SQL panel (Edit queries) -------------------------+ |
| | [ sales v ]                    [Min][S][M][L][XL]  | |
| | SELECT ...                                         | |
| | [Execute]                                          | |
| +----------------------------------------------------+ |
| +- sandboxed frame (the dashboard HTML) -------------+ |
| | <qv-param>   chart   <qv-select-view query=sales>  | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

Open it from the corner nav, or by URL: `?name=<name>` jumps straight to one.
Reopening re-fetches the dashboard and re-runs its queries, so a reloaded or
shared link always shows live data.

## The SQL panel

**Edit queries** opens an editor for the dashboard's queries, outside the
frame: pick a query, edit its SQL, and **Execute** re-runs the queries you
edited, and the widgets over them (everything, when nothing was edited). The frame is not reloaded, so the page keeps its state; a failing
query shows its error above it. Until **Execute**, the page and its widgets
run the SQL as last executed. **Save** persists the edited dashboard.

Focus in the panel holds the human [edit lock](./query.md#co-edit--edit-lock):
an agent push is refused with `blocked, user editing` while you type.

## The `push_dashboard` MCP tool

The MCP server at `/mcp` (see [mcp.md](./mcp.md) for arming and the
session id) exposes:

- `push_dashboard(session_id, html, queries, params?, name?)` — push the
  dashboard **draft** to the browser identified by `session_id`, which navigates
  to the dashboard view and renders it. Without `name` the draft is new:
  **Save** asks the user for its name. `name` must be a saved dashboard, which
  the push edits; the agent cannot name a new one. Only the user's **Save**
  writes it to the store. Returns
  `{ok, pushed, message, database}`; an unknown/disarmed
  `session_id` reports `pushed:false`, a disconnected one `not connected`.

A dashboard never names a [connection](./connect.md): it runs on the
**viewing** session's connection and selected database. So
a dashboard is portable across sessions, instances and git sync; opened in a
disconnected session it asks you to connect. Select a database first, or
fully-qualify tables as `db.table`.

The REST mirror `POST /api/dashboards` takes the same fields (plus optional
`session_id`) and drives the same persist-and-push path (used by the e2e suite).
See [api.md](./api.md) for the full endpoint list.

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

## Widgets

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

- **`<qv-select-view query>`** — a results table over the dashboard query it
  names: **Fields** (the select-fields and order-by pickers), **Limit**,
  **Offset**, **Previous** / **Next** and **Download CSV**, with the
  [default views](./query.md#default-views-for-complex-types) and
  [long-value popup](./query.md#long-values) of every results grid. `limit`
  (1–1000, default 100), `order-by` (`col` or `col desc`, comma-separated) and
  `fields` (the columns shown at first) set how it opens; changes made in the
  widget last for the visit.
- **`<template column>`** — designs one column's cells. Its HTML is used per
  row with `{cell}` (this column's value) and `{row.<column>}` (another
  column's) substituted: HTML-escaped, and URL-encoded inside `href` / `src`.
  An unknown `{row.<column>}` is left as written. Use placeholders in text and
  in `href` / `src` only: other attributes (`style`, `on…`) get no URL encoding.
  A column holding a whole URL can't fill an `href` by itself, since its `://`
  is encoded too; build the link around an id instead.
- **`<qv-param name>`** — the selector for one
  [dashboard parameter](#dashboard-parameters): a dropdown, or a checkbox for a
  `dimension`. A change re-runs the dashboard.

A query a `<qv-select-view>` names belongs to that widget: it runs per page
through `/api/db/query`, is **not** in `window.queries`, and a failure shows in
the widget, leaving the rest of the dashboard up. A name the dashboard doesn't
declare shows `Unknown query “…”`.

The widget sends the app a query name, limit, offset and order-by columns —
**never SQL**. The app looks the name up in the dashboard's `queries`,
substitutes the current parameters and runs it.

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

with a query referencing the placeholders:

```sql
SELECT {field} AS value, {category} AS category, count() AS cnt
FROM {table} GROUP BY value, category
```

| kind | substitutes as | example |
| --- | --- | --- |
| `value` (default) | quoted string literal, single quotes doubled | `{region}` → `'eu'` |
| `identifier` | a quoted table/column, in the connection's own quoting | `{field}` → `"city"` (`` `city` `` on ClickHouse) |
| `dimension` | a checkbox: its own column when checked, `''` when not | `{category}` → `"category"` / `''` |

A placeholder can override its param's kind in one spot: **`{table:literal}`**
gives a string where the SQL wants one while `FROM {table}` still gets the
identifier. The casts are `literal` and `identifier`; anything else is an error.
An identifier containing the quote character is rejected.

`options` and `options_sql`
are mutually exclusive (a `dimension` needs neither), and the first option is
chosen for you unless the param says **`default: none`** — then the selector
starts empty and every query that needs it is held back until a choice is made.
`options_sql` runs on the viewing session's connection and database, and may
reference another param (`{table}`), so a field list can follow the selected
table; params resolve in dependency order, a cycle is an error, and one whose
dependency is still unchosen simply has no options yet.

## Changing parameters: `window.params` and `setParams`

The resolved selectors are injected next to the results:

```js
window.params = [{ name, kind, options: [...], value }, …]
```

The page draws its own controls from that list and asks for a re-run with
`window.setParams({ field: 'city', category: true })`. The host substitutes the
values into the dashboard's **own** queries, runs them on the session's
connection, and posts the results back; `window.onQueryResults(queries, params,
message)` then fires with the new `window.queries` and `window.params`
(`message` is set when the run failed and the previous results were kept). The
iframe isn't reloaded, so the page keeps its state.

The page sends **values only, never SQL**, and the host answers only messages
from the dashboard's own frame — so a dashboard's SQL stays what `queries`
declares, reviewable in `queries.yaml`.

## Running the queries: `/api/runqueries`

The browser POSTs `{queries}` to `/api/runqueries`, which runs each query on
the session's connection and selected database (wrapped in a paginated subselect
capped at 1000 rows) and returns column-oriented results. Switching the
connection or database re-runs them.

It is **fail-fast**: if any query fails, or the session is not connected or has
no database selected, the whole request returns an HTTP error and the page shows a
dashboard-level error banner instead of partial panels. On success every named
query is present in `window.queries`. A failing query's message is prefixed with
its panel name (e.g. `churn: Unknown table …`) so it's clear which one to fix.

## Isolation & security

The HTML renders in
`<iframe sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" srcdoc=…>`
**without** `allow-same-origin`, giving it an opaque origin: it can run JS and load CDN
assets but cannot read the app's storage or call `/api/*` as the session (it
has neither the session id nor any credential). A link the page opens with
`target="_blank"` lands in a normal tab. Data reaches it only through the
injected `window.queries` and the [widget](#widgets) replies; the
`window.queries` JSON has `<` escaped so result data containing `</script>` can't break out
of the prologue.

Persisted dashboards are shared via SQLite and keyed by name within their
[workspace](./workspace.md). The agent HTML
is untrusted and confined to the sandbox; it never sees connection secrets or
the session id.

## Related docs

- [queryview.md](./queryview.md) — the pages and the Connect page.
- [query.md](./query.md) — pagination, the results grid, CSV, the edit lock.
- [mcp.md](./mcp.md) — arming a session, the session id, the MCP server.
- [api.md](./api.md) — `/api/runqueries`, `/api/dashboards`, the `dashboard` SSE event.
- [connect.md](./connect.md) — connections and their stored database.
