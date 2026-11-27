# Architecture overview

The components of QueryView and the contracts between them: [api.md](./api.md)
(endpoints), [mcp.md](./mcp.md) (agent tools),
[storage.md](./storage.md) (the data directory) and
[viewer_server_api.md](./viewer_server_api.md) (the viewer server). How
components work together is in the design pages:
[sessions.md](../designs/sessions.md) (session rows and claims),
[dashboards.md](../designs/dashboards.md) (dashboard query runs) and
[mcp.md](../designs/mcp.md) (the agent channel).

## Components

```
+-----+  /api  +-------------+------>+---------------+
| SPA |------->| FastAPI app |       | session store |
+-----+        +-------------+       +---------------+
   ^            |      |   |
   |            |      |   +-------->+---------+
   |            |      |             | drivers |
   |            |      v             +---------+
   |            |   +------------+
   |            |   | MCP server |  /mcp/
   |            |   +------------+
   |            |      |
+---------+     |      |
| remote  |<----+------+
| channel |
+---------+
FastAPI app --> git sync;  viewer server runs as its own process
```

## Contracts

Stated on the page that owns them:

- Where all state lives: [storage.md](./storage.md#storage--migrations).
- Which session a request acts on: [api.md](./api.md).
- Arming as the gate to the agent channel: [mcp.md](./mcp.md#security).
- What a locked connection refuses: [mcp.md](./mcp.md#security).
- How a dashboard's HTML is isolated: [below](#isolation--security).
- The redirect onto the MCP mount: [api.md](./api.md).

<!-- req: driver-contract -->
Every registered driver answers the shared operations (parse, config round trip, tables, fields, rows, text, databases) with the same typed results or an error.

<!-- req: static-spa -->
The backend serves the built SPA's files, falls back to `index.html` for client-side routes, and answers `404` for a missing file.

## Isolation & security

The HTML renders in
`<iframe sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" srcdoc=…>`
**without** `allow-same-origin`, giving it an opaque origin: it can run JS and load CDN
assets but cannot read the app's storage or call `/api/*` as the session (it
has neither the session id nor any credential). A link the page opens with
`target="_blank"` lands in a normal tab. The page cannot print or download;
[Snapshot](../user_guide/dashboard.md#snapshot) is the way out; its file runs no script because the
host puts a script-blocking policy ahead of the frame's text. Data reaches the page only through the
injected `window.queries` and the [widget](../user_guide/dashboard.md#widgets) replies; the
`window.queries` JSON has `<` escaped so result data containing `</script>` can't break out
of the prologue.

Persisted dashboards are shared via SQLite and keyed by name within their
[workspace](../user_guide/workspace.md). The agent HTML
is untrusted and confined to the sandbox; it never sees connection secrets or
the session id.

## Related docs

- [api.md](./api.md) — the HTTP endpoint reference.
- [sessions.md](../designs/sessions.md) — how a session is stored.
- [dashboards.md](../designs/dashboards.md) — how a dashboard's queries run.
- [mcp.md](./mcp.md) — MCP tools and the channel behind arming.
- [storage.md](./storage.md) — the data directory and migrations.
- [viewer_server_api.md](./viewer_server_api.md) — the viewer server's endpoints.
