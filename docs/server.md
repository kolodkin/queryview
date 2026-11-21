# Viewer server (display-only deployment)

`queryview-server` is a second way to run QueryView: a shared, display-only
server whose one page (`/`) shows the dashboards of a git repo on database
connections from a config file. It renders them as the app's
[dashboard page](./dashboard.md) does. Viewers pick a connection and a
dashboard; they cannot edit, connect or run SQL of their own. For the app
itself in a container see [docker.md](./docker.md); for how dashboards reach
the repo see [gitsync.md](./gitsync.md).

```
+-- queryview-server ------------------------------------+
| [connection v] [dashboard v]              [Snapshot]   |
| +- sandboxed frame (the dashboard HTML) -------------+ |
| | <qv-param>   chart   <qv-select-view query=sales>  | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

- **Same rendering:** [parameters](./dashboard.md#dashboard-parameters),
  [widgets](./dashboard.md#widgets) (paging, sorting, CSV) and
  [**Snapshot**](./dashboard.md#snapshot) work as in the app.
- **Shareable:** `?connection=<name>&name=<dashboard>` opens a dashboard on a
  connection. Without it the page reopens the browser's last pick (kept in its
  local storage), else the first connection.
- **A dashboard runs on the picked connection.** It names none, as in the app,
  so one written for another database fails with that database's error.

## Running it

The command ships in the same package and image as the app:

```bash
docker run -d --name queryview-server \
  -p 127.0.0.1:8000:8000 \
  -v ./server.yaml:/etc/queryview/server.yaml:ro \
  ghcr.io/kolodkin/queryview:latest queryview-server
```

- **Config:** `QV_CONFIG` names the file, default `/etc/queryview/server.yaml`.
  Mount it as a secret: it holds the passwords and the git token.
- **Port:** `--port`, else `PORT`, else 8000.
- **State:** none to keep. `DATA_DIR` holds only the repo's clone, made afresh
  at every start, so replicas need no shared disk.
- **Startup fails loudly:** a malformed config, an invalid connection or a
  failed first clone exits non-zero, naming the connection or the git error.

## The config file

```yaml
git:
  remote: https://x-access-token:<token>@github.com/example/dashboards.git
  branch: main          # default
  sync_interval: 60     # seconds between fetches, default
connections:
  - name: sales
    type: postgres
    host: db.example.internal
    port: 5432
    username: viewer
    password: <password>
    database: sales_reporting
  - name: local
    type: sqlite
    path: /data/reporting.sqlite
```

- `git.remote` takes the [workspace remote](./gitsync.md) URL form, token
  included.
- A connection is a `name` and `type` plus that driver's
  [connection fields](./connect.md#drivers). `database` is the one database it runs
  on, required for ClickHouse, Postgres and MySQL: there is no picker.
- A DuckDB connection whose `path` is a folder is refused: its SQL could read
  any file on the server, this config included.

## Sync

The server shows the repo's latest commit: what a QueryView app saves to the
repo appears within `sync_interval`, with nothing to click.

- It fetches the branch on a timer and reads the dashboards at its head. It
  never merges, commits or pushes.
- A failed fetch is logged and the last good copy keeps serving.
- A dashboard whose files don't parse is skipped; the others still show.
- A page already open keeps what it loaded; a reload or a new pick shows the
  change.

## Security

- **No login.** Anyone who can reach the server sees every dashboard's data on
  every configured connection. Put a reverse proxy or your platform's
  single sign-on in front, and keep the port private otherwise.
- **Display only by construction.** The server is a separate app: the routes
  that save, connect or run SQL, and the [MCP](./mcp.md) endpoint, don't exist
  on it. The browser sends dashboard, query and connection names plus
  parameter values; the SQL never leaves the server.
- **Values are checked.** A parameter value the dashboard's options don't
  offer falls back to the default and never reaches the SQL. A `text`
  parameter is free input by design: what a viewer types reaches the SQL only
  as a quoted string, at most 10,000 characters.
- **The repo decides the SQL.** Whoever can push to it chooses what runs, so
  give each connection a read-only database login without file privileges
  (see [future.md](./future.md#run_sql-server-side-file-access)).

## API

Listed in [api.md](./api.md#viewer-server): `/api/connections`,
`/api/dashboards`, `/api/run`, `/api/query`, `/api/describe` and
`/api/health`.

## Related docs

- [dashboard.md](./dashboard.md) — what a dashboard is and how it renders.
- [gitsync.md](./gitsync.md) — how dashboards reach the repo, and its URL form.
- [connect.md](./connect.md) — drivers and their connection fields.
- [docker.md](./docker.md) — the container image.
- [api.md](./api.md) — the endpoint reference.
