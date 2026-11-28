# Scripts — the SQL scratchpad

The **Scripts** page (`/scripts`) is a flat SQL textbox: whatever you type runs
**as written** against the session's selected database — `CREATE`, `INSERT`,
`ALTER`, `DROP` included — with no pagination wrapper, no saved names, no
column pickers. A dashboard's [**New query**](./dashboard.md#the-page-dashboard)
wraps a single `SELECT` for paging, saving and presentation; the MCP `run_sql` tool stays read-only (see
[Agent pushes](#agent-pushes) for the script tools). Before a
database is selected the page redirects to Connect.

## Run a script

<!-- req: run-script -->
You can run a multi-statement script, writes included, that stops at the
first error.

- A `;`-separated script runs as written, `CREATE` and `INSERT` included, and
  shows the last statement's rows.
- A failing statement stops the run: you are told which one failed and
  why, and the statements after it do not run.

## What's on the page

```
+------------------------------------------------------------+
|                           Scripts                          |
|                                    [Min] [S] [M] [L] [XL]  |
| +--------------------------------------------------------+ |
| | CREATE TABLE t (id INTEGER);                           | |  <- SQL textarea
| | INSERT INTO t VALUES (1), (2);                         | |
| | SELECT * FROM t|                                       | |
| +--------------------------------------------------------+ |
| [> Run] [>> Run all] [Open in Dashboard]                   |
| 3 statements - 2 rows - 6 ms                               |  <- status line
| +--------------------------------------------------------+ |
| | id                                                     | |  <- the last
| | 1                                                      | |     statement's rows
| | 2                                                      | |
| +--------------------------------------------------------+ |
+------------------------------------------------------------+
```

<!-- req: textarea-sizes -->
- **SQL textarea** — the script. **Min / S / M / L / XL** set its height;
  **Min** collapses it, keeping the text, so the table gets the room.
  <!-- req: run-current -->
- **▶ Run** (**Ctrl/⌘+Enter**) — runs the **statement under the cursor**, or
  the **selection** when there is one. Just past a `;` on the same line still
  counts as that statement; a blank line below belongs to the next one.
  <!-- req: run-all -->
- **▶▶ Run all** (**Ctrl/⌘+Shift+Enter**) — runs the whole script.
- **Status line** — one line per run; the statements are already in the
  textbox, so it never repeats them (see below).
- **Results table** — the rows of the **last statement run**, when it returned
  any: the same grid as the dashboard widget and the explorer. DDL, DML or a failure as
  the last statement means no table.
- **Open in Dashboard** — enabled while that table shows: opens the last
  statement's SQL as a dashboard [**New query**](./dashboard.md#the-page-dashboard)
  draft and runs it there, for paging, column pickers, saving and CSV.

## Statements

<!-- req: statements -->
Statements are separated by `;`. The split skips semicolons inside `'…'` (a
backslash escapes the next character, as in ClickHouse and Postgres `E''`
strings), `"…"`, `` `…` ``, `$$…$$` and `$tag$…$tag$` bodies, `-- …` line
comments and `/* … */` block comments; blank statements are dropped. On
MySQL the split reads the script as MySQL does: `# …` is a line comment, `--`
starts one only before a space, `/*! … */` is code, `$` belongs to names and
`"…"` takes backslash escapes. An unterminated quote keeps the rest of the script in one statement, so
the database reports the real syntax error.

<!-- req: one-connection -->
A run opens **one connection** (one server session on ClickHouse) and runs
its statements **in order** on it, so `BEGIN; …; COMMIT;`, `SET` and temporary
tables carry across statements of the same run but not from one Run to the
next. A statement may run for up to **10 minutes** before it is given up on,
unlike the 5-second limit of the other pages.

<!-- req: error-stops -->
**An error stops the run.** Nothing after the failing statement is sent, and
nothing before it is rolled back — statements `1 … k-1` stay applied. Fix the
failing one, then put the cursor on the next and use **▶ Run** (or select from
it to the end). Wrap the script in `BEGIN; …; COMMIT;` yourself on a driver
that supports transactions if partial application is not acceptable.

## The status line

| Last statement run | Line |
| --- | --- |
| Returned rows | `N rows · T ms`; cut at **100 rows**: `first 100 rows, more exist · T ms` |
| No rows (DDL, DML) | the driver's own status — ClickHouse `OK`, Postgres's command tag (`INSERT 0 3`), DuckDB and SQLite `OK` — `· T ms` |
| Failed | `Statement #k Failed - <the driver's error>` in red; the statement itself is **marked red in the textbox** until you click into it |

A script's line starts with `N statements ·` and `T` is the total.

<!-- req: row-cap -->
The 100-row cap exists because the page has no pagination: a bare `SELECT *`
must not pull a whole table into the browser. Page with your own
`LIMIT`/`OFFSET`, or open the statement in a dashboard. Values arrive in the
same JSON shape as every other result
([Results & CSV](./query.md#results--csv)).

## Per driver

- **ClickHouse** — each statement is an HTTP **POST** (a GET is read-only on
  the ClickHouse HTTP interface, so writes would be refused) with
  `default_format=JSONCompact`. A statement with its own `FORMAT` clause is
  shown as text in the status line instead of rows.
- **Postgres** — each statement is prepared and executed on the run's
  connection; rows are read through a cursor up to the cap, and a statement
  with no result columns reports its command tag.
<!-- req: mysql-script -->
- **MySQL** — statements run in autocommit on the run's connection. Rows
  stream up to the cap, then a `KILL QUERY` from a second connection stops the
  rest, so a `SELECT *` on a big table transfers only what is shown. Only a read
  (`SELECT`, `SHOW`, …) outside a transaction is stopped; anything else is
  read to its end: a `CALL`'s procedure may have more to do, and a
  `FOR UPDATE` in a `BEGIN` locks only the rows it reaches. A
  statement with no result reports `OK, N rows affected`. Past the 10 minutes,
  only a `SELECT` is ended on the server too
  ([Query timeout](./queryview.md#query-timeout)).
- **DuckDB** — the file is opened **read-write** for the run, while every other
  page opens it read-only. DuckDB refuses a second open of one file with a
  different mode in the same process, so the explorer and dashboards error on
  that file until the run finishes. A `:memory:` database is new on every run.
- **SQLite** — the run opens the file read-write in autocommit mode; every
  other page opens it read-only. Each statement persists as it runs, and a
  script's own `BEGIN`/`COMMIT` works.

## Session

<!-- req: session-text -->
The textbox's text is session state — a reload brings it back — but the status
line and the table are not, like every other view ([session.md](./session.md));
a reload never re-runs a script. Switching database clears them and keeps the
text.

## Agent pushes

<!-- req: agent-push -->
MCP `run_script` runs a script as Run all does and returns the results to the
agent; `push_script` replaces the text (saved like an edit) and, with `run`,
runs it here, usually in a [tab](./mcp.md#let-the-agent-open-its-own-tabs) of the agent's own. Focus
in the page holds the
[edit lock](./query.md#co-edit--edit-lock), so a push is refused with
`blocked, user editing` while you type. See [mcp.md](./mcp.md).

## File writes

On a DuckDB or SQLite connection a script, the agent's included, can write
any file QueryView's process can: DuckDB's `COPY ... TO` writes any path, and
SQLite's `ATTACH` opens or creates any SQLite file, QueryView's own
`db.sqlite` among them. `run_sql` refuses both.

```sql
ATTACH '/home/user/elsewhere.db' AS x;
CREATE TABLE x.customers_copy AS SELECT * FROM customers
```

Keep an agent off file connections you wouldn't hand it the filesystem for.

<!-- req: server-files -->
On MySQL and Postgres the files are the database server's, and the login's
privileges decide. MySQL's `SELECT … INTO OUTFILE` / `INTO DUMPFILE` write one
and `LOAD_FILE()` reads one, given the FILE privilege; Postgres's `COPY … TO`
writes one, or runs a command with `TO PROGRAM`, for a superuser, even in a
read-only transaction. `run_sql` refuses `INTO OUTFILE`, `INTO DUMPFILE`,
`COPY` and `DO` (a block can run a `COPY`), quoted text and comments aside.
That check reads the text, so it can be dodged, and scripts get no check at
all: give an agent's connection a login without file privileges — no FILE on
MySQL; no superuser, `pg_read_server_files`, `pg_write_server_files` or
`pg_execute_server_program` on Postgres.

## Related docs

- [query.md](./query.md) — querying: pagination, the results grid, CSV.
- [dashboard.md](./dashboard.md) — dashboards and **New query**.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [session.md](./session.md) — what a session remembers.
