# Viewer server: display-only deployment

## Intent

Run QueryView as a shared, display-only server. It shows the dashboards of the
git repo a local QueryView [syncs](../../gitsync.md) to, on database
connections given in a mounted config file, rendered as the app's
[dashboard page](../../dashboard.md) renders them. Viewers pick a connection
and a dashboard; they cannot edit anything or run SQL of their own.

## Goals

- A second entrypoint, `queryview-server`, in the same wheel and Docker image.
- The server holds the SQL: the browser sends names and parameter values only.
- One implementation of parameter substitution, in Python, used by the app and
  the viewer server.
- Always the latest commit: what a local QueryView pushes to the repo shows
  on the server within the sync interval, with nobody clicking anything.
- Stateless: no SQLite, sessions or encryption key. A restart re-clones.

## Non-goals

- Login. Access control is a reverse proxy or SSO in front (see
  [Security](#security)).
- A webhook endpoint (see [Approaches](#approaches)), several repos,
  workspaces, or a database picker.
- Pushing a change into a page that is already open: it shows on the next
  load or pick.
- A dashboard naming its connection (`meta.yaml` is unchanged).
- An agent tool that runs a dashboard with values. The Python function makes
  it a thin wrapper later; `future.md` gets a line.
- Caching resolved options between requests.
- `${VAR}` references inside the config file, or env vars as a second way to
  configure. The file is the one secret to mount.

## Anti-goals

- A viewer reaching data the dashboards do not expose: SQL text from the
  browser, or an `identifier` value outside the param's options.
- The app's behaviour changing for its users in phase 1.
- Substitution rules living in both TypeScript and Python.

## Approaches

**Where the viewer lives**

1. Flags in `main.py` switching 40 routes off. One app, but every new route
   must remember the flag.
2. **A new FastAPI app at `backend/queryview/server/`**, defining only viewer
   routes. Routes that don't exist can't be called. **Picked.**

**Who holds the SQL**

1. The browser substitutes and posts SQL, as the app does. Smallest, but
   "display only" is then a UI property.
2. **The server substitutes.** Truly display-only; costs a Python port of
   `frontend/src/core/dashboard/params.ts`. **Picked**, and the app moves to
   the same Python code so the rules have one home.

**Which connection a dashboard runs on**

1. **The viewer picks, the URL carries it.** No repo format change.
   **Picked.**
2. `meta.yaml` names it. No choice for viewers, but dashboards stop being
   portable and the app must round-trip the field.
3. A mapping file in the repo. Portable, but a second thing to keep in step.

**How the server stays current**

1. **Polling: `git fetch` on a timer.** Up to one interval behind (60 seconds
   by default). Nothing inbound, so it works behind a firewall, and it is the
   only moving part. **Picked.**
2. A GitHub webhook that triggers the fetch. Seconds behind, but GitHub must
   reach the server, and it adds an endpoint with a shared secret to verify.
   It would sit on top of polling, which stays as the fallback for a missed
   delivery, so it can be added later without changing anything here.

## Phase 1: substitution in Python (the app)

Lands first, on its own, proven by the existing test suites.

### `backend/queryview/dashboard_params.py`

A port of `params.ts` with the same rules and the same error messages:
placeholder syntax and casts, literal and identifier quoting per dialect,
dimension and text kinds, `MAX_TEXT_PARAM`, dependency order with cycle
detection, `default: none`, and held-back queries.

- Pure: no session, request or driver import. The caller passes the dialect
  (`ident_quote`, `backslash_escapes`) and an async runner for `options_sql`.
- Three entry points: resolve the selectors (options and chosen values) for
  given values; substitute one SQL for resolved values; apply to a map of
  queries, leaving out any still waiting on a choice.
- `params.test.ts` cases for the ported functions are rewritten as pytest and
  are the contract.

### API

The three endpoints gain optional `params` (the dashboard's declaration) and
`values`. Without them they behave as today, so Explorer and Scripts are
untouched.

| Endpoint | Today | With `params` and `values` |
| --- | --- | --- |
| `POST /api/runqueries` | `{queries}` of final SQL | `queries` are templates. The server resolves the selectors, substitutes, skips queries waiting on a choice, and adds `params: [{name, kind, options, value}]` to the reply. |
| `POST /api/db/query` | `{query, limit, offset, order_by, format}` | `query` is a template, substituted with `values` as given (no option resolution). |
| `POST /api/db/describe` | `{query}` | As `/api/db/query`. |

- A bad value (unknown cast, quote character in an identifier, no value
  chosen) is a 400 with the message the browser throws today. A widget query
  waiting on a choice replies `Waiting for a parameter choice.`
- The dialect comes from the session's driver.
- A text param the page leaves out of `set-params` keeps what was typed: the
  frontend fills it in from its last resolved params before posting.

### Frontend

- `DashboardView.tsx` posts templates, declaration and values at its four
  substitution sites (load, `set-params`, **Execute**, the widget host) and
  takes the resolved params from the reply.
- `params.ts` keeps the types, `parseDashboardParams` and
  `parseParamsRequest`. Quoting, substitution, ordering, option resolution and
  their tests are deleted, as is the `identQuote` / `backslashEscapes` plumbing
  if nothing else reads it.

## Phase 2: the viewer server

### Configuration

One YAML file, mounted into the container (a Kubernetes Secret, a Docker
secret, a bind mount). `QV_CONFIG` names its path, default
`/etc/queryview/server.yaml`.

```yaml
git:
  remote: https://<token>@github.com/example/dashboards.git
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
```

- `git.remote` takes the [workspace remote](../../gitsync.md) URL form.
- A connection is a `name` and `type` plus the fields that driver's Connect
  form posts (its `parse_config`). `database` is required where the driver has
  a picker; it is the one database the connection runs on.
- `PORT` and `DATA_DIR` stay env vars, as in the app. `DATA_DIR` holds only
  the clone, in a directory of its own.

Startup validates every connection with its driver's `parse_config` and does
the first clone. Either failing exits non-zero, naming the entry or the git
error and never echoing a config or the token.

A DuckDB connection whose `path` is a folder is refused at startup: its SQL
can read any local file, the config file (every password and the git token)
included. SQLite and DuckDB file mode already block other files.

### Sync

- Reuses `gitsync`'s clone, fetch, tree listing and read-at-ref code. Nothing
  is merged, committed or pushed.
- A background task fetches every interval. When the branch head moves, the
  dashboards are re-read into memory and served from there.
- A failed fetch is logged and the last good copy keeps serving.

### API

No session header. Every reply is JSON; errors are `{ok: false, message}`.

| Endpoint | Body | Reply |
| --- | --- | --- |
| `GET /api/health` | | `{status}` |
| `GET /api/connections` | | `[{name, type}]`, never a config |
| `GET /api/dashboards` | | `[{name}]` |
| `GET /api/dashboards/{name}` | | `{name, html, queries: [<names>]}`, never SQL or `options_sql` |
| `POST /api/run` | `{connection, dashboard, queries: [<names>], values}` | `{ok, results, params}` |
| `POST /api/query` | `{connection, dashboard, query, values, limit, offset, order_by, format}` | as the app's `/api/db/query` |
| `POST /api/describe` | `{connection, dashboard, query, values}` | `{ok, fields}` |

- `queries` in `/api/run` lets the page leave out the queries its widgets
  fetch themselves, as the app does.
- Every run resolves the selectors first, on all three POST endpoints. A
  value the options don't offer falls back as in the app (the first option,
  or none with `default: none`) and never reaches the SQL. That costs the
  `options_sql` queries again on each widget page; acceptable for now (see
  non-goals).
- `order_by` names follow the identifier rule params use: no quote character,
  and no backslash where the dialect escapes with it. Enforced in the shared
  `ORDER BY` builder, so the app gets it too.
- The SQL is not a secret, only unsendable: driver errors pass through as in
  the app, so an author can debug from the page.
- Unknown connection, dashboard or query name is a 404.

### The page

```
+-- queryview-server ------------------------------------+
| [connection v] [dashboard v]              [Snapshot]   |
| +- sandboxed frame (the dashboard HTML) -------------+ |
| | <qv-param>   chart   <qv-select-view query=sales>  | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

- A second Vite HTML entry with its code in `frontend/src/viewer/`, importing
  `src/core` only. The server serves it at `/`, with the widget bundle.
- Params, widgets (paging, sorting, CSV) and **Snapshot** work as in the app.
- `?connection=<name>&name=<dashboard>` opens a dashboard on a connection.
  Without them the page opens the last pick, kept in the browser's local
  storage, else the first connection. A stored connection that is gone falls
  back to the first.
- Frame message handling that the app and the viewer both need is shared, not
  copied. `src/core` never fetches, so the transport is passed in.

### Packaging

- `[project.scripts]` gains `queryview-server = "queryview.server.main:run"`.
- The same Docker image, started with the command `queryview-server`.

### Security

- No login: anyone who can reach the server sees every dashboard's data on
  every configured connection. The docs say to put it behind a proxy or SSO.
- Whoever can push to the repo decides the SQL the server runs. The docs
  advise a read-only database login without file privileges (see
  `future.md`, "run_sql: server-side file access").

## Docs

- New `docs/server.md`, joined to the `README.md` list.
- `api.md`: the three extended endpoints. `dashboard.md`: substitution happens
  on the server. `docker.md`: running the server. `future.md`: the agent tool.

## Tests

Layers and fixtures per the project `testing` skill.

- Phase 1: pytest for `dashboard_params.py`; API tests for the three extended
  endpoints; the existing dashboard e2e passes unchanged.
- Phase 2: API tests against a local bare repo and a file database, covering
  sync picking up a new commit, a failed fetch keeping the last copy, startup
  failures (a DuckDB folder among them), a value outside the options never
  reaching the SQL, and a hostile `order_by` name; one e2e for the page.

## Left to the builder

- Module and function names, and how much of `DashboardView.tsx` moves to
  `src/core`.
- How option values are stringified, as long as the ported tests pass.
- The clone's directory name and the log format.
