# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## run_sql: server-side file access

An agent's [`run_sql`](./mcp.md#tools) runs read-only, but read-only only
blocks writes to tables. On MySQL, `SELECT … INTO OUTFILE` and `INTO DUMPFILE`
still write files on the database server, and `LOAD_FILE()` reads them, when
the login has the FILE privilege. `secure_file_priv` limits where, and an
existing file is never overwritten. Postgres's `COPY … TO '<file>'` likely
has the same gap for a superuser (untested).

- **Refuse in `run_sql`.** Reject `INTO OUTFILE` / `INTO DUMPFILE` (MySQL) and
  `COPY … TO` a file (Postgres), skipping comments and ignoring case. A
  text check can be dodged, so it backs up the next item.
- **Document the login.** [mcp.md](./mcp.md) and [connect.md](./connect.md)
  advise an agent connection to use a login without file privileges: no FILE
  on MySQL, no superuser or `pg_write_server_files` on Postgres.

## MySQL driver follow-ups

- **Scripts stop reading at the cap.** A script SELECT keeps 100 rows (see
  [scripts.md](./scripts.md#per-driver)), but the driver reads the rest of the
  result to free the connection, so `SELECT * FROM big_table` transfers the
  whole table. A `KILL QUERY` from a second connection would end it at the cap
  instead.
- **Server-side timeouts.** The **Query timeout** and `run_sql`'s limit end the
  request in QueryView, but MySQL keeps running the statement. Setting
  `max_execution_time` per session would stop it on the server too, as
  Postgres's `statement_timeout` does.
- **`#` comments in scripts.** The statement splitter knows `--` and `/* */`
  comments, not MySQL's `#`, so an apostrophe in `# don't …` merges the rest
  of the script into one statement, which then fails. `#` is an operator in
  Postgres, so the splitter needs it per driver, with its frontend mirror.

## DuckDB file mode: schema picker

A DuckDB connection whose `path` is a `.duckdb` file should navigate like
Postgres: the picker lists the file's schemas (`duckdb_schemas()`, `main`
first, internal ones hidden) as the "databases", and the explorer lists the
tables and views of the picked schema with the estimates the driver already
computes. Same driver and same picker as folder mode (see
[explorer.md](./explorer.md)); the `path` decides the mode. Today file mode has
no picker and lists only what `SHOW TABLES` returns.

## Dashboards

- **Unsaved edits survive a reload.** A **New query** draft is kept in the
  [session](./session.md); [SQL panel](./dashboard.md#the-sql-panel) edits to
  a saved dashboard are not, and are lost on leaving it.
- **Driver scope.** A dashboard's SQL is written for one driver, yet every
  dashboard lists for every connection. An optional driver on the dashboard
  would hide it from sessions on another.
- **Script-created widgets.** The widget bundle loads, and a widget's query is
  kept out of the up-front run, only when the tag is written in the HTML: one
  a script creates is not seen.
- **Snapshots for agents.** An agent building a report from one or more
  dashboards needs their [snapshots](./dashboard.md#snapshot) as files. The
  server would render them in a headless browser of its own (the same snapshot
  code, written to a file whose path the tool returns) so no user tab is in
  the loop and reports can be batched or scheduled. Open: a browser engine in
  the server image, and which connection a session with no user behind it
  runs on. Asking a user's armed tab for its snapshot was considered and
  dropped: the HTML is too large to return inline, and it needs that tab open.
- **Tabs that work in a snapshot.** A dashboard's own tabs switch by script,
  so a snapshot freezes on the tab that was open. A built-in `<qv-tabs>`
  that switches without script would work in the file; authors can get the
  same today with radio inputs and `:checked`.

## Git sync

- **Local vs git status.** Show, per dashboard on the dashboard page, how the
  local copy stands against the repo: in sync, local changes, behind (the
  repo's copy changed since they last agreed) or conflict. The
  [merge-in](./gitsync.md#merge-in) already tracks this per entity.
- **No Save while behind.** Today a Save pushes the local copy over a newer
  one in the repo. Refuse Save when the dashboard is behind, until the user
  takes the repo's copy with **Restore**.

## Deferred

Out of scope by design, not planned yet. Git sync assumes a single user syncs
each workspace; multi-user sync needs git pulling or a webhook first.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [connect.md](./connect.md) — connecting, storage.
- [mcp.md](./mcp.md) — the agent tools, `run_sql` among them.
- [scripts.md](./scripts.md) — running scripts, per driver.
- [gitsync.md](./gitsync.md) — git backup & restore, whose follow-ups live here.
- [workspace.md](./workspace.md) — workspaces and their git remotes.
- [session.md](./session.md) — sessions and what they remember.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — querying: pagination, the results grid, CSV.
