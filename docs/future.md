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
[explorer.md](./explorer.md)); the `path` decides the mode. Today file mode has
no picker and lists only what `SHOW TABLES` returns.

## Dashboards after Studio

Left out when dashboards took over from the Studio page:

- **Rename and delete.** A saved dashboard can only be overwritten. Add
  **Rename** and a soft **Delete** / **Undelete** / **Purge**, with git sync
  following a deletion.
- **Draft survives a reload.** A **New query** draft and unsaved
  [SQL panel](./dashboard.md#the-sql-panel) edits live in the page: keep them
  in the [session](./session.md), as the Scripts text is.
- **Driver scope.** A dashboard's SQL is written for one driver, yet every
  dashboard lists for every connection. An optional driver on the dashboard
  would hide it from sessions on another.
- **More widgets.** Only `<qv-select-view>` and `<qv-param>` exist; a chip is
  the next candidate.
- **Widget detection.** A widget's query is found by scanning the HTML for a
  quoted `query="…"`, so a tag a script creates, or an unquoted attribute,
  also runs up front with the page's own queries.

## Deferred

Out of scope by design, not planned yet. Git sync assumes a single user syncs
each workspace; multi-user sync needs git pulling or a webhook first.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [connect.md](./connect.md) — connecting, storage.
- [gitsync.md](./gitsync.md) — git backup & restore, whose follow-ups live here.
- [workspace.md](./workspace.md) — workspaces and their git remotes.
- [session.md](./session.md) — sessions and what they remember.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — querying: pagination, the results grid, CSV.
