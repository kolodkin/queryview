# Queries — the SQL scratchpad

The **Queries** page (`/queries`) is a flat SQL textbox for exploring and for
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
│                                    [Min] [S] [M] [L] [XL]  │
│ ┌───────────────────────────────────────────────────────┐ │
│ │ CREATE TABLE t (id INTEGER);                          │ │  ← SQL textarea
│ │ INSERT INTO t VALUES (1), (2);                        │ │
│ │ SELECT * FROM t|                                      │ │
│ └───────────────────────────────────────────────────────┘ │
│ [▶ Run] [▶▶ Run all] [Open in QueryView]                  │
│ 3 statements · 2 rows · 6 ms                              │  ← the status line
│ ┌───────────────────────────────────────────────────────┐ │
│ │ id                                                    │ │  ← the last
│ │ 1                                                     │ │     statement's rows
│ │ 2                                                     │ │
│ └───────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

- **SQL textarea** — the script. **Min / S / M / L / XL** set its height, as on
  QueryView; **Min** collapses it so the results table gets the room (the text
  is kept).
- **▶ Run** (**Ctrl/⌘+Enter**) — runs the **statement under the cursor**, or
  the **selection** when there is one. The cursor's statement is the one whose
  text contains it; just past a `;` on the same line still counts as that
  statement, a blank line below belongs to the next one.
- **▶▶ Run all** (**Ctrl/⌘+Shift+Enter**) — runs the whole script.
- **Status line** — one line per run, nothing more: the statements are already
  in the textbox. `2 rows · 2 ms` for a single statement; `3 statements ·
  2 rows · 6 ms` for a script (what the last one left, total time). A failed run
  shows in red which statement failed and the error; the statement itself is
  marked red in the textbox until you click into it.
- **Results table** — the rows of the **last statement run**, when it returned
  any (the same grid as QueryView and the explorer, with the cell popup for
  long values). A run whose last statement was DDL, DML or a failure shows no
  table.
- **Open in QueryView** — enabled while that table is showing: loads the last
  statement's SQL into [QueryView](./query.md) for paging, column pickers,
  saving and CSV. Nothing runs until you click Execute there.

## Multiple statements

Statements are separated by `;`. The split skips semicolons inside `'…'`,
`"…"`, `` `…` ``, `$$…$$` bodies, `-- …` line comments and `/* … */` block
comments; blank statements are dropped. An unterminated quote keeps the rest of
the script in one statement, so the database reports the real syntax error.

Statements run **in order on one connection**.

## An error stops the run

**Run all** stops at the first statement that fails. Nothing after it runs: the
status line says `Statement #k Failed - <error>` in red, that statement is
marked red in the textbox, and statements `k+1` onward are not sent.

Nothing is rolled back either — statements `1 … k-1` succeeded and stay
applied. Fix the failing statement, then run the rest: put the cursor on the
next one and use **▶ Run**, or select from it to the end. Wrap the script in
`BEGIN; …; COMMIT;` yourself on a driver that supports transactions if partial
application is not acceptable.

## What the status line shows

| Last statement run | Status line |
| --- | --- |
| Returned rows | `N rows`; when the result was cut at **100 rows**, `first 100 rows, more exist` |
| No rows (DDL, DML) | the driver's own status — ClickHouse `OK`, Postgres's command tag (`INSERT 0 3`), DuckDB `OK` |
| Failed | `Statement #k Failed - <the driver's error>`; the statement itself is **marked red in the textbox** until you focus or edit it |

A single statement's line ends with its time; a script's starts with how many
statements ran and ends with the total.

The 100-row cap is there because the page has no pagination: a bare
`SELECT *` must not pull a whole table into the browser. Page it with your own
`LIMIT`/`OFFSET`, or hand the statement to QueryView with **Open in QueryView**.

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

The textbox's text is session state — a reload brings it back — but the status line
and the table are not, like every other view ([session.md](./session.md)); a reload
never re-runs a script. Switching database clears them (the rows came from
somewhere else now) and keeps the text. **Open in QueryView** writes the
statement into the query panel's own session state, which is how QueryView
finds it on arrival.

## API

| Method | Path              | Body    | Result |
| ------ | ----------------- | ------- | ------ |
| POST   | `/api/db/execute` | `{sql}` | `{ok, results:[{sql, ok, meta, data, truncated, status, message, elapsed_ms}]}` — one entry per statement run (the list ends with the failing one, if any). `meta`/`data` are set for a row-returning statement (`data` capped at 100 rows, `truncated` says so) and `null` otherwise, when `status` carries the driver's word. `ok` on the envelope is about the request; a failed statement is `ok:false` in its own entry. Empty `sql` → `400`; no session / no database → `409`. |

## Related docs

- [query.md](./query.md) — QueryView: the paginated, saveable single query.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [session.md](./session.md) — what a session remembers.
- [api.md](./api.md) — the full backend JSON API.
