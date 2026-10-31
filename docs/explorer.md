# Explorer — the classical table navigator

The landing page for a live connection (`/explorer`, next to
[queries](./queryview.md) and [dashboards](./dashboard.md) in the corner nav —
see [queryview.md](./queryview.md#landing-page)): a sidebar lists the active
database's tables; clicking one browses its rows. No SQL is typed — the page generates
`SELECT * FROM "<table>"` and drives it with the same field select and
order-by select the query panel uses.

## Layout

```
+------------------------------------------------------------+
| (o) test                     QueryView Explorer Dashboard  |
|                                                            |
| +--------+ +---------------------------------------------+ |
| | Tables | | items (refresh) Limit [100] < Prev Next >   | |
| | events | | +---------------------------------------+   | |
| | items <| | | Fields 2/2 v  Order by v  1.id ASC    |   | |
| | users  | | +---------------------------------------+   | |
| |        | |  id | name                                  | |
| |        | |  ...| ...                                   | |
| +--------+ +---------------------------------------------+ |
+------------------------------------------------------------+
```

- **Sidebar** — the tables of the session's selected database, from
  `GET /api/db/tables`. A DuckDB folder connection adds a **Union by name**
  checkbox beside the heading (see [DuckDB folder mode](#duckdb-folder-mode)). Each entry shows the engine's row-count and size
  estimates under the name (e.g. `1.2K rows · 3.4MB`), and a **copy** icon
  that copies the name without opening the table. Row counts abbreviate with K/M/G/T/P at each power of
  1000, byte sizes with KB/MB/GB/TB/PB at each power of 1024; an estimate the
  engine doesn't track (views, a never-analyzed Postgres table) is simply
  omitted. The list refreshes when the active database changes (via the
  connection pill); a selected table that no longer exists is deselected.
- **Table search** — the box above the list filters it by case-insensitive
  substring of the name; Enter opens the first match.
- **Sidebar width** — drag the panel's right edge for names too long to fit the
  256px default (200–600px); ←/→ nudge it, Home or a double-click resets, as
  does a **Reset width** button beside the *Tables* heading. A name that still
  overflows truncates, with the full name as a tooltip. The width persists
  under the the session's `ui` blob key (see `frontend/src/app/session.ts`:
  one key per view, settings as JSON, so a new option costs no new key).
- **Rows panel** — the selected table's rows. The selection lives in the URL
  (`/explorer?table=<name>`), so reloads and links land on the same table.
- **Viewport height** — the page fills the window (min 30rem, then the page
  scrolls), as the QueryView page does; the table list and rows grid scroll
  internally, keeping the grid's horizontal scrollbar on screen.
- **Loading** — panels show *Loading tables…* / *Loading rows…* rather than
  sitting empty. Re-running a loaded table (paging, a new order-by) keeps its
  rows on screen, dimmed, with a spinner by the table name.
- Without a ready connection the page shows a hint to connect on the QueryView
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
- **Refresh** — the ↻ after the table name re-runs the browse query at the
  current offset; the row loader shows meanwhile.
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
| DuckDB file | `SHOW TABLES` against the file (no database picker)         | `duckdb_tables()`'s `estimated_size` rows; bytes = distinct `pragma_storage_info` blocks × block size (null for views / `:memory:`) |
| DuckDB folder | the selected folder's data files and `*.<ext>` globs (below) | rows null (never scanned); bytes = file size, summed for a glob |

Like `/api/db/query` and `/api/db/describe`, the endpoint is session-scoped and
gated: no active connection or (for drivers with a picker) no selected database
is a 409.

## DuckDB folder mode

A DuckDB connection whose **Path** is a directory browses the filesystem: the
folders under it are the "databases" (relative paths, `.` being the root) and
the data files in the selected folder are the tables. Connecting lands on the
root; reopening the connection does too.

```
+------------------------------------------------+
| /data/exports/2024                             |  <- full path
| [ Search 3 folders...                        ] |
| [ .. ]                                         |  <- parent, hidden at root
| [ q1 ]                                         |
| [ q2 ]                                         |
| [ archive ]                                    |
| ---------------------------------------------- |
| connections ...  [Disconnect]                  |
+------------------------------------------------+
```

- **Pill menu** — one level at a time: the selected folder's full path, then
  its subfolders and **..**; picking one enters it, which lists its files in
  the sidebar. The pill reads `<connection> · <folder name>` with the full path
  as its tooltip. Folders are scanned at connect and when the menu opens,
  shallowest first; hidden entries and symlinks are skipped.
- **Tables** — files named `.parquet`, `.csv`, `.tsv`, `.json`, `.jsonl` or
  `.ndjson`, the non-parquet ones also with a `.gz` or `.zst` suffix. The
  browse query is the matching reader, e.g. `SELECT * FROM read_csv('items.csv')`.
  An extension with two or more files also gets a **`*.<ext>`** entry (`*.csv`,
  `*.csv.gz`) whose query lists those files, so a file added later needs a
  refresh. Hidden files, symlinks and names with `*`, `?` or `[` are skipped.
- **Path** — beside the selected file's name, its path from the root in small
  type (`sub/nested.csv.gz`) with a copy button, for SQL on the query page.
  A `*.<ext>` entry has none.
- **Max entries** — the most folders scanned and files listed per folder,
  default 1000 (1–100000); a blank or non-number entry is ignored. A cut list
  says so: "More than N files" above the sidebar (its `*.<ext>` entries then
  read only the listed files), "More than N folders" in the pill menu.
  Remembered with the sidebar width; the server reads it from the session.
- **Union by name** — adds `union_by_name = true` to `*.<ext>` queries, so a
  column only some files have is kept (NULL elsewhere) rather than dropped.
  Remembered with the sidebar width.
- **Paths** — folder mode opens `:memory:` with `file_search_path` set to the
  root, and queries name files by their path from it, so SQL reads the same
  file whichever folder is selected. Only folders under the root can be
  selected. **Test** and connecting both refuse a root with a comma (DuckDB
  reads it as a list) or one that cannot be listed; after a backend restart, a
  folder that is gone leaves the session disconnected.
