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

## Deferred

Out of scope by design, not planned yet. Git sync assumes a single user syncs
each workspace; multi-user sync needs git pulling or a webhook first.

- **Content check when a sync follows a deletion.** The merge reads a query,
  then soft-deletes it in a second DB session without re-checking its
  content. A save landing in between is soft-deleted instead of becoming a
  conflict (it stays recoverable with **Undelete**). With one user this needs
  their own save to race their own sync. Multi-user sync should make that
  write a compare-and-set on what the merge read, and report a conflict on a
  mismatch.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [connect.md](./connect.md) — connecting, storage.
- [gitsync.md](./gitsync.md) — git backup & restore, whose follow-ups live here.
- [workspace.md](./workspace.md) — workspaces and their git remotes.
- [session.md](./session.md) — sessions and what they remember.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — running queries: pagination, predefined queries, CSV.
