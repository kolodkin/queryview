# Git sync — backup & restore

A workspace with a git remote (e.g. GitHub) keeps its predefined queries
(`/studio`) and dashboards (`/dashboard`) in the repo: every save is a commit,
and any past revision can be restored, per entity. Connections are never
written to the repo (their config is encrypted credentials). For one-off
copies without git, see [export-import.md](./export-import.md).

## Configuration

Each workspace (see [workspace.md](./workspace.md)) carries its own remote URL
and branch, managed in the UI/API and encrypted at rest. There is no
environment-variable fallback: without a remote, git sync is disabled. New
workspaces start on branch `main`.

Clones live at `{data dir}/gitsync/{workspace id}/`; the layout inside each
clone is unchanged by workspaces.

## Git sync mode

A workspace is in git sync mode while it has a remote. Then:

- **Badge.** A **git sync** badge sits next to the Studio and Dashboard
  headings. Without a remote the badge is absent and saves stay local.
- **Save commits.** **Save** (query or dashboard) writes the row, then commits
  and pushes that one entity: `store {kind} {name}`. There is no separate
  Commit button.
- **Rename commits.** One commit, `rename query {type}/{new}`, adds the new
  file and removes the old one.
- **Delete commits.** **Delete** removes the query for good — there is no
  trash or undelete — and commits its file's removal,
  `delete query {type}/{name}`. To bring one back, pick **+ New name…** with
  its name, **Restore** a revision from before the delete, then **Save**.
- **All or nothing.** A change and its commit are one unit: the touched rows
  are snapshotted, changed, committed and pushed. If git fails (offline,
  rejected push) the rows are put back as they were and the request fails
  with `502` (`not saved: …`), shown as the page's error.
- **Push races.** A push rejected because another instance pushed first is
  retried from the new remote head, up to 5 attempts in all.
- **Agent pushes stay drafts.** A `push_query` or `push_dashboard` from an
  agent renders in the browser but commits nothing until the user saves it.
- **Not committed:** YAML [import](./export-import.md) writes rows without a
  commit; they show as *No git sync* (below) until saved.
- **History is kept.** Deleted files stay in git history; rewriting it is up
  to you, outside QueryView. Other instances learn of a delete only as a
  missing file, which sync never acts on: they keep their copy.

## No git sync

Each saved query and dashboard row carries `git_sha`, the commit holding it as
it is: set by a commit (or a save that finds nothing to change) and by a sync
that imports the row or finds it identical; cleared by any DB write. Rows
without one — from a YAML import, or saved before the workspace had a remote —
are listed under `unsynced` by `GET /api/git/status` and shown under the ⚠
next to the workspace switcher as **No git sync**, until a **Save** or
**Sync** settles them. Adding a remote runs a sync, which clears every row the
repo already holds as is; the rest need a **Save**.

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
for that case is in [docker.md](./docker.md#git-sync).

## Repository layout

```
queries/{type}/{name}.yaml         # query, cell_view, order_by, fields
dashboards/{name}/meta.yaml        # name, params (when declared)
dashboards/{name}/dashboard.html   # the HTML, verbatim
dashboards/{name}/queries.yaml     # {query_name: SQL}
```

File names are percent-encoded where needed; the canonical name lives inside
the YAML. A dashboard needs all three files (the HTML and queries may be
empty): a dir missing one is a hand edit, so **Restore** returns 404 naming
the file and a sync skips it.

## Merge-in

A sync fetches the repo and merges its head into the workspace. It runs:

- when a remote is saved (re-entering the same URL counts);
- on every save, **Restore**, and opening an entity's revision list;
- on **Sync** in the workspace panel (header dropdown → *Manage workspaces…*),
  to pick up what was committed elsewhere.

Opening or refreshing the app never syncs.

The merge only adds, never overwrites:

- in the repo, not here → **imported**, unless it was renamed or deleted here
  since the last agreement and the repo's copy hasn't changed since;
- the same on both sides → nothing to do;
- different, and the repo's copy changed since this workspace last agreed with
  it → a **conflict**: the local copy is kept and the entity is listed under a
  ⚠ next to the workspace switcher until you **Save** (push yours) or
  **Restore** (take the repo's);
- different, but only because you edited it locally → just an uncommitted
  change, not a conflict.

A sync never removes a row. "Last agreed" is the repo object id each entity
had when it was imported, committed, restored or found identical, kept with the conflict
list in `{data dir}/gitsync/{workspace id}.sync.json`.
Changing a workspace's remote or branch drops its clone and that file.

## Versioning

Git commits are the versions — each change makes exactly one commit touching one
entity, so an entity's history is `git log -- <its path>`. Restore reads
files at a chosen commit (`git show`) and overwrites the local DB row; HEAD
never moves and history is append-only.

## UI

Next to each entity's **Save** button (query panel and dashboard page),
**Restore** opens the entity's revision list (newest first, 10 at a time,
scroll for more) and overwrites the local copy with the picked revision after
confirmation. It is disabled when the active workspace has no remote.

## API

- `GET /api/git/status?workspace=` → `{configured, conflicts, unsynced}`
- `POST /api/git/sync` `{workspace?}` → `{ok, imported, conflicts}`
- `POST /api/git/store` `{kind, name, conn_type?, message?, workspace?}` → `{ok, committed, sha, message, imported, conflicts}`
- `GET /api/git/history?kind=&name=&conn_type=&before=&limit=10&workspace=` → `{ok, revisions: [{sha, date, message}], has_more}`
- `POST /api/git/restore` `{kind, name, conn_type?, ref?, workspace?}` → `{ok, restored, sha, imported, conflicts}`
  `ref` is a sha from history or a branch name (read as `origin/<name>`); default: the remote branch head.

`kind` is `"query"` or `"dashboard"`; `conn_type` is required for queries;
`workspace` defaults to the fallback workspace (see [workspace.md](./workspace.md)). MCP tools `git_store`, `git_history`,
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](./workspace.md)).

## Related docs

- [workspace.md](./workspace.md) — workspaces: per-workspace remotes.
- [export-import.md](./export-import.md) — one-shot YAML export/import of the same entities, no git needed.
- [query.md](./query.md) — predefined queries.
- [dashboard.md](./dashboard.md) — dashboards.
- [docker.md](./docker.md) — git credentials in a container.
- [api.md](./api.md) — backend JSON API.
