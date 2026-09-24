# Explorer — the classical table navigator

The landing page for a live connection (`/explorer`, next to
[queries](./queryview.md) and [dashboards](./dashboard.md) in the corner nav —
see [queryview.md](./queryview.md#landing-page)): a sidebar lists the active
database's tables; clicking one browses its rows. No SQL is typed — the page generates
`SELECT * FROM "<table>"` and drives it with the same field select and
order-by select the query panel uses.

## Layout

```
┌───────────────────────────────────────────────────┐
│ 🟢 connected - test        Queries Explorer Dashboard │
│                                                     │
│ ┌────────┐ ┌─────────────────────────────────────┐ │
│ │ Tables │ │ items      Limit [100] ← Prev Next → │ │
│ │ events │ │ ┌─────────────────────────────────┐ │ │
│ │ items ◀│ │ │ Fields 2/2 ▾ Order by ▾ 1.id ASC│ │ │
│ │ users  │ │ └─────────────────────────────────┘ │ │
│ │        │ │  id │ name                          │ │
│ │        │ │  …  │ …                             │ │
│ └────────┘ └─────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

- **Sidebar** — the tables of the session's selected database, from
  `GET /api/db/tables`. Each entry shows the engine's row-count and size
  estimates under the name (e.g. `1.2K rows · 3.4MB`), leaving the name the
  panel's full width: row counts abbreviate with K/M/G/T/P at each power of
  1000, byte sizes with KB/MB/GB/TB/PB at each power of 1024; an estimate the
  engine doesn't track (views, a never-analyzed Postgres table) is simply
  omitted. The list refreshes when the active database changes (via the
  connection pill); a selected table that no longer exists is deselected.
- **Sidebar width** — drag the panel's right edge for names too long to fit the
  256px default (200–600px); ←/→ nudge it, Home or a double-click resets, as
  does a **Reset width** button beside the *Tables* heading. A name that still
  overflows truncates, with the full name as a tooltip. The width persists
  under the the session's `ui` blob key (see `frontend/src/app/session.ts`:
  one key per view, settings as JSON, so a new option costs no new key).
- **Rows panel** — the selected table's rows. The selection lives in the URL
  (`/explorer?table=<name>`), so reloads and links land on the same table.
- **Viewport height** — the page fills the window (min 30rem, then the page
  scrolls); the table list and rows grid scroll internally, keeping the grid's
  horizontal scrollbar on screen.
- **Loading** — panels show *Loading tables…* / *Loading rows…* rather than
  sitting empty. Re-running a loaded table (paging, a new order-by) keeps its
  rows on screen, dimmed, with a spinner by the table name.
- Without a ready connection the page shows a hint to connect on the Queries
  page first; connection state is shared app-wide (see
  [queryview.md](./queryview.md)).

## Browsing behavior

Selecting a table describes `SELECT * FROM "<table>"` to populate the pickers,
then loads the first page. The pickers are the query panel's, with the same
semantics:

- **Select fields** — client-side column visibility only; no re-run.
- **Order by** — server-side `ORDER BY`; toggling a column or flipping its
  ASC/DESC direction re-runs the query immediately (browsing wants instant
  feedback, so unlike the query panel there is no separate Run button).
- **Pagination** — Limit (applies on blur) plus Previous/Next, mapping to the
  query API's `limit`/`offset`.
- **Long values** — columns are a fixed 50 characters wide; longer values scroll
  inside their cell and get a button opening the parsed/raw
  [cell popup](./query.md#long-values).

The browse SELECT always selects `*` and comes from the server: each
`/api/db/tables` entry carries its ready-to-run `query`, quoted with the
driver's own identifier quote (backticks for ClickHouse, double quotes for
Postgres/DuckDB) — the frontend never guesses dialect quoting.

## Table listing per driver

`GET /api/db/tables` lists `{name, rows, bytes, query}` per table via the
driver's `list_tables` (`query` is attached by the session layer). Rows and
bytes are cheap engine estimates — never a `COUNT(*)` scan — and null when the
engine doesn't track them:

| Driver     | Names                                                       | Estimates |
| ---------- | ----------------------------------------------------------- | --------- |
| ClickHouse | `system.tables` for the selected database (same set as `SHOW TABLES`) | `total_rows` / `total_bytes` (null for views) |
| Postgres   | `pg_class` for the `public` schema, tables and views — what an unqualified name resolves to under the default `search_path`; other schemas need explicit SQL on the query page | planner's `reltuples` (null until first ANALYZE/VACUUM) / `pg_total_relation_size` |
| DuckDB     | `SHOW TABLES` against the file (no database picker)          | `duckdb_tables()`'s `estimated_size` rows; bytes = distinct `pragma_storage_info` blocks × block size (null for views / `:memory:`) |

Like `/api/db/query` and `/api/db/describe`, the endpoint is session-scoped and
gated: no active connection or (for drivers with a picker) no selected database
is a 409.
