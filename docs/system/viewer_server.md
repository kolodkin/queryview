# Viewer server (display-only deployment)

`queryview-server` is a second way to run QueryView: a shared, display-only
server whose one page (`/`) shows the dashboards of a git repo on database
connections from a config file. It renders them as the app's
[dashboard page](dashboard.md) does. Viewers pick a connection and a
dashboard; they cannot edit, connect or run SQL of their own.
[viewer_server_docker.md](../viewer_server_docker.md) runs it,
[viewer_server_api.md](../architecture/viewer_server_api.md) lists its
endpoints. For how dashboards reach the repo see [gitsync.md](gitsync.md).

```
+-- queryview-server ------------------------------------+
| [connection v] [dashboard v]              [Snapshot]   |
| +- sandboxed frame (the dashboard HTML) -------------+ |
| | <qv-param>   chart   <qv-select-view query=sales>  | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

<!-- req: same-rendering -->
- **Same rendering:** [parameters](dashboard.md#dashboard-parameters),
  [widgets](dashboard.md#widgets) (paging, sorting, CSV) and
  [**Snapshot**](dashboard.md#snapshot) work as in the app.
  <!-- req: shareable -->
- **Shareable:** `?connection=<name>&name=<dashboard>` opens a dashboard on a
  connection. Without it the page reopens the browser's last pick (kept in its
  local storage), else the first connection.
- **A dashboard runs on the picked connection.** It names none, as in the app,
  so one written for another database fails with that database's error.

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

- `git.remote` takes the [workspace remote](gitsync.md) URL form, token
  included.
- A connection is a `name` and `type` plus that driver's
  [connection fields](connect.md#drivers). `database` is the one database it runs
  on, required for ClickHouse, Postgres and MySQL: there is no picker.
- A DuckDB connection whose `path` is a folder is refused: its SQL could read
  any file on the server, this config included.

## Sync

<!-- req: sync -->
The server shows the repo's latest commit: what a QueryView app saves to the
repo appears within `sync_interval`, with nothing to click.

- It fetches the branch on a timer and reads the dashboards at its head. It
  never merges, commits or pushes.
- A failed fetch is logged and the last good copy keeps serving.
- A dashboard whose files don't parse is skipped; the others still show.
- A folder is one dashboard, [named by the folder](gitsync.md#repository-layout):
  a copied folder shows as its own dashboard, and one with a non-standard
  name is skipped and logged.
- A page already open keeps what it loaded; a reload or a new pick shows the
  change.

## Security

- **No login.** Anyone who can reach the server sees every dashboard's data on
  every configured connection. Put a reverse proxy or your platform's
  single sign-on in front, and keep the port private otherwise.
  <!-- req: display-only -->
- **Display only by construction.** The server is a separate app: the routes
  that save, connect or run SQL, and the [MCP](mcp.md) endpoint, don't exist
  on it. The browser sends dashboard, query and connection names plus
  parameter values; the SQL never leaves the server.
- **Values are checked.** A parameter value the dashboard's options don't
  offer falls back to the default and never reaches the SQL. A `text`
  parameter is free input by design: what a viewer types reaches the SQL only
  as a quoted string, at most 10,000 characters.
- **The repo decides the SQL.** Whoever can push to it chooses what runs, so
  give each connection a read-only database login without file privileges
  (see [future.md](../future.md#run_sql-server-side-file-access)).

## Related docs

- [dashboard.md](dashboard.md) — what a dashboard is and how it renders.
- [gitsync.md](gitsync.md) — how dashboards reach the repo, and its URL form.
- [connect.md](connect.md) — drivers and their connection fields.
- [viewer_server_docker.md](../viewer_server_docker.md) — running the server.
- [viewer_server_api.md](../architecture/viewer_server_api.md) — its endpoints.
