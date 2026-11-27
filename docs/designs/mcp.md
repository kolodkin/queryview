# The agent channel

How an MCP push reaches the user's tab. The tools and what they refuse are in
[architecture/mcp.md](../architecture/mcp.md).

## How the channel works

When armed, the browser opens an SSE stream
(`GET /api/remote/events?session=<id>`); the backend registers an in-memory
channel **keyed by that session's id** (see [session.md](../user_guide/session.md)).
The push tools enqueue onto that channel; the SSE stream delivers the payload
and the page renders it.

Because the channel is named after a session, the agent's session-scoped tools
read that session's database and workspace straight from its row — the browser
reports nothing (see [workspace.md](../user_guide/workspace.md)).

<!-- req: tab-queue -->
A push to a [tab](../user_guide/mcp.md#tabs) nobody has opened yet lands in a channel `new_tab`
opened in advance, which answers `queued for the tab`; arming takes that
channel over with its pushes queued. One whose tab never comes is dropped
after a minute.

State is in-memory and per-process (like the active-connection session map): a
backend restart drops channels; the browser reconnects while armed and gets a
new id.

## Related docs

- [architecture/mcp.md](../architecture/mcp.md) — the MCP tools, and arming as the gate.
- [mcp.md](../user_guide/mcp.md) — connecting an agent and arming a session.
- [session.md](../user_guide/session.md) — sessions and agent tabs.
