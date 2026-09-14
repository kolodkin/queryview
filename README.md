# QueryView

A local SQL workbench for **ClickHouse**, **Postgres** and **DuckDB** — and a
place to let an AI agent do the querying for you.

Everything happens at one prompt: type `connect prod` to open a database,
`query` to run SQL, `explorer` to click through tables, `dashboard` to open a
saved dashboard. Saved queries and dashboards live in workspaces that can back
themselves up to a git remote. A built-in MCP server lets an agent run
read-only queries, push a query or a whole dashboard into your open browser tab,
and snapshot your work to git.

QueryView is a **single-user tool that runs on your own machine**. It has no
login and assumes it is reachable only from localhost — don't expose its port.

## Quick start

Run the released package — API + bundled SPA on http://localhost:8000:

```bash
uvx queryview
```

`--port` (or the `PORT` env var) picks the listen port, default 8000:
`uvx queryview --port 9000`.

Or run the container image — every release publishes
`ghcr.io/kolodkin/queryview` to GHCR for `linux/amd64` and `linux/arm64`, tagged
`vX.Y.Z` and (for non-pre-releases) `latest`:

```bash
docker run -p 8000:8000 ghcr.io/kolodkin/queryview:latest
```

To serve on a different host port, remap it (the container keeps listening on
8000, which its healthcheck probes): `docker run -p 9000:8000 ...`. QueryView
expects to be reached from localhost only, so prefer binding the published port
to loopback: `docker run -p 127.0.0.1:8000:8000 ...`.

