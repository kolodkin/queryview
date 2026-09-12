# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## Git sync: keep the credential out of the clone

A workspace's remote URL is encrypted at rest, but `git clone` and
`git remote add` write it verbatim into
`{data dir}/gitsync/{workspace id}/.git/config`. A token embedded in an HTTPS
remote therefore sits in plaintext next to its own encrypted copy: the
encryption protects the SQLite file but not the data directory, and any backup
of that directory carries a working credential. This matters more now that
tokens are the documented way to reach a remote from the container.

Either keep the credential out of the stored URL and supply it per invocation
(a credential helper, or `http.extraHeader` set for the single command), or
hold it in its own encrypted field and assemble the URL at call time. Decide
before recommending tokens more widely.

## Git sync: fail fast instead of prompting

`_git` inherits the server's stdin, sets no timeout, and leaves git's terminal
prompts enabled, so any operation that asks for input — an SSH key passphrase,
an unknown host key, HTTPS credentials — can block a request indefinitely
rather than returning an error. Pass a null stdin, set `GIT_TERMINAL_PROMPT=0`
and SSH `BatchMode=yes`, and bound the wait so these surface as a normal
`GitSyncError`. Small and self-contained; worth folding into the next change
that touches git sync.

## Edit / delete predefined queries

Predefined queries can currently be saved (which upserts by name) and loaded,
but not renamed or removed from the UI. Add a way to rename and delete saved
queries — likely a `DELETE /api/predefined-queries` endpoint and edit/delete
controls in the query panel's predefined-query selector.

## Workspace-scoped connections

Connections are global — any workspace (see [workspace.md](./workspace.md))
can use any connection. If workspaces come to represent genuinely separate
environments or teams, scope connections per workspace: each workspace sees
only its own, and restore requires the connection to exist in that workspace.
Deferred because it multiplies setup for the common single-team case.

## Git sync follow-ups

Small improvements noted in the git-sync final review, none blocking:

- `restore` treats only a missing `meta.yaml` at a ref as 404; missing
  `dashboard.html`/`queries.yaml` silently default (unreachable today because
  store writes all three files in one commit — remove or document the
  asymmetry).
- Restoring by branch *name* resolves the local branch, which fetch doesn't
  fast-forward, so it can read a stale tree; sha/HEAD paths (the documented
  usage) are correct. Resolve named refs against `origin/` or note it in
  [gitsync.md](./gitsync.md).
- No push retry: under the single per-instance lock a store never self-races,
  but a second QueryView instance pushing between our fetch and push rejects
  the store. Fine for v1's single-instance scope; add one retry if that
  changes.

## Related docs

- [api.md](./api.md) — backend JSON API.
- [connect.md](./connect.md) — connecting, storage, sessions.
- [queryview.md](./queryview.md) — the single-prompt page concept.
- [query.md](./query.md) — running queries: pagination, predefined queries, CSV.
