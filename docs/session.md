# Sessions

A **session** is one browser tab's working state: the page you are on and its
URL, the connection and database you are querying, your workspace, and the
per-view settings a reload should bring back. It lives in SQLite, so it survives
a browser refresh *and* a backend restart.

Exactly one tab holds a session at a time, but sessions outlive the tabs that
held them: close a tab and the next one you open picks its session back up.

> **`sessionStorage` holds identity. The server holds state.**
> No browser storage holds anything durable — the app uses no `localStorage` at
> all.

## What a session remembers

| | |
| --- | --- |
| Route and URL | `/explorer?table=events`, `/dashboard?name=sales` — path and query string |
| Connection | the saved connection this session is on, and its selected database |
| Workspace | which workspace scopes its queries, dashboards and git sync |
| Query panel | SQL text, limit/offset, visible columns, sort |
| Explorer | the Tables sidebar width |

**Results are not remembered.** A reload restores the SQL you were writing and
how it was paginated, but not the rows — so reopening a tab can never re-fire an
expensive query. The explorer is different because it is URL-driven: an
`?table=` in the restored URL does re-load that table's rows, exactly as
following the same link would.

Anything transient stays in the page and is never written: whether a popover is
open, filter text, a drag in progress, fetched rows.

## Refresh, new tabs, and the claim

Each tab keeps two values in `sessionStorage` — `qv_tab`, a token it mints for
itself, and `qv_session`, the session it is attached to. Both survive a refresh;
neither crosses to a new tab. That is the whole trick: **a tab that already has
an id is refreshing, a tab without one is new.**

A session is **held** while the tab holding it has been heard from within 30
seconds. Tabs re-attach every 10 seconds, which doubles as the heartbeat, and
send a release beacon when they close. A tab that crashes simply stops
heartbeating, and its session frees itself.

`POST /api/sessions/attach` makes the whole decision server-side, in one pass,
so two tabs opening at once cannot race:

1. **The id the tab already has**, if it is free or already this tab's — a
   refresh, or a heartbeat. *This is why a refresh never resets anything.*
2. Otherwise **the most recently active session no tab is holding** — "restore
   the last session".
3. Otherwise **a new session**.

Step 1 falls through when a *different* live tab holds that id. Duplicating a
tab copies its `sessionStorage`, so the copy arrives carrying someone else's
session id; it gets its own session instead of hijacking the original.

In practice:

- **Refresh** → the same session, same page, same everything.
- **New tab while another is open** → a new session, because the first tab is
  holding its own.
- **New tab with nothing else open** → your last session comes back.

## The session dropdown

The top-right dropdown lists every session, most recently active first. Each row
shows its label; one held by another live tab is shown but not selectable, since
two tabs on one session would overwrite each other's state.

- **New session** starts a fresh one in this tab.
- **Rename this session** pins a name. Clearing the name unpins it.
- **×** deletes a session. A session a live tab is holding refuses deletion.

A label with no name pinned is derived from the session's state:
`connection · database`, else the connection name, else `Session <n>`.

Sessions never expire. Every tab you open while another is in use adds one, so
the list grows until you prune it — that is the cost of sessions being durable
and nameable rather than a capped history.

## Sessions and the agent

The id in the agent popover **is** the session id. An agent pointed at it acts on
that session's connection, database and workspace, read straight from the
session. Arming is still the gate: disarming closes the channel and any later
push fails with `unknown or inactive session`. Unlike the old per-arm id, this
one is stable, so the command you copy stops changing under you. See
[remote.md](./remote.md).

## How it is stored

One row per session in SQLite (`sessions`), alongside connections and
workspaces — see [connect.md](./connect.md#storage--migrations).

```sql
id              TEXT PRIMARY KEY  -- also the agent channel id
seq             INTEGER           -- stable ordinal behind "Session 3"
label           TEXT              -- NULL = derived; set = pinned by you
connection_name TEXT              -- NULL is the durable "disconnected" state
database        TEXT
workspace       TEXT
url             TEXT              -- path + query string
ui              TEXT              -- JSON, namespaced by view
claimed_by      TEXT              -- the tab token holding it
claim_seen_at   INTEGER           -- unix ms; stale after 30s
last_active_at  INTEGER           -- unix ms
```

`ui` is a JSON blob rather than columns, for the same reason a connection's
config is one: a view can remember a new setting without a migration.

```json
{"query": {"sql": "…", "limit": 100, "offset": 0, "visibleCols": [], "orderBy": []},
 "explorer": {"sidebarWidth": 256}}
```

Every `/api/*` request names its session with an `X-QV-Session` header. There is
no session cookie: a session is named by its id, not by the browser it happens
to be open in, which is what lets two tabs sit on two different databases at
once. The one exception is the remote-control SSE stream, which takes
`?session=` because `EventSource` cannot send headers.

Writes are debounced (400ms) and fire-and-forget: the page never waits on one,
and a lost patch costs a remembered preference, never your work in the live tab.

## API

See [api.md](./api.md#sessions) for the request and response shapes.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/attach` | Resolve and claim this tab's session; doubles as the heartbeat. |
| POST | `/api/sessions/select` | Switch to a session, or (no id) start a new one. |
| GET | `/api/sessions` | The dropdown's rows. |
| PATCH | `/api/sessions/{id}` | Update `url`, `ui`, `label` or `workspace`. |
| DELETE | `/api/sessions/{id}` | Delete one; refused while held. |
| POST | `/api/sessions/release` | The closing tab's beacon. |

The connection and database are not patched here — `/api/db/connect`, `/open`
and `/database` write them through, so connection changes keep one path.
