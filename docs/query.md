# Querying — results, paging & the grid

How a query runs and how its rows render, wherever the app shows a results
grid: the [`<qv-select-view>`](./dashboard.md#widgets) widget on
[dashboards](./dashboard.md) (ad-hoc SQL is a dashboard's **New query** draft),
the [explorer](./explorer.md), and the [Scripts](./scripts.md) page.

## Pagination

The backend paginates by wrapping the query:

```sql
SELECT * FROM (
<your query>
) LIMIT <limit> OFFSET <offset>
```

So pages are stable only if the query defines its own order — include an
`ORDER BY`, or pick **Order by** columns in the grid's **Fields** bar. There is
no total-row count, so **Next** can page past the last row into an empty result.

## Fields, selection & ordering

**Fields** describes the query's output columns (names and types) without
scanning data, and fills two searchable dropdowns:

- **Select fields** — a toggle per column for what the table shows.
  **Client-side and immediate**; **Download CSV** ignores it. **All** / **None**
  flip every toggle. A column the last **Fields** call didn't cover always
  shows, so a stale list can't blank the table.
- **Order by** — one or more columns, each **ASC** (default) or **DESC**.
  **Server-side**: a change re-runs the query. Column names are quoted and
  directions whitelisted, so the picker can't inject SQL.

## Default views for complex types

Cells whose value is a collection — a ClickHouse **`Array`**, **`Map`**, or
**`Tuple`**, or any JSON array/object another driver returns — get a built-in
**default view** with no cell template: instead of the serialized text
(`["a","b"]`, `{"x":1}`) the cell renders a **plain vertical list**. When a
collection has more than 3 items the cell starts **collapsed**, showing the
first 3 with a `… (+N more)` expander; expanding reveals the rest plus a
`▾ collapse` control.

- **Array** — one element per line.
- **Map** — one `key → value` per line.
- **Tuple** — one `name: value` per line for a **named tuple**
  (`Tuple(id Int32, name String)` → `id: 1`); unnamed tuples use the positional
  index (`0:`, `1:`).
- **`Array(Tuple(...))`** — a list of tuples, **one tuple per line**
  (`id: 1, name: a`), so a list of records stays scannable.
- **`Array(Map(...))`** — a list of maps, **one map per line**
  (`x → 1, y → 2`). The outer array collapses to the first 3 elements.
- Nesting beyond those two cases (e.g. `Array(Array(...))`, a complex `Tuple`
  field) renders that nested piece as **JSON text**.

Values arrive structured (see [Results & CSV](#results--csv)); the column type
from the result's own metadata only decides map (`→`) versus tuple (`:`)
labelling. A [`<template column>`](./dashboard.md#widgets) for a column **takes precedence**
over its default view (and is the way to opt out). Default views apply to the
on-screen table only — **Download CSV** keeps the database's own serialized
value.

## Long values

Each result column fits its header or its widest value on the page, **capped at
50 characters**, so a table of short values fits on screen and one long-text
column can't push the others off-screen. A longer value **scrolls inside its own
cell**.

An overflowing cell gets a button at its **left edge**, outside the scroller so
it stays put as the text moves. It opens the **cell popup** on the whole value,
and its glyph says what that value looks like:

- **`{ }`** — parses as JSON or YAML: the popup opens on a **collapsible tree**
  of the parsed document with a **Raw** toggle. Containers below the top level
  start folded, so a large document opens readable. A value the database sent
  as a collection (a ClickHouse `Map`, `Array`, `Tuple` or `JSON` column, a
  Postgres `jsonb`) is labelled by its column type, full type on hover; only
  text is labelled by the detected format (`json`, `yaml`).
- **`⤢`** — long text that is neither: the popup shows it as wrapped raw text.

Detection is deliberately conservative, because almost any string is valid YAML.
JSON is accepted whenever it parses to an **object or array**; YAML only for text
that **already spans lines** and also yields one — so `status: healthy`, a
Windows path, or a line of prose stay plain text.

The [explorer](./explorer.md) shares this grid, so it behaves identically. A
cell template still decides how a cell *renders*; the popup always shows the
underlying value.

## Results & CSV

Results come back as `{meta: [{name, type}], data: [[…]]}` — ClickHouse's
`JSONCompact` shape, which the other drivers reproduce from their native rows.
Values are JSON as the database emitted them; 64-bit integers and decimals are
quoted as strings so nothing rounds in the browser, and arrays, maps, and
tuples arrive as JSON arrays and objects (named tuples as objects).
**Download CSV** re-runs the current page as `CSVWithNames` and saves
`query.csv` — current page only, always every column regardless of the
**Select fields** view.

## Co-edit & edit lock

An agent (via the `push_dashboard` / `push_script` MCP tools) and a human can
share a live session without clobbering each other, arbitrated by a
**server-side edit lock** on the session (owner: none / human / agent, held in
memory).

- **Human** acquires the lock on **focus** inside the dashboard's
  [SQL panel](./dashboard.md#the-sql-panel) or the [Scripts](./scripts.md)
  editor and releases it on **blur** (a ~10s heartbeat refreshes a 30s TTL, so
  a frozen tab can't hold it forever; a closed tab drops it immediately).
- **Agent** pushes are atomic: a push checks the lock and, if a human holds it,
  is rejected with `blocked, user editing` (the agent backs off and retries).
- When an agent push lands, the browser shows a brief toast so the human
  notices the page changed.
- Pushes never persist — only the human's **Save** writes to the store. An
  agent can't name a new dashboard: it pushes unnamed and the human names it.

The lock and channels live in one process's memory (like the SSE relay), so this
assumes a single backend process; multi-worker deployments would need a shared
backplane.

## API

`/api/db/query` (a page of rows, or CSV), `/api/db/describe` (output columns)
and `/api/remote/lock` (the edit lock): see [api.md](./api.md). Queries run on
the session's connection and selected database, within its
[query timeout](./queryview.md#query-timeout).

## Related docs

- [dashboard.md](./dashboard.md) — dashboards, the SQL panel and the widgets.
- [scripts.md](./scripts.md) — the Scripts page: a `;`-separated script run as written, writes included.
- [explorer.md](./explorer.md) — browsing tables with the same grid.
- [api.md](./api.md) — the full backend JSON API.
