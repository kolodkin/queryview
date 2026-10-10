# Git sync — backup & restore

Predefined queries and dashboards can be backed up to a git repository (e.g.
GitHub) and restored from any past revision, per entity. Connections are never
written to the repo (their config is encrypted credentials).

## Configuration

Each workspace (see [workspace.md](./workspace.md)) carries its own remote URL
and branch, managed in the UI/API and encrypted at rest. There is no
environment-variable fallback: without a remote, git sync is disabled. New
workspaces start on branch `main`.

Clones live at `{data dir}/gitsync/{workspace id}/`; the layout inside each
clone is unchanged by workspaces.

## Credentials

A remote URL may embed a credential (`https://x-access-token:<token>@host/...`).
Git would copy it verbatim into the clone's `.git/config`, so it is split off
before any URL reaches git: the clone records the credential-free URL, and each
network call gets the credential through its environment — out of both the repo
and our argv. Only `http(s)` userinfo counts; the `git@` in `git@host:path` is
an SSH login, not a secret.

Git never runs interactively: stdin is closed, prompts are disabled, SSH runs in
batch mode, and each invocation is capped at two minutes. A missing credential,
a key passphrase or an unknown host fails instead of blocking a request — which
is why a container wants a token rather than a key it cannot unlock. Mounting
for that case is in the README's [Run with Docker](../README.md#run-with-docker).

## Repository layout

```
queries/{type}/{name}.yaml         # query, cell_view, order_by, fields
dashboards/{name}/meta.yaml        # name, params (when declared)
dashboards/{name}/dashboard.html   # the HTML, verbatim
dashboards/{name}/queries.yaml     # {query_name: SQL}
```

File names are percent-encoded where needed; the canonical name lives inside
the YAML.

## Merge-in

A sync fetches the repo and merges its head into the workspace. It runs:

- when a remote is saved (re-entering the same URL counts);
- on **Commit**, **Restore**, and opening an entity's revision list;
- on **Sync** in the workspace panel (header dropdown → *Manage workspaces…*),
  to pick up what was committed elsewhere.

Opening or refreshing the app never syncs.

The merge only adds, never overwrites:

- in the repo, not here → **imported**, unless it was deleted or renamed here
  since the last agreement and the repo's copy hasn't changed since (a local
  change, like an edit); a repo copy changed elsewhere is imported again;
- the same on both sides → nothing to do;
- different, and the repo's copy changed since this workspace last agreed with
  it → a **conflict**: the local copy is kept and the entity is listed under a
  ⚠ next to the workspace switcher until you **Commit** (push yours) or
  **Restore** (take the repo's);
- different, but only because you edited it locally → just an uncommitted
  change, not a conflict.

Nothing is ever deleted by a sync, and deleting or renaming locally never
removes the repo's copy: it stays as a backup that **Restore** can bring back.
"Last agreed" is the repo object id each entity had when it was imported,
committed, restored or found identical, kept with the conflict list in
`{data dir}/gitsync/{workspace id}.sync.json`.
Changing a workspace's remote or branch drops its clone and that file.

## Versioning

Git commits are the versions — each Commit makes exactly one commit touching
one entity, so an entity's history is `git log -- <its path>`. Restore reads
files at a chosen commit (`git show`) and overwrites the local DB row; HEAD
never moves and history is append-only.

## UI

Next to each entity's **Save** button (query panel and dashboard page; absent
in an [autosave](./workspace.md#autosave) workspace, which saves on update):
**Commit** pushes the saved DB state to the remote; **Restore** opens
the entity's revision list (newest first, 10 at a time, scroll for more) and
overwrites the local copy with the picked revision after confirmation. Both
are disabled when the active workspace has no remote configured.

## API

- `GET /api/git/status?workspace=` → `{configured, conflicts}`
- `POST /api/git/sync` `{workspace?}` → `{ok, imported, conflicts}`
- `POST /api/git/store` `{kind, name, conn_type?, message?, workspace?}` → `{ok, committed, sha, message, imported, conflicts}`
- `GET /api/git/history?kind=&name=&conn_type=&before=&limit=10&workspace=` → `{ok, revisions: [{sha, date, message}], has_more}`
- `POST /api/git/restore` `{kind, name, conn_type?, ref?, workspace?}` → `{ok, restored, sha, imported, conflicts}`

`kind` is `"query"` or `"dashboard"`; `conn_type` is required for queries;
`workspace` defaults to the fallback workspace (see [workspace.md](./workspace.md)). MCP tools `git_store`, `git_history`,
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](./workspace.md)).

## Related docs

- [workspace.md](./workspace.md) — workspaces: per-workspace remotes.
- [export-import.md](./export-import.md) — one-shot YAML export/import of the same entities, no git needed.
- [query.md](./query.md) — predefined queries.
- [dashboard.md](./dashboard.md) — dashboards.
- [api.md](./api.md) — backend JSON API.
