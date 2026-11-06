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

## Sandbox DuckDB folder queries

A DuckDB folder connection must keep external file access on to read its own
data files, and DuckDB's `allowed_directories` does not cover `read_text`,
`read_blob`, or `glob`, so SQL on such a connection can read a file outside the
folder, including `encryption.key` (see
[security.md](./security.md#duckdb)). File and in-memory connections are
already fully locked; only folder mode has the gap, and only an untrusted SQL
author reaches it — the agent is barred from file drivers, so it needs a user's
open folder tab.

Two ways to close it:

- **Subprocess isolation (the real boundary).** Run each folder query in a
  short-lived child under a Linux sandbox (`bwrap`/`unshare` mount namespace,
  or Landlock) that exposes only the connection's folder — read-only for
  queries, read-write for the Scripts path. Rows cross back as Arrow or JSON.
  The driver already opens and closes a connection per query, so there is no
  session state to carry. Costs: per-query spawn and serialization overhead,
  and the boundary is Linux-only (the container image has it; a local macOS or
  Windows run does not).
- **In-driver reader allowlist (portable, weaker).** In folder mode, reject
  `read_text`/`read_blob`/`glob` and absolute or `..` paths before running, or
  permit only the readers folder mode itself emits. No OS dependency and little
  code, but exposed to SQL-parser edge cases.

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
- [security.md](./security.md) — credential-leak protections and the DuckDB residual.
- [connect.md](./connect.md) — connecting, storage.
- [gitsync.md](./gitsync.md) — git backup & restore, whose follow-ups live here.
- [workspace.md](./workspace.md) — workspaces and their git remotes.
- [session.md](./session.md) — sessions and what they remember.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — running queries: pagination, predefined queries, CSV.
