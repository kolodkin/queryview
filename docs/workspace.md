# Workspaces

Predefined queries and dashboards belong to a **workspace**; each workspace
git-syncs to its own remote (see [gitsync.md](./gitsync.md)). Entity names are
unique per workspace, so two workspaces can each have a "daily revenue"
dashboard. Connections are global — any workspace can use any connection.

A `default` workspace is seeded by migration, with no remote and on branch
`main`. It is an ordinary row, renamable like any other. The **fallback**
workspace — used for an omitted `workspace` parameter and for new sessions —
is the oldest one, found by id, never by the name `default`. Renaming a
workspace moves the sessions on it along; deleting one moves them to the
fallback, and the last workspace can't be deleted.

## Configuration

Workspace settings live in the database, not env vars. The remote URL may
embed a token, so it is encrypted at rest (same AES-GCM key as connection
configs). The API returns it only with the credential stripped
(`https://host/org/repo.git`, or an SSH URL as is), so the token itself is
write-only. A workspace
without a remote is a pure namespace: its git controls are disabled.

Deleting a workspace requires it to be empty (409 otherwise); the git remote
keeps its history either way.

## API

- `GET /api/workspaces` → `{workspaces: [{name, branch, configured, remote}]}`
- `POST /api/workspaces` `{name, remote?, branch?}`
- `PATCH /api/workspaces/{name}` `{name?, remote?, branch?}` — a null `remote`
  clears it; an absent key leaves it unchanged
- `DELETE /api/workspaces/{name}`

Scoped endpoints (predefined queries, dashboards, `/api/git/*`) accept an
optional `workspace` name, defaulting to the fallback workspace.

## UI

The header shows a workspace switcher (dropdown + manage panel for
create/rename/remote/branch/delete). The active workspace is session state
(see [session.md](./session.md)); switching reloads the query and dashboard
lists.

## MCP

MCP is workspace-unaware: no workspace parameter, no workspace tools. The
armed browser session reports its active workspace (alongside the database);
`list_queries`, `list_dashboards`, and the `git_*` tools take an optional
`session_id` and resolve the workspace from it, else the fallback. The human picks the
workspace; the agent works inside the session it was invited into. Workspace
CRUD stays API/UI-only because it is admin configuration involving secrets.

## Related docs

- [gitsync.md](./gitsync.md) — backup & restore mechanics.
- [query.md](./query.md) — predefined queries.
- [dashboard.md](./dashboard.md) — dashboards.
- [api.md](./api.md) — backend JSON API.
