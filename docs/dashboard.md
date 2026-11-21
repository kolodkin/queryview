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
  URL is shareable and the back button works; the button beside it copies the
  open dashboard's name;
- **Save** — writes the open dashboard to the store; reads **Saved**, disabled,
  while the open dashboard is the store's copy (no draft, agent push or
  SQL-panel edit);
- **Rename** and **Delete** — for a saved dashboard; Rename asks for the new
  name and keeps unsaved SQL-panel edits, Delete asks to confirm;
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

Open it from the corner nav, or by URL: `?name=<name>` jumps straight to one.
Reopening re-fetches the dashboard and re-runs its queries, so a reloaded or
shared link always shows live data.

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
- its rows, in a results table like a [`<qv-select-view>`](#widgets),
  whatever the dashboard's HTML does with that query.

**Execute** re-runs the queries you edited (everything, when nothing was
edited): in the popup's table, on the page and in the widgets over them. A
page of rows the popup and a widget both show runs once. The frame is not
reloaded, so the page keeps its state; a failing page query shows its error
above the frame. Until **Execute**, everything runs the SQL as last executed.

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

A dashboard never names a [connection](./connect.md): it runs on the
**viewing** session's connection and selected database. So
a dashboard is portable across sessions, instances and git sync; opened in a
disconnected session it asks you to connect. Select a database first, or
fully-qualify tables as `db.table`.

The REST mirror `POST /api/dashboards` takes the inline fields (plus optional
`session_id`) and drives the same persist-and-push path (used by the e2e suite).
See [api.md](./api.md) for the full endpoint list.

## Pushing from a folder

An agent regenerates inline `html` and `queries` in full on every push. With
`dir`, it writes them once to a folder of its own (its scratchpad) and each
re-push is a short call; the server reads the folder, so both must share a
filesystem.

```
push_dashboard(session_id, dir="/tmp/agent-scratch/sales-overview")

sales-overview/
  dashboard.html
  queries.yaml     {query name: SQL}
  meta.yaml        optional: name, params
```

The layout is a dashboard's folder in [workspace git](./gitsync.md). `dir` is
an absolute path outside QueryView's data directory; only these three
names are read, and none through a symlink. Inline `name` and `params` win over `meta.yaml`; `dir`
together with `html` or `queries` is refused.

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
  `dimension`, a text box for a `text` (sent on Enter or on leaving it). A
  change re-runs the dashboard.

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
| `value` (default) | quoted string literal, single quotes doubled (and backslashes on ClickHouse) | `{region}` → `'eu'` |
| `identifier` | a quoted table/column, in the connection's own quoting | `{field}` → `"city"` (`` `city` `` on ClickHouse) |
| `dimension` | a checkbox: its own column when checked, `''` when not | `{category}` → `"category"` / `''` |
| `text` | whatever was typed, as a quoted string literal | `{note}` → `'o''k'` |

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

## Snapshot

**Snapshot** downloads the open dashboard as one static `<name>.html`, as it
stands at the current parameters. Print the file for a PDF.

- Each widget shows every row it holds, without controls or a scroll box,
  under a caption of its row count, limit, offset and order. Raise its
  **Limit** first for more rows.
- A canvas chart becomes an image; a dropdown, its chosen value.
- Refused while a widget is still loading.
- The file runs no script and redirects nowhere, whatever the dashboard's
  HTML contains: the host puts a script-blocking policy ahead of the frame's
  text. Stylesheets, fonts and images from elsewhere are still fetched when
  it is opened; embedded frames are not.
- A WebGL chart or a canvas holding a cross-origin image comes out blank; a
  password field, empty.
- It holds rendered query results: treat the file as data.

## Isolation & security

The HTML renders in
`<iframe sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" srcdoc=…>`
**without** `allow-same-origin`, giving it an opaque origin: it can run JS and load CDN
assets but cannot read the app's storage or call `/api/*` as the session (it
has neither the session id nor any credential). A link the page opens with
`target="_blank"` lands in a normal tab. The page cannot print or download;
[Snapshot](#snapshot) is the way out. Data reaches it only through the
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
