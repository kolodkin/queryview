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
for that case is in [docker.md](./docker.md#git-sync).

## Repository layout

```
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

**Restore**, next to the dashboard page's **Save**, opens the entity's
revision list (newest first, 10 at a time, scroll for more) and overwrites the
local copy with the picked revision after confirmation. It is disabled when
the active workspace has no remote configured.

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
- [api.md](./api.md) — backend JSON API.
- [future.md](./future.md) — planned follow-ups to git sync.
