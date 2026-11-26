# Git sync — backup & restore

Dashboards can be backed up to a git repository (e.g.
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
for that case is in [docker.md](../docker.md#git-sync).

## Repository layout

```
dashboards/{name}/dashboard.html   # the HTML, verbatim
dashboards/{name}/queries.yaml     # {query_name: SQL or {connection, sql, database?}}
dashboards/{name}/meta.yaml        # params, only when declared
```

The folder is the dashboard's name, percent-encoded where needed; a `name`
key in `meta.yaml` is ignored. A dashboard needs `dashboard.html` and
`queries.yaml` (either may be empty): a dir missing one is a hand edit, so
**Restore** returns 404 naming the file and a sync skips it. A sync also
skips a folder the encoding would not write, such as `a%41` for `aA`, with a
warning in the server log.

`queries.yaml` holds each entry as written: a SQL string, or a
[federated](./dashboard.md#the-push_dashboard-mcp-tool) map, so an untouched
repo produces no diff. A folder mixing the two is refused with
`malformed dashboard file: every query and options_sql names a connection, or none does`.

Every QueryView on one repo, [viewer servers](./viewer_server.md)
included, must read this layout: one that expects the name in `meta.yaml`
skips these folders.

A name new to the workspace must fit that folder, with or without a remote:

- over 255 bytes once encoded, it is refused as too long;
- differing only by letter case from another dashboard's name, or from a
  folder the repo holds, it is refused: the two would share a folder on a
  case-insensitive disk.

## Merge-in

A sync fetches the repo and merges its head into the workspace. It runs:

- when a remote is saved (re-entering the same URL counts);
- on **Save**, **Rename**, **Delete**, **Restore**, and opening an entity's revision list;
- on **Sync** in the workspace panel (header dropdown → *Manage workspaces…*),
  to pick up what was committed elsewhere.

Opening or refreshing the app never syncs.

The merge only adds, never overwrites:

- in the repo, not here → **imported**, unless it was removed here since the
  last agreement and the repo's copy hasn't changed since;
- the same on both sides → nothing to do;
- different, and the repo's copy changed since this workspace last agreed with
  it → a **conflict**: the local copy is kept and the entity is listed under a
  ⚠ next to the workspace switcher until you **Save** (push yours) or
  **Restore** (take the repo's);
- different, but only because you edited it locally → just an uncommitted
  change, not a conflict.

A sync never removes a row, and ignores anything in the repo outside
`dashboards/`. "Last agreed" is the repo object id each entity had when it
was imported, committed, restored or found identical, kept with the conflict
list in `{data dir}/gitsync/{workspace id}.sync.json`.
Changing a workspace's remote or branch drops its clone and that file.

## Versioning

Git commits are the versions — each [user action](#committing) makes exactly one commit touching
one entity, so an entity's history is `git log -- <its path>`. Restore reads
files at a chosen commit (`git show`) and overwrites the local DB row; HEAD
never moves and history is append-only.

Each dashboard row records `commit_sha`: the last commit that touched its
folder and holds exactly the row's content. **Save**, **Rename**, **Restore**
and a merge-in import or match set it. It is `NULL` in a workspace without a
remote, and a YAML import clears it, since no commit holds that content.

## Committing

Only a user's action on the [dashboard page](./dashboard.md#the-page-dashboard)
commits; agent pushes, Import and Restore never do. In a workspace with a
remote, each is one commit and push:

| Action | Commit |
| --- | --- |
| **Save** | `store dashboard <name>`: the dashboard as saved |
| **Rename** | `rename dashboard <old> → <new>`: `git mv` of its folder |
| **Delete** | `delete dashboard <name>`: `git rm` of its folder |

The local change happens only once the push succeeds. An unreachable remote,
or a failed commit or push, leaves the workspace as it was and shows the error:
nothing is saved locally until the remote takes the commit. A push rejected because
another instance pushed first is retried from the new head, up to five times.
Rename and Delete of a dashboard the repo doesn't hold make no commit; a
Rename onto a name the repo already holds is refused. Without a remote, the
three only change the workspace.

## UI

<!-- req: restore-ui -->
**Restore**, next to the dashboard page's **Save**, opens the entity's
revision list (newest first, 10 at a time, scroll for more) and overwrites the
local copy with the picked revision after confirmation. It is disabled when
the active workspace has no remote configured.

<!-- req: not-in-git -->
With a remote, the dashboard picker marks a dashboard no commit holds
(`commit_sha` is `NULL`) as `<name> · not in git`. A row whose content
matches the repo but has no `commit_sha` recorded yet gets one on the next
[merge-in](#merge-in), e.g. **Sync**.

## API

- `GET /api/git/status?workspace=` → `{configured, conflicts}`
- `POST /api/git/sync` `{workspace?}` → `{ok, imported, conflicts}`
- `GET /api/git/history?kind=&name=&before=&limit=10&workspace=` → `{ok, revisions: [{sha, date, message}], has_more}`
- `POST /api/git/restore` `{kind, name, ref?, workspace?}` → `{ok, restored, sha, imported, conflicts}`
  `ref` is a sha from history or a branch name (read as `origin/<name>`); default: the remote branch head.

`kind` is `"dashboard"`;
`workspace` defaults to the fallback workspace (see [workspace.md](./workspace.md)). MCP tools `git_history` and
`git_restore` mirror the same surface, resolving the workspace from an
optional `session_id` (see [workspace.md](./workspace.md)).

## Related docs

- [workspace.md](./workspace.md) — workspaces: per-workspace remotes.
- [export-import.md](./export-import.md) — one-shot YAML export/import of the same entities, no git needed.
- [dashboard.md](./dashboard.md) — dashboards.
- [api.md](../architecture/api.md) — backend JSON API.
- [future.md](../future.md) — planned follow-ups to git sync.
