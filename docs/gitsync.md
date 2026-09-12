# Git sync — backup & restore

Predefined queries and dashboards can be backed up to a git repository (e.g.
GitHub) and restored from any past revision, per entity. Connections are never
written to the repo (their config is encrypted credentials).

## Configuration

Each workspace (see [workspace.md](./workspace.md)) carries its own remote URL
and branch, managed in the UI/API and encrypted at rest. There is no
environment-variable fallback: a workspace without a remote has git sync
disabled until one is set. New workspaces start on branch `main`.

Clones live at `{data dir}/gitsync/{workspace id}/`; the repository layout inside each
clone is unchanged by workspaces.

## Credentials

A remote URL may embed a credential (`https://x-access-token:<token>@host/...`).
The row is encrypted at rest, but git would otherwise copy the URL verbatim into
the clone's `.git/config`, leaving the credential in plaintext beside its own
encrypted copy. So the credential is split off before any URL reaches git: the
clone records the credential-free URL, and each network call receives the
credential through its environment, keeping it out of the repo and out of our
argv. Only `http(s)` userinfo is treated this way — the `git@` in
`git@host:path` names an SSH login, not a secret, and is left alone.

Git never runs interactively: stdin is closed, terminal prompts are disabled and
SSH runs in batch mode, so a missing credential, an SSH key passphrase or an
unknown host key fails immediately instead of blocking a request. Each
invocation is also capped at two minutes.

## Repository layout

```
queries/{type}/{name}.yaml         # query, cell_view, order_by, fields
dashboards/{name}/meta.yaml        # name, connection
dashboards/{name}/dashboard.html   # the HTML, verbatim
dashboards/{name}/queries.yaml     # {query_name: SQL}
```

File names are percent-encoded where needed; the canonical name lives inside
the YAML.

## Versioning

Git commits are the versions — each Commit makes exactly one commit touching
one entity, so an entity's history is `git log -- <its path>`. Restore reads
files at a chosen commit (`git show`) and overwrites the local DB row; HEAD
never moves and history is append-only.

## UI

Next to each entity's existing **Save** button (query panel and dashboard
page): **Commit** pushes the saved DB state to the remote; **Restore** opens
the entity's revision list (newest first, 10 at a time, scroll for more) and
overwrites the local copy with the picked revision after confirmation. Both
are disabled when the active workspace has no remote configured.

## API

- `GET /api/git/status?workspace=` → `{configured}`
- `POST /api/git/store` `{kind, name, conn_type?, message?, workspace?}` → `{ok, committed, sha, message}`
- `GET /api/git/history?kind=&name=&conn_type=&before=&limit=10&workspace=` → `{ok, revisions: [{sha, date, message}], has_more}`
- `POST /api/git/restore` `{kind, name, conn_type?, ref?, workspace?}` → `{ok, restored, sha}`

`kind` is `"query"` or `"dashboard"`; `conn_type` is required for queries;
`workspace` defaults to `default`. MCP tools `git_store`, `git_history`,
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](./workspace.md)).

## Related docs

- [workspace.md](./workspace.md) — workspaces: per-workspace remotes.
- [export-import.md](./export-import.md) — one-shot YAML export/import of the same entities, no git needed.
- [query.md](./query.md) — predefined queries.
- [dashboard.md](./dashboard.md) — dashboards.
- [api.md](./api.md) — backend JSON API.
