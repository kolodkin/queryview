# Queries — the SQL scratchpad

The **Queries** page (`/sql`) is a flat SQL textbox for exploring and for
writing: whatever you type runs **as written** against the session's selected
database — `CREATE`, `INSERT`, `ALTER`, `DROP` included — with no pagination
wrapper, no saved names, no column pickers. It complements
[QueryView](./query.md), which wraps a single `SELECT` for paging, saving and
presentation, and the MCP `run_query` tool, which stays read-only.

Before a database is selected the page redirects to Connect, like QueryView.

## Layout

```
┌───────────────────────────────────────────────────────────┐
│                         Queries                           │
│ ┌───────────────────────────────────────────────────────┐ │
│ │ CREATE TABLE t (id INTEGER);                          │ │  ← SQL textarea
│ │ INSERT INTO t VALUES (1), (2);                        │ │
│ │ SELECT * FROM t;                                      │ │
│ └───────────────────────────────────────────────────────┘ │
│ [Run]  Separate statements with ; …                       │
│ ┌ CREATE TABLE t (id INTEGER) ──────────────────────────┐ │
│ │ OK · 3 ms                                             │ │  ← one block per
│ ├ INSERT INTO t VALUES (1), (2) ────────────────────────┤ │     statement
│ │ INSERT 0 2 · 1 ms                                     │ │
│ ├ SELECT * FROM t ──────────────────────────────────────┤ │
│ │ 2 rows · 2 ms                                         │ │
│ │ id                                                    │ │
│ │ 1                                                     │ │
│ │ 2                                                     │ │
│ └───────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

- **SQL textarea** — the script. Drag its corner to resize.
- **Run** (or **Ctrl/⌘+Enter** in the textarea) — runs the script. If some text
  is **selected**, only the selection runs, so a page of statements can be run
  one at a time.
- **Result blocks** — one per statement that ran, in order: the statement, a
  summary line, and the rows when it returned any (the same grid as QueryView
  and the explorer, with the cell popup for long values).

## Multiple statements

Statements are separated by `;`. The split skips semicolons inside `'…'`,
`"…"`, `` `…` ``, `$$…$$` bodies, `-- …` line comments and `/* … */` block
comments; blank statements are dropped. An unterminated quote keeps the rest of
the script in one statement, so the database reports the real syntax error.

Statements run **in order on one connection** and **stop at the first
failure**: the failing statement's block shows the error in red, and anything
after it is not run. Nothing is rolled back — a statement that succeeded before
the failure stays applied (write `BEGIN; …; COMMIT;` yourself on a driver that
supports it).

## What a block shows

| Statement | Summary |
| --- | --- |
| Returned rows | `N rows · T ms`; when the result was cut at **1000 rows**, `first 1000 rows, more exist · T ms` |
| No rows (DDL, DML) | the driver's own status — ClickHouse `OK`, Postgres's command tag (`INSERT 0 3`), DuckDB `OK` — `· T ms` |
| Failed | the driver's error message |

The 1000-row cap is there because the page has no pagination: a bare
`SELECT *` must not pull a whole table into the browser. Page it with your own
`LIMIT`/`OFFSET`, or use QueryView.

Values arrive in the same JSON shape as every other result
([Results & CSV](./query.md#results--csv)), so 64-bit integers and decimals are
quoted strings and collections render with their default views.

## Per driver

- **ClickHouse** — each statement is sent as an HTTP **POST** (a GET is
  read-only on the ClickHouse HTTP interface, so writes would be refused) with
  `default_format=JSONCompact`. A statement with its own `FORMAT` clause bypasses
  that; its text is shown as the summary instead of rows.
- **Postgres** — one connection per run, each statement prepared and executed
  on it; a statement with no result columns reports its command tag.
- **DuckDB** — the file is opened **read-write** for the run (every other page
  opens it read-only). A long-running script therefore blocks the explorer and
  QueryView against the same file until it finishes.

## Session

The textbox's text is session state — a reload brings it back — but the result
blocks are not, like every other view ([session.md](./session.md)); a reload
never re-runs a script. Switching database clears the blocks on screen (they
came from somewhere else now) and keeps the text.

## API

| Method | Path              | Body    | Result |
| ------ | ----------------- | ------- | ------ |
| POST   | `/api/db/execute` | `{sql}` | `{ok, results:[{sql, ok, meta, data, truncated, status, message, elapsed_ms}]}` — one entry per statement run (the list ends with the failing one, if any). `meta`/`data` are set for a row-returning statement (`data` capped at 1000 rows, `truncated` says so) and `null` otherwise, when `status` carries the driver's word. `ok` on the envelope is about the request; a failed statement is `ok:false` in its own entry. Empty `sql` → `400`; no session / no database → `409`. |

## Related docs

- [query.md](./query.md) — QueryView: the paginated, saveable single query.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [session.md](./session.md) — what a session remembers.
- [api.md](./api.md) — the full backend JSON API.
