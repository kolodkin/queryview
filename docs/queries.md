# Queries — the SQL scratchpad

The **Queries** page (`/queries`) is a flat SQL textbox: whatever you type runs
**as written** against the session's selected database — `CREATE`, `INSERT`,
`ALTER`, `DROP` included — with no pagination wrapper, no saved names, no
column pickers. [QueryView](./query.md) wraps a single `SELECT` for paging,
saving and presentation; the MCP `run_query` tool stays read-only. Before a
database is selected the page redirects to Connect.

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
│ 3 statements · 2 rows · 6 ms                              │  ← status line
│ ┌───────────────────────────────────────────────────────┐ │
│ │ id                                                    │ │  ← the last
│ │ 1                                                     │ │     statement's rows
│ │ 2                                                     │ │
│ └───────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

- **SQL textarea** — the script. **Min / S / M / L / XL** set its height as on
  QueryView; **Min** collapses it, keeping the text, so the table gets the room.
- **▶ Run** (**Ctrl/⌘+Enter**) — runs the **statement under the cursor**, or
  the **selection** when there is one. Just past a `;` on the same line still
  counts as that statement; a blank line below belongs to the next one.
- **▶▶ Run all** (**Ctrl/⌘+Shift+Enter**) — runs the whole script.
- **Status line** — one line per run; the statements are already in the
  textbox, so it never repeats them (see below).
- **Results table** — the rows of the **last statement run**, when it returned
  any: the same grid as QueryView and the explorer. DDL, DML or a failure as
  the last statement means no table.
- **Open in QueryView** — enabled while that table shows: loads the last
  statement's SQL into [QueryView](./query.md) for paging, column pickers,
  saving and CSV, with a fresh sort and column selection. Nothing runs until
  you click Execute there.

## Statements

Statements are separated by `;`. The split skips semicolons inside `'…'`,
`"…"`, `` `…` ``, `$$…$$` bodies, `-- …` line comments and `/* … */` block
comments; blank statements are dropped. An unterminated quote keeps the rest of
the script in one statement, so the database reports the real syntax error.

A run opens **one connection** and runs its statements **in order** on it, so
`BEGIN; …; COMMIT;`, `SET` and temp tables carry across statements of the same
run but not from one Run to the next.

**An error stops the run.** Nothing after the failing statement is sent, and
nothing before it is rolled back — statements `1 … k-1` stay applied. Fix the
failing one, then put the cursor on the next and use **▶ Run** (or select from
it to the end). Wrap the script in `BEGIN; …; COMMIT;` yourself on a driver
that supports transactions if partial application is not acceptable.

## The status line

| Last statement run | Line |
| --- | --- |
| Returned rows | `N rows · T ms`; cut at **100 rows**: `first 100 rows, more exist · T ms` |
| No rows (DDL, DML) | the driver's own status — ClickHouse `OK`, Postgres's command tag (`INSERT 0 3`), DuckDB `OK` — `· T ms` |
| Failed | `Statement #k Failed - <the driver's error>` in red; the statement itself is **marked red in the textbox** until you click into it |

A script's line starts with `N statements ·` and `T` is the total.

The 100-row cap exists because the page has no pagination: a bare `SELECT *`
must not pull a whole table into the browser. Page with your own
`LIMIT`/`OFFSET`, or hand the statement to QueryView. Values arrive in the
same JSON shape as every other result
([Results & CSV](./query.md#results--csv)).

## Per driver

- **ClickHouse** — each statement is an HTTP **POST** (a GET is read-only on
  the ClickHouse HTTP interface, so writes would be refused) with
  `default_format=JSONCompact`. A statement with its own `FORMAT` clause is
  shown as text in the status line instead of rows.
- **Postgres** — each statement is prepared and executed on the run's
  connection; a statement with no result columns reports its command tag.
- **DuckDB** — the file is opened **read-write** for the run, while every other
  page opens it read-only. DuckDB refuses a second open of one file with a
  different mode in the same process, so the explorer and QueryView error on
  that file until the run finishes. A `:memory:` database is new on every run.

## Session

The textbox's text is session state — a reload brings it back — but the status
line and the table are not, like every other view ([session.md](./session.md));
a reload never re-runs a script. Switching database clears them and keeps the
text.

## API

`POST /api/db/execute` — see [api.md](./api.md).

## Related docs

- [query.md](./query.md) — QueryView: the paginated, saveable single query.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [session.md](./session.md) — what a session remembers.
