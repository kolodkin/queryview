# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## DuckDB file mode: schema picker

A DuckDB connection whose `path` is a `.duckdb` file should navigate like
Postgres: the picker lists the file's schemas (`duckdb_schemas()`, `main`
first, internal ones hidden) as the "databases", and the explorer lists the
tables and views of the picked schema with the estimates the driver already
computes. Same driver and same picker as folder mode (see
[explorer.md](./user_guide/explorer.md)); the `path` decides the mode. Today file mode has
no picker and lists only what `SHOW TABLES` returns.

## Dashboards

- **Unsaved edits survive a reload.** A **New query** draft is kept in the
  [session](./user_guide/session.md); [SQL panel](./user_guide/dashboard.md#the-sql-panel) edits to
  a saved dashboard are not, and are lost on leaving it.
- **Driver scope.** A dashboard's SQL is written for one driver, yet every
  dashboard lists for every connection. An optional driver on the dashboard
  would hide it from sessions on another.
- **Script-created widgets.** The widget bundle loads, and a widget's query is
  kept out of the up-front run, only when the tag is written in the HTML: one
  a script creates is not seen.
- **Snapshots for agents.** An agent building a report from one or more
  dashboards needs their [snapshots](./user_guide/dashboard.md#snapshot) as files. The
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
  [merge-in](./user_guide/gitsync.md#merge-in) already tracks this per entity.
- **No Save while behind.** Today a Save pushes the local copy over a newer
  one in the repo. Refuse Save when the dashboard is behind, until the user
  takes the repo's copy with **Restore**.

## Deferred

Out of scope by design, not planned yet. Git sync assumes a single user syncs
each workspace; multi-user sync needs git pulling or a webhook first.

## Related docs

- [api.md](./architecture/api.md) — backend JSON API.
- [connect.md](./user_guide/connect.md) — connecting, storage.
- [gitsync.md](./user_guide/gitsync.md) — git backup & restore, whose follow-ups live here.
- [workspace.md](./user_guide/workspace.md) — workspaces and their git remotes.
- [session.md](./user_guide/session.md) — sessions and what they remember.
- [queryview.md](./user_guide/queryview.md) — the Connect page and the app's pages.
- [query.md](./user_guide/query.md) — querying: pagination, the results grid, CSV.
