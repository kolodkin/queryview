# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## Workspace-scoped connections

Connections are global — any workspace (see [workspace.md](./workspace.md))
can use any connection. If workspaces come to represent genuinely separate
environments or teams, scope connections per workspace: each workspace sees
only its own, and restore requires the connection to exist in that workspace.
Deferred because it multiplies setup for the common single-team case.

## Git sync follow-ups

Small improvements noted in the git-sync final review, none blocking:

- The dashboard readers (`restore` and the merge's `_read_repo_entity`)
  treat only a missing `meta.yaml` at a ref as 404; a missing
  `dashboard.html`/`queries.yaml` silently defaults. Unreachable through
  QueryView, which writes all three files in one commit, but a hand-edited
  repo reaches it — remove or document the asymmetry.
- No push retry: under the single per-instance lock a store never self-races,
  but a second QueryView instance pushing between our fetch and push rejects
  the store. Fine for v1's single-instance scope; add one retry if that
  changes.

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
