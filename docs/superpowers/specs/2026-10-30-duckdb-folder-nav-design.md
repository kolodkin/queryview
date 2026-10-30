# DuckDB folder navigation — design

## Intent

Give DuckDB connections the database/table navigation ClickHouse and Postgres
have, mapped onto the filesystem: a connection points at a **root directory**,
directories are the "databases", and the data files inside a directory
(`.parquet`, `.csv`, `.json` and their compressed variants) are the "tables".
Picking a folder enters it; the Explorer browses its files without typing SQL.

Why: DuckDB's natural use is a directory of exported files, not a `.duckdb`
database. Today the driver only opens one file and has no picker, so a folder
of parquet/CSV exports has no navigation at all.

## Goals

- A DuckDB connection whose `path` is a directory gets a database picker and an
  Explorer table list, with the same pill, picker, Explorer and API as the other
  drivers.
- Browse a file as a table in one click, including gzip/zstd compressed CSV and
  JSON.
- Browse all files of one extension in a folder as one table (a `*.csv` glob
  entry), with an Explorer checkbox to match columns by name across files.
- Always show the full path of the folder being browsed.

## Non-goals

- Listing `.duckdb` files inside directories or the tables inside them. A
  `.duckdb` file remains what it is today: the connection's `path`.
- A tree widget. The picker stays a flat list showing one level at a time.
- Arbitrary user-typed glob patterns in the picker. The query page covers that.
- Writing files. Dir mode is read-only browsing; scripts run as they do today.

## Anti-goals

- Escaping the root: nothing the UI can select may read outside the configured
  directory.
- Scanning data to produce estimates. Row counts stay null rather than running a
  `COUNT(*)`.
- Breaking existing DuckDB connections whose `path` is a file or `:memory:`.

## Constraints (how it works today)

- `Driver.list_databases` returns a flat `list[str]`, cached on the session at
  connect (`_build_session`) and refreshed by `GET /api/db/databases`.
  `select_database` validates the pick against that cached list. `database` is
  one string stored on the session and in saved queries/dashboards.
- The frontend shows a picker whenever `connection.databases` is non-empty and
  treats the connection as ready when `database !== null` (`isReady` in
  `frontend/src/app/connection.ts`). Two picker surfaces share the list: the
  pill menu `DatabaseMenu` (`App.tsx`) and the Connect page `DatabasePicker`
  (`ConnectView.tsx`), both filtered by typed text.
- The backend gate `_gated_session` uses the static `Driver.requires_database`
  flag (False for DuckDB) to 409 when no database is selected.
- `list_tables` in `connect.py` attaches each table's browse `query` via
  `select_all_sql(name, ident_quote)`; the frontend never builds SQL.
- `DuckDBDriver` opens `config.path` per call; the explorer lists `SHOW TABLES`.

## Approaches considered

1. **Two-level reuse** (chosen): directories are databases (relative paths),
   files are tables. Reuses the pill, picker, gate, Explorer and API shape.
   Picker renders one level at a time by filtering the cached list client-side.
   Trade-off: the full directory list is walked at connect, so depth is capped.
2. **Tree picker**: a nested directory tree component replacing the flat picker
   for DuckDB. Truer to a file browser, but a new sidebar component, a new nav
   API shape, and `database` stops meaning one thing across drivers. Rejected
   for cost; the user's "flat list, click to enter" model doesn't need it.
3. **One in-memory view per file**, keep `SHOW TABLES`: no API or UI change at
   all, but flattens the hierarchy away. Rejected: the folder nav is the point.

## Design

### Modes of a DuckDB connection

`path` decides the mode at connect time:

| `path`                | Mode         | Databases                    | Tables                          |
| --------------------- | ------------ | ---------------------------- | ------------------------------- |
| `:memory:` or a file  | file (today) | `[]` (no picker)             | `SHOW TABLES` with estimates    |
| an existing directory | folder (new) | `.` plus every subdirectory  | data files + glob entries       |

A path that is neither a file, a directory, nor `:memory:` fails to connect
with DuckDB's own error, as today.

### Folder mode: databases

`list_databases` walks the root with `os.walk` and returns relative POSIX paths:
`"."` for the root first, then `"2024"`, `"2024/exports"`, ... sorted. Hidden
entries (name starting with `.`) and symlinked directories are skipped.

**Depth cap**: the walk stops a few levels down (builder picks, 4 is fine) so a
huge root does not stall connect. Marked in code as
`shortcut: depth capped, upgrade to lazy per-folder listing if roots get deep`.

**Default selection**: in folder mode the session's `database` defaults to `"."`
when nothing is remembered, so connecting lands on the Explorer showing the
root's files, matching DuckDB's "straight to the explorer" behavior today. The
remembered database still wins when it is in the list.

### Folder mode: tables

`list_tables(config, database)` lists the regular files directly in
`root/<database>` (no recursion) whose name ends in one of:

