# Future

Planned work, highest priority first. Each entry is a proposal, not yet
implemented — the spec lives here until it ships, then moves into the relevant
doc.

## A standing Agent session

Today the agent only gets a session id the user copies out of an armed tab.
Arming gates pushes only: `run_sql` and the other tools work on any session
row that has a connection. So a session that always exists would let the
agent start without the copying step, and let the user watch it.

- Fixed id `00000000000000000000000000000000`, created at startup if missing,
  labelled **Agent**. Never auto-resumed by a new tab, never deletable.
- The agent uses it unprompted: `add_connection` + `use_connection` for its
  own connections, or whatever saved connection the user put it on. The MCP
  tool docs name the id.
- The UI picks it from the session switcher like any session: sees what the
  agent is on, opens a saved connection for it, and arming it there enables
  pushes as today.
- [Locked](./connect.md#locked-connections) connections refuse it like any
  other session; nothing in the lock changes.
- It starts disconnected and stays on whatever the agent last used on it:
  the session row remembers its connection across restarts like any other,
  so nothing is picked on the agent's behalf.

Roughly: a constant and a startup upsert in `sessions.py`, two guards
(auto-resume, delete), a label, docstring lines in `mcp_server.py`, docs, and
two tests.

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
- [remote.md](./remote.md) — the MCP tools the Agent session would serve.
- [queryview.md](./queryview.md) — the Connect page and the app's pages.
- [query.md](./query.md) — running queries: pagination, predefined queries, CSV.
