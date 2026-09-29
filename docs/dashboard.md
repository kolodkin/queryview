# Dashboards (agent-authored, pushed to a live session)

A **dashboard** is an HTML layout plus a set of named SQL queries. An AI agent
authors one and pushes it into a live, armed QueryView browser session over MCP;
it is also persisted so it can be reopened later by name.

Responsibilities mirror the [remote-control](./remote.md) layer: the agent never
receives query results back. The **browser** (trusted code with a session) runs
the queries on its session's connection and feeds the results into the
agent-authored HTML, which renders inside an isolated iframe.

## The page (`/dashboard`)

`/dashboard` is a top-level page beside Connect (`/connect`) and the query
workflow (`/queries`); see [queryview.md](./queryview.md). It has:

- a **dropdown** of saved dashboards — selecting one sets `?name=<name>`, so the
  URL is shareable and the back button works;
- a **sandboxed iframe** that renders the selected dashboard.

Open it from the corner nav (just the dropdown), or by URL — `?name=<name>`
jumps straight to one. Reopening
re-fetches the dashboard and re-runs its queries, so a reloaded or shared link
always shows live data.

## The `push_dashboard` MCP tool

The FastMCP server at `/mcp` (see [remote.md](./remote.md) for arming and the
session id) exposes:

- `push_dashboard(session_id, name, html, queries, params?)` — push the
  dashboard **draft** to the browser identified by `session_id`, which navigates
  to `/dashboard?name=<name>` and renders it. It does **not** persist — only the
  user's **Save** button in the dashboard view writes it to the store (mirrors
  `push_query`). Returns `{ok, pushed, message, database}`; an unknown/disarmed
  `session_id` reports `pushed:false`, a disconnected one `not connected`.

A dashboard never names a [connection](./connect.md): it runs on the
**viewing** session's connection and selected database, like a saved query. So
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

As with [query params](./query.md#query-parameters), `options` and `options_sql`
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

The HTML renders in `<iframe sandbox="allow-scripts" srcdoc=…>` **without**
`allow-same-origin`, giving it an opaque origin: it can run JS and load CDN
assets but cannot read the app's storage or call `/api/*` as the session (it
has neither the session id nor any credential). All data reaches it only through the injected `window.queries`,
whose JSON has `<` escaped so result data containing `</script>` can't break out
of the prologue.

Like the rest of the app (and [predefined queries](./query.md)), persisted
dashboards are **global**, shared via SQLite, and keyed by name. The agent HTML
is untrusted and confined to the sandbox; it never sees connection secrets or
the session id.

## Related docs

- [queryview.md](./queryview.md) — the pages and the Connect page.
- [remote.md](./remote.md) — arming a session, the session id, the MCP server.
- [api.md](./api.md) — `/api/runqueries`, `/api/dashboards`, the `dashboard` SSE event.
- [connect.md](./connect.md) — connections and their stored database.
