# Architecture overview

The components of QueryView and the contracts between them. Mechanisms live in
the neighbouring pages: [api.md](./api.md) (endpoints), [sessions.md](./sessions.md)
(session rows), [mcp.md](./mcp.md) (agent tools and channels),
[storage.md](./storage.md) (the data directory) and
[viewer_server_api.md](./viewer_server_api.md) (the viewer server).

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
- Arming as the gate to the agent channel: [mcp.md](./mcp.md#how-it-works).

<!-- req: architecture/overview/driver-contract -->
Every registered driver answers the shared operations (parse, config round trip, tables, fields, rows, text, databases) with the same typed results or an error.

<!-- req: architecture/overview/mcp-mount -->
A slashless `/mcp` redirects to `/mcp/` for every MCP method (`POST`, `GET`, `DELETE`), and `/mcp/` itself is not redirected. The mount is in [api.md](./api.md).

<!-- req: architecture/overview/locked-refuses-both -->
A locked connection refuses the MCP tools that query, push or switch it, and refuses a REST call that lacks the unlock token. See [connect.md](../system/connect.md#locked-connections).

<!-- req: architecture/overview/static-spa -->
The backend serves the built SPA's files, falls back to `index.html` for client-side routes, and answers `404` for a missing file.

## Related docs

- [api.md](./api.md) — the HTTP endpoint reference.
- [sessions.md](./sessions.md) — how a session is stored.
- [mcp.md](./mcp.md) — MCP tools and the channel behind arming.
- [storage.md](./storage.md) — the data directory and migrations.
- [viewer_server_api.md](./viewer_server_api.md) — the viewer server's endpoints.
