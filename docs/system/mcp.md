# MCP server

QueryView serves an MCP server (Streamable HTTP) at `http://localhost:8000/mcp/`,
inside the same process — nothing extra to start. Register it once with your
agent:

```bash
claude mcp add --scope user --transport http queryview http://localhost:8000/mcp/
```

- **Match the port:** `--port 9000` or `docker run -p 127.0.0.1:9000:8000`
  means `http://localhost:9000/mcp/`.
- **Start QueryView first:** a client that finds nothing listening stays failed
  until you reconnect it.
- **Keep the trailing slash:** `/mcp` works too, but costs a redirect per call.
- **Localhost only:** `/mcp/` has no auth and can query every connection and
  rewrite workspace git state. Don't expose the port.

## Tabs

<!-- req: tabs -->
An agent works in browser tabs of its own, one per task, and leaves your
sessions alone unless you hand it an id. `new_tab(name)` creates a
[tab session](./session.md#tabs) and returns its `session_id` and `url`,
`<origin>/?session=<id>`. The agent opens the link in your browser (`open` on
macOS, `xdg-open` on Linux) or gives it to you; the tab lists as
**Agent › orders**, arms itself on load, and is gone once closed. The agent
connects it with `use_connection` or `add_connection`, then pushes into it as
into any session; a push made before the link is opened waits for it, a minute
at most, and every reply about a tab carries its `url`.

## Arming a session

<!-- req: arming -->
Remote control is **opt-in**, per browser session, and off by default. Once a
database is selected, an **agent icon** sits next to the connection status pill.
Click it and toggle **Allow remote control**. The popover then shows this
session's **id** and a copyable command, e.g.:

> Use the queryview mcp to connect to session "a1b2c3" (Session 1)

Turning the toggle off (or closing the tab) disarms the session immediately —
pushes to its id are then reported as not delivered.

Without a copied id the agent works in a [tab](#tabs) of its own.

## Agent skill

The server publishes one skill over the MCP Skills extension,
`skill://queryview/SKILL.md` ([source](../../backend/queryview/skills/queryview/SKILL.md)):
the default workflow for tabs, connections, SQL and dashboards.
Naming a tool overrides it.

## Tools

The tools an agent can call are listed in [mcp.md](../architecture/mcp.md#tools).

## Naming and saving

The agent drafts and edits; the user names and saves. No tool saves.

- **New work is unnamed.** The agent pushes a draft. The user names it at the
  prompt of the dashboard's **Save**, which refuses a name already taken.
- **The agent edits a saved dashboard by its name**, and only a saved one.
- **A push persists nothing.** The user's **Save** does.
- **No tool renames or deletes.** The store's names are the user's: **Rename**
  and **Delete** live on the dashboard page only. An agent asked to rename
  says so; pushing the same dashboard under a new name is not a rename.

## How it works

The SSE channel behind arming is described in [mcp.md](../architecture/mcp.md#how-it-works).

## Related docs

- [api.md](../architecture/api.md) — backend JSON API.
- [session.md](./session.md) — sessions and agent tabs.
- [dashboard.md](./dashboard.md) — how agents author dashboards.
- [query.md](./query.md) — querying: pagination, the results grid, CSV.
- [docker.md](../docker.md) — port mapping when running the container.
