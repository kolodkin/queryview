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

| Tool | What it does |
|---|---|
| `session_info` | The session's connection, database, workspace and tables |
| `run_sql` | Run read-only SQL; rows go to the agent |
| `run_script` | Run a `;`-separated script, writes allowed; results go to the agent |
| `push_query` | Open a query in the browser's QueryView |
| `push_script` | Fill the browser's Scripts editor, optionally run it |
| `push_dashboard` | Render a dashboard in the browser as a draft |
| `open_explorer` | Open the browser's Explorer on a database, or on one of its tables |
| `list_queries` / `list_dashboards` | List saved queries and dashboards |
| `list_connections` / `list_databases` | List connections and their databases |
| `add_connection` / `remove_connection` | Add or remove a session connection |
| `use_connection` / `select_database` | Switch the session's connection or database |
| `git_store` / `git_history` / `git_restore` | Back up, list and restore a query or dashboard via workspace git |

Tools act on a browser session. To target your tab, click the agent icon next
to the connection pill, enable **Allow remote control**, and give the agent the
session id it shows. [remote.md](./remote.md) has each tool's arguments.

## Related docs

- [remote.md](./remote.md) — arming a session and every MCP tool's arguments.
- [dashboard.md](./dashboard.md) — how agents author dashboards.
- [docker.md](./docker.md) — port mapping when running the container.
