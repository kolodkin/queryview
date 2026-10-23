# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## Authentication

Today QueryView has no auth: whoever reaches the port can attach any session,
open any saved connection and query it, and the agent session's id is a known
constant. That is why the README limits it to **dev write credentials and
read-only credentials elsewhere**. Lifting that limit means:

- **A login for the browser.** A single shared secret first (`QV_TOKEN` env,
  entered once, kept in a cookie), then real users if ever needed. Every
  `/api` and `/mcp` request without it is 401; the SSE stream included.
- **A token for the agent.** The MCP client sends it as a header; the agent
  session becomes reachable only with it, so its fixed id stops mattering.
- **Scopes on connections.** A connection carries `read_only: true` and the
  backend enforces it (reject `run_script` and non-read statements), so a
  writing credential can be saved yet only written through with intent.
- **An audit trail.** Who ran what, when, on which connection; the agent and
  the user already carry `created_by`/`connection_by`, so this is one table.
- **Session ownership.** With users, a session belongs to one; the dropdown
  lists only yours and the agent session.

Until all of it ships, the credential rule above is the boundary, not the code.

## Git sync follow-ups

A small improvement noted in the git-sync final review, not blocking:

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
