# Querying

The **query panel** is what a ready session shows on **Queries** — a database is
selected, or the driver has no picker — on the first visit and on every return.
(Connecting itself lands on the explorer; see
[queryview.md](./queryview.md#landing-page).) It runs SQL against the session's selected database, pages
through results, saves/loads reusable queries, and exports the current page as
CSV. Typing `query` returns to it from a connection form; before a database is
selected it shows the hint `Select a database first.`

## Panel

```
┌───────────────────────────────────────────────────────────┐
│ [ query ]  [ Predefined queries… ▾ ]            [ Save ]   │
│                                    [Min] [S] [M] [L] [XL]  │
│ ┌───────────────────────────────────────────────────────┐ │
│ │ SELECT …                                              │ │  ← SQL textarea
│ └───────────────────────────────────────────────────────┘ │
│ [Execute] [Fields] Limit [100] Offset [0] [← Prev] [Next →]│
│                                          [Download CSV]    │
│ ┌───────────────────────────────────────────────────────┐ │
│ │ name | …                                              │ │  ← results table
│ │ alpha| …                                              │ │     (scrollable)
│ └───────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

In query mode the command **prompt** moves onto the panel's top row, next to the
predefined-query controls, to save vertical space.

- **SQL textarea** — the query to run. **Min / S / M / L / XL** change its height;
  **Min** collapses it to maximize room for results.
- **Execute** — runs the query at the current offset.
- **Fields** — introspects the query's output columns (see
  [Fields, selection & ordering](#fields-selection--ordering)).
- **Limit / Offset** — page size and starting row (defaults `100` / `0`).
- **Previous / Next** — step the offset by ±limit and re-run. Previous is
  disabled at offset `0`. There is no total-row count, so Next can page past the
  last row into an empty result.
- **Download CSV** — downloads the **current page** as `query.csv`, always with
  **all** columns (the field selection below is view-only).
- **Results table** — the rows for the current page. Like the explorer, the
  page fills the window (min 30rem) and the table takes the panel's remaining
  height (at least 12rem), scrolling inside it both ways.

## Fields, selection & ordering

**Fields** describes the current query's output columns (names and ClickHouse
types) without scanning data (ClickHouse `DESCRIBE (<query>)`), and populates two
pickers from that list, shown as two searchable dropdowns in one bar:

- **Select fields** — a toggle per column for what the results table shows.
  **Client-side and immediate**: toggling shows/hides the column with no re-query,
  and **Download CSV** ignores it (CSV always exports every column). **All** /
  **None** flip every toggle. New columns from a query edited since the last
  **Fields** call always show, so a stale list can't blank the table.
- **Order by** — pick one or more columns, each **ASC** (default) or **DESC**.
  **Server-side**, so it takes effect only on a re-run: **Execute** / **Previous** /
  **Next**, **Download CSV**, or **Run** (re-runs the
  whole query like Execute, applying the current limit/offset). Column names are
  backtick-quoted and directions whitelisted, so the picker can't inject SQL.

Editing the SQL doesn't auto-refresh the pickers — click **Fields** again to
re-describe.

## Pagination

The backend paginates by wrapping the query:

```sql
SELECT * FROM (
<your query>
) LIMIT <limit> OFFSET <offset>
```

So pages are stable only if the query defines its own order — include an
`ORDER BY` for predictable `Previous`/`Next` boundaries.

## Predefined queries

Predefined queries are reusable SQL **shared globally** (not per session), keyed
by **connection type** (e.g. `clickhouse`), stored in the `predefined_queries`
SQLite table:

```sql
CREATE TABLE predefined_queries (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  query_name TEXT NOT NULL,
  type       TEXT NOT NULL,   -- connection type (clickhouse, …)
  query      TEXT NOT NULL,
  cell_view  TEXT,            -- raw YAML; per-column render config + params (see below)
  UNIQUE (type, query_name)
);
```

- The **selector** lists saved queries for the active connection's type; choosing
  one loads its SQL into the textarea and makes it the active name. Its **+ New
  name…** item prompts for a fresh name (no separate name field).
- **Save** stores the textarea's SQL (and the `cell_view` YAML) under the
  **currently selected name** and refreshes the selector. Saving an existing name
  **upserts** (overwrites) it.

Renaming and deleting predefined queries are not yet supported — see
[future.md](./future.md).

## Cell views

Each predefined query can carry a **`cell_view`** map controlling how result
cells render. Author it as YAML in the **"Cell view"** modal (toolbar button just
before the **Min** toggle), stored as raw text on the query. The modal's **Save**
persists and closes; **Cancel** or the backdrop discards. Map keys are column
names; each entry has a `type` and a `value` template. Two placeholders are
substituted from the row being rendered:

- **`{cell}`** — this column's own raw value.
- **`{row.<column>}`** — the value of another column in the **same row** (e.g.
  `{row.name}` yields that row's `name` value). An unknown column name is left
  in place untouched.

```yaml
cve_id:
  type: link
  value: https://nvd.nist.gov/vuln/detail/{cell}
severity:
  type: custom
  value: <strong>{cell}</strong>
name:
  type: link
  value: https://example.com/items/{row.id}
```

Supported types:

- **`link`** — render the cell as `<a href target="_blank" rel="noopener noreferrer">{cell}</a>`. `{cell}` and any `{row.<column>}` are URL-encoded into the href; the resolved scheme must be `http`/`https` (anything else falls back to plain text).
- **`custom`** — render the `value` HTML verbatim with `{cell}` and any `{row.<column>}` substituted in. Substituted values are HTML-escaped (so DB content can't break out), but the template HTML is **trusted** and is not sanitized. **Anyone who can save a predefined query can inject markup/script that runs in every viewer's browser**, because predefined queries are shared globally with no auth.

Substitution is a single pass, so a cell value that itself looks like a
placeholder is rendered as literal (escaped) text rather than re-resolved
against the row.

Both wrappers (the `<a>` for `link`, the `<span>` for `custom`) carry
`data-testid="cell-<columnName>"`, so e2e tests can target rendered cells without
baking testids into the YAML.

Rendering uses the **saved** `cell_view` of the **currently selected** predefined
query — editor edits take effect only after **Save** (which re-fetches the list).
Ad-hoc SQL with no selected query renders plain, as does a broken (unparseable or
unrecognized-shape) `cell_view`.

Every write path — save, remote push, YAML import, git restore — **validates**
`cell_view` against this contract and rejects violations
(`invalid cell_view: …`). Reads stay lenient: rows stored before validation
existed still render, with broken entries falling back to plain text.

### Pushed cell views (MCP / remote)

A remote push (the `push_query` MCP tool, or `POST /api/remote/push`) may carry a
`cell_view` field — the same raw YAML — that styles **that pushed result only**.
It's a per-push override, not persisted: it wins over the selected query's saved
`cell_view` for rendering and is dropped on the next manual **Execute** or when a
query is picked from the dropdown. This lets an agent push a query *and* its
render rules in one call (e.g. show a `source` column as a custom HTML token)
without saving a predefined query.

## Default views for complex types

Cells whose value is a collection — a ClickHouse **`Array`**, **`Map`**, or
**`Tuple`**, or any JSON array/object another driver returns — get a built-in
**default view** with no `cell_view` authored: instead of the serialized text
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
labelling. An explicit `cell_view` entry for a column **takes precedence** over
its default view (and is the way to opt out). Default views apply to the
on-screen table only — **Download CSV** keeps the database's own serialized
value.

## Long values

Result columns are a **fixed 50 characters wide**, so one long-text column can't
stretch the grid and push the others off-screen. A longer value **scrolls inside
its own cell**; values that fit are untouched.

An overflowing cell gets a button at its **left edge**, outside the scroller so
it stays put as the text moves. It opens the **cell popup** on the whole value,
and its glyph says what that value looks like:

- **`{ }`** — parses as JSON or YAML: the popup opens on a **collapsible tree**
  of the parsed document with a **Raw** toggle. Containers below the top level
  start folded, so a large document opens readable.
- **`⤢`** — long text that is neither: the popup shows it as wrapped raw text.

Detection is deliberately conservative, because almost any string is valid YAML.
JSON is accepted whenever it parses to an **object or array**; YAML only for text
that **already spans lines** and also yields one — so `status: healthy`, a
Windows path, or a line of prose stay plain text.

The [explorer](./explorer.md) shares this grid, so it behaves identically. An
explicit `cell_view` still decides how a cell *renders*; the popup always shows
the underlying value.

## Query parameters

A predefined query can declare **dropdown selectors** whose chosen value is
substituted into the SQL. They live in a reserved **`params:`** key inside the
`cell_view` YAML (so `params` is never treated as a column-render rule). Each entry
has a `name` and a list of `options`:

```yaml
params:
  - name: source
    options: [a, b, c]
```

With the query:

```sql
select * from events where source = {source}
```

a labelled dropdown appears above the SQL textarea, one per param, populated with
the declared options. The placeholder **`{source}`** is replaced with the selected
value as a **quoted SQL string** (`source = 'b'`), with embedded single quotes
doubled — write the placeholder where a value goes, no quotes of your own. A
`{name}` with no matching param is left untouched; a param whose `{name}` never
appears in the query is harmless.

**Changing a dropdown re-runs the query immediately** (resetting to offset 0).
Substitution applies everywhere the query runs — **Execute**, **Previous** /
**Next**, **Fields** (`DESCRIBE`), and **Download CSV**. The first option is the
default.

## Options from a query (`options_sql`)

Instead of a static `options` list, a param can derive its choices from a query:

```yaml
params:
  - name: host
    options_sql: SELECT DISTINCT host FROM system.clusters ORDER BY host
```

The **first column of every row** becomes an option, in the query's own order
(use `DISTINCT` / `ORDER BY` yourself — results are not de-duplicated or sorted).
The query runs once against the current connection when the predefined query
loads, and results are cached for the session. The first row is the default.

`options` and `options_sql` are **mutually exclusive** — declaring both is
rejected at save time (and the client parse drops such an entry from
pre-validation rows). If the `options_sql` query **fails or returns no rows**, the param has
nothing to choose from, so the main query is **blocked** (run controls disabled)
and the error banner names the param.

Because values are constrained to the declared options (or the `options_sql` rows)
and quoted/escaped on substitution, params stay within the existing trust model
(the SQL textarea is already sent to the backend as-is). A broken or absent
`params:` block renders no dropdowns.

## Results & CSV

Results come back as `{meta: [{name, type}], data: [[…]]}` — ClickHouse's
`JSONCompact` shape, which the other drivers reproduce from their native rows —
and render as an HTML table, scrolling within the panel (wide results scroll
horizontally). Values are JSON as the database emitted them; 64-bit integers and
decimals are quoted as strings so nothing rounds in the browser, and arrays,
maps, and tuples arrive as JSON arrays and objects (named tuples as objects).
**Download CSV** re-runs the current page as `CSVWithNames` and saves
`query.csv` — current page only, always every column regardless of the **Select
fields** view.

## Co-edit & edit lock

An agent (via the `push_query` MCP tool) and a human can share a live session
without clobbering each other, arbitrated by a **server-side edit lock** on the
session (owner: none / human / agent, held in memory).

- **Human** acquires the lock on **focus** of any editable item in the query
  panel and releases it on **blur** (a ~10s heartbeat refreshes a 30s TTL, so a
  frozen tab can't hold it forever; a closed tab drops it immediately).
- **Agent** pushes are atomic: a push checks the lock and, if a human holds it,
  is rejected with `blocked, user editing` (the agent backs off and retries).
- A push is validated first: malformed `order_by`/`fields` are rejected with
  `invalid …` and nothing is delivered. `cell_view` stays lenient.
- When an agent push lands, the browser shows a brief **"Agent updated the
  query"** toast so the human notices the panel changed.
- **Save persists presentation:** the human's Save now stores `order_by` and the
  selected `fields` alongside `cell_view`, so reloading a predefined query
  restores its full presentation. Pushes never persist — only the human's Save
  writes to the DB.

The lock and channels live in one process's memory (like the SSE relay), so this
assumes a single backend process; multi-worker deployments would need a shared
backplane.

## API

| Method | Path                        | Body                                          | Result |
| ------ | --------------------------- | --------------------------------------------- | ------ |
| POST   | `/api/db/query`     | `{query, limit?, offset?, format?, order_by?}` | `{ok, meta:[{name, type}], data:[[…]]}` \| `{ok:false, message}`. `format:"csv"` returns `{ok, output}` (CSV text). `order_by` is `[{name, dir}]` (`dir` ASC/DESC). Empty query → `400`; no session → `409`. |
| POST   | `/api/db/describe`  | `{query}`                                     | `{ok, fields:[{name, type}]}` — the query's output columns, via `DESCRIBE`, no data scanned. \| `{ok:false, message}`. Empty query → `400`; no session / no database → `409`. |
| GET    | `/api/predefined-queries`   | `?type=<connType>`                            | `{queries:[{query_name, query, cell_view, order_by, fields}]}` for that connection type. `cell_view` is raw YAML text or `null`; `order_by` is `[{name, dir}]` or `null`; `fields` is `["col", …]` or `null`. |
| POST   | `/api/predefined-queries`   | `{query_name, type, query, cell_view?, order_by?, fields?}` | `{ok}`; upserts a predefined query. `cell_view` is optional raw YAML; `order_by`/`fields` persist the saved presentation (validated; malformed → `400`). Missing required fields → `400`. |
| POST   | `/api/remote/lock`          | `{session_id, action:"acquire"\|"release"}`   | `{ok, message}`; browser-only edit lock for a live session (acquire on panel focus + ~10s heartbeat, release on blur). Bad action → `400`. |

Queries run over the ClickHouse HTTP interface (HTTP Basic auth, 5s timeout),
scoped to the session's selected database.

## Related docs

- [queryview.md](./queryview.md) — the single-prompt page concept.
- [connect.md](./connect.md) — connecting, storage, sessions.
- [api.md](./api.md) — the full backend JSON API.
