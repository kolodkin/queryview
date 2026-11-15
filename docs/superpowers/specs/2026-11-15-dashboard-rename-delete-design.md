# Dashboard rename & delete — design

## Intent

A saved dashboard can only be overwritten. Add **Rename** and **Delete**, and
make git sync follow user actions directly: in a git-synced workspace, a
user's Save, Rename or Delete is itself the commit. No Undelete or Purge —
git history already holds every committed version.

## Behaviour

Without a remote, all three only change the DB. With one, each is one commit
and push:

| Action | DB | Git (when synced) |
|--------|----|-------------------|
| **Save** | upsert | commit the current content, `store dashboard <name>` |
| **Rename** | change the row's name | `git mv` the folder, `rename dashboard <old> → <new>` |
| **Delete** | remove the row | `git rm` the folder, `delete dashboard <name>` |

- **Transaction.** The DB change is committed only after the push succeeds.
  On a failed commit or push, the DB is rolled back, the clone is reset to
  the remote head, and the error is shown. A push rejected by a concurrent
  push is retried once, as today.
- **Git moves only what is there.** Rename or Delete of a dashboard the repo
  doesn't hold makes no commit.
- **Sync state follows.** Rename moves the `agreed` entry and any conflict to
  the new name; Delete drops them.
- **Rename to a taken name** is refused (409).
- **Only users commit.** Agent pushes (`push_dashboard`), Import and Restore
  never commit.

## UI

- Remove the **Commit** button; **Restore** stays.
- Add **Rename** (prompt for the new name, like Save) and **Delete**
  (confirm) next to Save; disabled for an unsaved New query draft.
- After Rename the URL moves to `?name=<new>`; after Delete the page empties.

## Calls made (veto any)

- No MCP rename/delete tools.
- MCP `git_store` and `POST /api/git/store` are removed: they let a commit
  happen outside a user's Save. `gitsync.store` stays as the Save path.
- Docs: `dashboard.md`, `gitsync.md` (states the "only user actions commit"
  rule), `api.md`, `mcp.md`; the entry leaves `future.md`.

## Approaches considered

- **Commit on the action (chosen).** Every user action keeps repo and DB in
  step; one commit per action.
- **Separate Commit, pending removals** — needs tracking state and extra UI
  for things no longer on screen.
- **Local-only rename/delete** — the repo keeps stale copies that a fresh
  workspace re-imports.

## Tests

Backend: rename/delete with and without a remote, rollback on push failure,
name clash, Save commits. E2E: the Rename and Delete buttons.
