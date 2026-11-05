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

## Tools

The agent can run read-only SQL (`run_sql`) or a script with writes
(`run_script`), push a query, script or dashboard into your open tab, list saved
queries and dashboards, and store, list and restore workspace git snapshots.
Tools that target a browser tab need it armed: click the agent icon next to the
connection pill, enable **Allow remote control**, and give the agent the session
id it shows. [remote.md](./remote.md) has the full tool reference.

## Related docs

- [remote.md](./remote.md) — arming a session and every MCP tool's arguments.
- [dashboard.md](./dashboard.md) — how agents author dashboards.
- [docker.md](./docker.md) — port mapping when running the container.