| Base extension           | Reader          |
| ------------------------ | --------------- |
| `.parquet`               | `read_parquet`  |
| `.csv`, `.tsv`           | `read_csv`      |
| `.json`, `.jsonl`, `.ndjson` | `read_json` |

each optionally followed by `.gz` or `.zst` (DuckDB infers compression from the
suffix; parquet is compressed internally, so no suffix variants for it).

Entries, sorted by name:

- One per file: `name` is the file name, `bytes` is the file size, `rows` is
  null (no scan).
- One **glob entry** per distinct full extension that has two or more files in
  the folder, named `*.<ext>` (e.g. `*.csv`, `*.csv.gz`), `bytes` the sum,
  `rows` null. Listed after the files.

Each entry carries its own `query`, built by the driver, not by
`select_all_sql`:

```sql
SELECT * FROM read_csv('items.csv')
SELECT * FROM read_csv('*.csv')
SELECT * FROM read_csv('*.csv', union_by_name = true)   -- when union is on
```

File names are passed as SQL string literals with `'` doubled. Paths are
**relative to the selected folder**: every DuckDB connection open in folder mode
runs `SET file_search_path = '<root>/<database>'` first, so generated queries,
saved queries and SQL typed on the query page all resolve against the folder
being browsed. In folder mode the connection opened is `:memory:`.

`TablesResult` entries may now include `query`; `connect.list_tables` uses it
when present and falls back to `select_all_sql` otherwise, so other drivers
are untouched.

### Union by name

`GET /api/db/tables?union=1` asks the driver to add `union_by_name = true` to
glob queries (it is accepted by all three readers). Single-file entries are
unaffected. Other drivers ignore the parameter.

The Explorer shows a **Union by name** checkbox above the table list, only for
folder-mode DuckDB connections (`type === 'duckdb'` and a non-empty database
list). Toggling it refetches the list; the current table reloads with its new
query. The flag persists in the Explorer's `ui` blob key alongside the sidebar
width.

### Picker: one level at a time

Both picker surfaces (pill menu and Connect page) get the same treatment via
one small helper in `frontend/src/app/connection.ts`:

- In folder mode the items shown are the **children** of the current database
  (entries whose parent path equals it), displayed by their last path segment,
  plus a `..` item that selects the parent, hidden at the root.
- Clicking an item selects it (`POST /api/db/database`); since the picker is
  rendered from the current database, that one click also "enters" it.
- The typed filter still filters the shown children.
- A heading shows the **full path**: root plus the current relative directory
  (`/data/exports/2024`). The connection pill shows the folder name (the last
  segment, or the root's folder name for `.`), with the full path as its
  tooltip.

Sketch of the pill menu in folder mode:

```
+------------------------------------------------+
| /data/exports/2024                             |  <- full path
| [ .. ]                                         |  <- parent, hidden at root
| [ q1 ]                                         |
| [ q2 ]                                         |
| [ archive ]                                    |
| ---------------------------------------------- |
| connections ...  [Disconnect]                  |
+------------------------------------------------+
```

To show the full path the frontend needs the root: `/api/db/connect`,
`/api/db/open` and `/api/session` responses include the driver's `root` for
folder-mode DuckDB (absolute, as configured). Other drivers send nothing.

### Gate

`_gated_session` 409s with `no-database` when
`(driver.requires_database or s.databases) and not s.database`. The static
flag keeps its meaning for ClickHouse/Postgres; a folder-mode DuckDB session
is gated by having a list. With the `"."` default this only bites when a
remembered folder has vanished.

### Security

- Selection is validated against the cached list, as today, so `..` segments
  or absolute paths can never become the active folder.
- The walk follows no symlinks and skips hidden entries.
- `file_search_path` scopes relative names in generated queries to the folder;
  user-typed SQL on the query page can still name any path the process can
  read, which is already true today.

### Docs

Update `docs/connect.md` (DuckDB takes a file *or a folder*), `docs/explorer.md`
(per-driver table listing row, the Union checkbox, folder picker), and
`docs/queryview.md` where the picker is described. Delete this spec and its plan
when the work ships (`docs/AGENTS.md`).

### Tests

Per the project `testing` skill:

- Driver tests in `backend/queryview/drivers/test_duckdb.py`: folder mode lists
  `.` and subdirectories, skips hidden ones, caps depth; tables list files,
  compressed variants and glob entries with byte sums; queries resolve via
  `file_search_path`; union flag changes glob queries only; file mode unchanged.
- API test: `/api/db/tables?union=1` on a folder-mode session; gate 409 when
  the folder list is non-empty and nothing selected.
- Frontend unit test for the children/parent helper.
- One e2e: connect to a temp folder with a CSV and a subfolder, enter the
  subfolder from the pill, see the full path, browse a file.

## Left to the builder

- Exact depth cap and the helper names.
- Whether parquet row counts come from `parquet_file_metadata` (cheap) or stay
  null like the others; null is acceptable for the first cut.
- Checkbox placement details within the Explorer sidebar header.
