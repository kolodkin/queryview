# Architecture overview

The components of QueryView and the contracts between them. Mechanisms live in
the neighbouring pages: [api.md](./api.md) (endpoints), [sessions.md](./sessions.md)
(session rows), [mcp.md](./mcp.md) (agent tools and channels),
[storage.md](./storage.md) (the data directory) and
[viewer_server_api.md](./viewer_server_api.md) (the viewer server).

# Components

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

# Contracts

<!-- req: architecture/overview/session-scoped-api -->
A data request names its session in the `X-QV-Session` header; without a session it answers `409`. A session-only connection is visible to its own session alone, and the session's stored `ui` settings and database reach the driver. See [sessions.md](./sessions.md).

<!-- req: architecture/overview/driver-contract -->
Every registered driver answers the shared operations (parse, config round trip, tables, fields, rows, text, databases) with the same typed results or an error.

<!-- req: architecture/overview/mcp-mount -->
The MCP server is mounted at `/mcp/` in the same app; a slashless `/mcp` redirects there for every MCP method.

<!-- req: architecture/overview/remote-channel -->
An agent push reaches the tab through the channel keyed by that session's id, and is refused once the tab disarms the session. See [mcp.md](./mcp.md#how-it-works).

<!-- req: architecture/overview/locked-refuses-both -->
A locked connection refuses the MCP tools that query, push or switch it, and refuses a REST call that lacks the unlock token. See [connect.md](../system/connect.md#locked-connections).

<!-- req: architecture/overview/data-dir -->
All state (the SQLite store, the encryption key, the git-sync clones) lives under `DATA_DIR`, which defaults to `~/.queryview`. See [storage.md](./storage.md).

<!-- req: architecture/overview/static-spa -->
The backend serves the built SPA's files, falls back to `index.html` for client-side routes, and answers `404` for a missing file.

## Related docs

- [api.md](./api.md) — the HTTP endpoint reference.
- [sessions.md](./sessions.md) — how a session is stored.
- [mcp.md](./mcp.md) — MCP tools and the channel behind arming.
- [storage.md](./storage.md) — the data directory and migrations.
- [viewer_server_api.md](./viewer_server_api.md) — the viewer server's endpoints.