The command above keeps its state inside the container, so connections and
workspaces are lost when the container is removed. See
[Run with Docker](#run-with-docker) for a persistent setup.

## What you can do

Open http://localhost:8000 and type into the prompt:

| Command | What happens |
|---|---|
| `new clickhouse` / `new postgres` / `new duckdb` | Create a connection — host, port and credentials, or a file path for DuckDB. Passwords are encrypted at rest. |
| `connect <name>` | Open a saved connection and pick a database — that opens the explorer. The last one reconnects automatically next time. |
| `query` | Run SQL: paginated results, column picker, save/load reusable queries, download the page as CSV. |
| `explorer` | Browse tables without typing SQL — a sidebar of tables with row/size estimates, click to page through rows. |
| `dashboard [name]` | Open a saved dashboard: an HTML layout that re-runs its queries against live data every time you open it. |

Beyond the prompt:

- **Workspaces** group your saved queries and dashboards, and each can sync to
  its own git remote for backup, history and restore —
  [workspace.md](docs/workspace.md), [gitsync.md](docs/gitsync.md).
- **YAML export/import** moves a single query, a dashboard, or a whole
  workspace between instances with no git involved —
  [export-import.md](docs/export-import.md).
- **MCP** lets an agent query your databases and author dashboards — see
  [below](#mcp-server).

## Run with Docker

The image runs as the non-root user `queryview` (UID 1000) and sets
`DATA_DIR=/var/lib/queryview`, so every piece of state lives directly under that
one directory:

| Path | Contents |
|---|---|
| `/var/lib/queryview/db.sqlite` | SQLite store: connections, workspaces, queries, dashboards |
| `/var/lib/queryview/encryption.key` | Key that encrypts stored connection passwords |
| `/var/lib/queryview/gitsync/` | Local clones used by workspace git sync |

Mount a volume at `/var/lib/queryview` and all three persist across container
restarts, removals and upgrades.

### Persisting it

```bash
mkdir -p ~/.queryview
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v ~/.queryview:/var/lib/queryview \
  ghcr.io/kolodkin/queryview:latest
```

Create the directory first so Docker doesn't create it owned by root. The
container runs as UID 1000, the first user on most Linux distributions; if
`id -u` prints something else, add `--user "$(id -u):$(id -g)"` so the
container writes the files as you.

`~/.queryview` is also where a local `uvx queryview` keeps its state, so the
container and a local run share one database, key and set of clones with no
extra setup. Don't run both at once: each would serve the same SQLite file.

To let Docker own the location instead, swap the path for a named volume,
`-v queryview-data:/var/lib/queryview`. Docker seeds it from the image, so
ownership is already right and there is nothing to create up front, but the
state no longer lines up with a local run.

### Git sync

The image ships `git`, so workspace git sync works in the container, and its
clones live under `/var/lib/queryview/gitsync/`, which the mount above already
covers. Give the workspace an HTTPS remote carrying a scoped, expiring token —
[docs/gitsync.md](docs/gitsync.md) has the URL form and what becomes of the
credential.

SSH also works, but nothing in the container can answer a prompt: the key must
be passphrase-free and `known_hosts` must already list the host. Mount one
dedicated deploy key, not your whole `.ssh`, readable by UID 1000:

```bash
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v ~/.queryview:/var/lib/queryview \
  -v ~/.ssh/queryview_deploy:/home/queryview/.ssh/id_ed25519:ro \
  -v ~/.ssh/known_hosts:/home/queryview/.ssh/known_hosts:ro \
  ghcr.io/kolodkin/queryview:latest
```

## MCP server

The backend mounts a FastMCP server (Streamable HTTP) at
`http://localhost:8000/mcp/`. There is nothing extra to start — it runs inside
the server process (`uvx queryview`, `npm run dev`, ...). Registering the client
is a separate, one-time step on the machine running the agent: an HTTP MCP
server can't install itself into someone else's client.

```bash
claude mcp add --transport http queryview http://localhost:8000/mcp/
```

Three things to get right:

- **Prefer the trailing slash.** The mount serves `/mcp/`. The slashless
  `/mcp` also works — it 307-redirects — but registering the canonical path
  skips a round trip on every call.
- **Match the port.** The URL must point at the port QueryView actually
  listens on — `--port 9000` means `http://localhost:9000/mcp/`, and
  `docker run -p 9000:8000` means the *host* port, `9000`, not the container's
  `8000`.
- **Start QueryView first.** The client dials this URL when it starts; if
  nothing is listening it reports a connection error and stays failed until you
  reconnect it.

QueryView is a **local, single-user tool**: it assumes it is reachable only from
localhost. `/mcp/` is unauthenticated, and its tools can query every configured
connection and rewrite workspace git state, so don't publish the port. Bind the
container to loopback — `docker run -p 127.0.0.1:8000:8000 ...` — since a plain
`-p 8000:8000` listens on all interfaces.

Tools: `run_query` (read-only SQL, rows returned to the agent), `push_query`
and `push_dashboard` (fill a live browser session), `list_queries` /
`list_dashboards`, and `git_store` / `git_history` / `git_restore` (workspace
git backups). The push tools target an **armed** browser session: enable
"Allow remote control" from the agent icon next to the connection pill and use
the session id it shows. See [docs/remote.md](docs/remote.md) for the full
protocol.

## Where your data lives

All state lives in one data directory, `~/.queryview` on every OS, relocated
with `DATA_DIR`. Inside are the SQLite store `db.sqlite`, the local
password-encryption key `encryption.key`, and the workspace git-sync clones
under `gitsync/`. Back that directory up — or give each workspace a git remote
and let [git sync](docs/gitsync.md) do it.

## Documentation

- [queryview.md](docs/queryview.md) — the single-prompt page.
- [connect.md](docs/connect.md) — connections, drivers, sessions, storage.
- [query.md](docs/query.md) — the query panel: pagination, predefined queries, CSV.
- [explorer.md](docs/explorer.md) — the table navigator.
- [dashboard.md](docs/dashboard.md) — dashboards and how agents author them.
- [workspace.md](docs/workspace.md) — workspaces.
- [gitsync.md](docs/gitsync.md) — git backup, history and restore.
- [export-import.md](docs/export-import.md) — YAML export and import.
- [remote.md](docs/remote.md) — the remote-control protocol behind the MCP push tools.
- [api.md](docs/api.md) — the full HTTP endpoint reference.

## Contributing

Development setup, tests and the release process are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).
