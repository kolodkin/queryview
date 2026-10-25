# Connecting

Connections have two halves: a **type** (the driver, e.g. `clickhouse`) and a
**name** (your label, e.g. `clickhouse`, `prod-ch`). Create one from a **New
connection** card on the Connect page (see [queryview.md](./queryview.md)),
reopen it from its saved card. Connections persist in SQLite, and a session
reconnects whichever one it was last on.

## Storage & migrations

State lives in one data directory (`DATA_DIR`, defaulting to `~/.queryview`),
whose SQLite file is `db.sqlite`.
The backend is **single-process** — SQLite is single-writer, so one process owns
the file, and no cross-process migration lock is needed. The schema is owned by
**Alembic**: on startup the FastAPI lifespan runs `alembic upgrade head` (via
`connect._ensure_schema()`) before serving any request, so an Alembic-managed DB
is migrated forward in place rather than rebuilt. Migrations ship inside the
package (`backend/queryview/migrations/`). To author a new revision after
changing a model, from `backend/`:

```
DATA_DIR=/tmp/qv-dev uv run alembic revision --autogenerate -m "describe change"
```

Review the generated script (column changes use batch mode for SQLite) and
commit it; the app applies it on next start.

> A DB predating Alembic (created by the old `create_all`, so it has no
> `alembic_version` table) is not upgraded automatically — delete it and let the
> app recreate it on next start.

## Drivers

 ClickHouse and Postgres take host/port/username/password and present
a database picker — for ClickHouse the picker lists `SHOW DATABASES`, for Postgres
it lists real databases (`pg_database`) and the chosen one is where queries run.
DuckDB takes a **path** (or `:memory:`), has no network and **no picker** —
connecting goes straight to the explorer; schema-qualify tables in SQL as
needed.

A saved card that fails to open reports the error under the cards.
When QueryView runs in a container and a connect to `localhost` / `127.0.0.1`
fails, the error suggests `host.docker.internal` (see the README's
[Connecting to databases on your machine](../README.md#connecting-to-databases-on-your-machine)).

## Concepts

- **Test connection** — a throwaway connectivity check (`SELECT 1`). It reports
  pass/fail and nothing else: it does **not** save the connection, does not open
  a steady connection, and does not change what the session is connected to.
- **Connect** — opens a *steady* connection: it validates, lists the databases,
  **saves** the connection to SQLite and makes it the session's active
  connection, then shows the database picker.
- **Active connection** — held at the **session** level (see
  [queryview.md](./queryview.md)). One per session.
- **Database selection** — after connecting, the user picks a database. Only
  then does the top-left indicator read `🟢 <connection> · <database>`. The choice
  is remembered with the connection.

## Creating a connection

A **New connection** card shows its driver's form in place of the cards
(ClickHouse below); **← Connections** goes back without saving.

| Field    | Default     | Notes                                          |
| -------- | ----------- | ---------------------------------------------- |
| Name     | `clickhouse`| Label for the connection (unique key in storage). |
| Host     | `localhost` | ClickHouse host.                               |
| Port     | `8123`      | ClickHouse HTTP interface port.                |
| Username | `default`   | ClickHouse user.                               |
| Password | *(empty)*   | ClickHouse password.                           |

Two actions:

- **Test connection** — `POST /api/db/test`. Shows a pass/fail message
  inline. No side effects.
- **Connect** — `POST /api/db/connect`. On success the picker opens.

## Flow

```
cards ── "New connection" card ──▶ connection form
                                     │
                     ┌── Test ───────┤   (inline pass/fail, stays here)
                     │               │
                     └── Connect ────┴──▶ database picker
                                              │
                              pick a database  │
                                              ▼
                              🟢 <connection> · <database>  (explorer)

cards ── saved card ──▶ opens <name>, activates it ──▶ database picker ──▶ pick
```

## Database picker

After connecting, the picker lists the databases (`SHOW DATABASES`), the last
one used highlighted; **← Connections** returns to the cards, leaving the
connection open. A filter input (focused on open) narrows the list by case-insensitive
substring; **Enter** selects the first remaining match, and an empty result
shows "No databases match". Each row has a copy icon for its name. Selecting a database:

- sets the session's selected database,
- persists it on the saved connection (`POST /api/db/database`),
- collapses the picker and shows the top-left indicator `🟢 <connection> · <database>`,
- makes the query panel available on QueryView (see [query.md](./query.md)),
- and lands on the explorer (see
  [queryview.md](./queryview.md#landing-page)).

Clicking the `🟢 <connection> · <database>` pill reopens the same list as a
dropdown — same filter, plus **Escape** to close — so the database can be
switched from any page without going back to Connect. Below the databases it
lists the connections; clicking one opens it. Both the dropdown and the picker
re-list the databases on open, so one created since the connect appears; a
failed re-list keeps the list on screen.

## Persistence (SQLite)

Connection details are stored via SQLModel in the SQLite database (see
[Storage & migrations](#storage--migrations)). Schema (the `connections` table):

```sql
CREATE TABLE connections (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL UNIQUE,
  type           TEXT NOT NULL,   -- selects the driver (clickhouse | postgres | duckdb)
  config         TEXT NOT NULL,   -- base64(AES-GCM(json.dumps(driver config)))
  database       TEXT,            -- last selected database (nullable)
  last_active_at INTEGER NOT NULL -- unix ms; when it was last opened
);
```

- **Connect** upserts the row by `name` and bumps `last_active_at`.
- **Selecting a database** updates `database` for that row.
- `last_active_at` orders the saved cards, most recent first.

Driver-specific fields (host/port/user/pass for ClickHouse and Postgres, a file
path for DuckDB) are not columns — each driver serializes its own config to a
dict that is JSON-encoded and stored encrypted in `config`. Adding a future
driver needs no schema change.

## Config encryption

The whole `config` blob is **encrypted at rest** with AES-256-GCM; the stored
value is `base64(iv ‖ ciphertext)` (AES-GCM appends its 16-byte tag to the
ciphertext), never plaintext. Storing the entire config (not just a password
field) keeps the storage layer secret-agnostic. The key is resolved once and
memoized on first use:

- `DB_ENCRYPTION_KEY` — base64 of 32 bytes, if set (use this in CI/shared envs);
- otherwise a key is generated and written to `encryption.key` in the data dir
  (gitignored, mode `600`).

If the key changes (or a row predates encryption) the value can't be decrypted;
a session on that connection reads as disconnected and the user reconnects,
which re-encrypts it with the current key.

## Session connections

A **session connection** lives only in one session's memory: never saved,
invisible to other sessions, gone when the session is deleted or the backend
restarts (the session then reads as disconnected).

- Each carries `scope` (`session` | `saved`) and `created_by` (`agent` |
  `user`); connections the agent added get an `agent` badge on their card and
  in the pill menu's connection list (session ones listed apart from saved, the
  active one marked). The user's own get none.
- When one is added or removed, an armed tab's lists refresh. The session row
  records who switched (`connection_by`: `agent` | `user`); a tab that sees the
  agent's `use_connection` toasts "Agent switched to <name>", never the user's.
- You add one with **Session only — don't save** on the new-connection form.
- Names are unique across saved connections and all sessions' ones.
- The agent may add (ClickHouse or Postgres only: DuckDB reads local files),
  switch to, pick the database of and remove its own. Anything else it may only
  list, and query while active. See [remote.md](./remote.md#mcp-tools).
- This keeps a cooperating agent in its lane; it is not a security boundary.
  For one, lock the connection.

## Locked connections

A saved connection can be **locked** behind a passphrase: click the lock on
its card and type one. On a session whose active connection is locked, every
MCP tool that reads or writes data (`run_sql`, `run_script`, `select_database`,
the table list in `session_info`, every push) answers `connection is locked`,
and so does every REST call without the tab's unlock token (`403`).
`list_connections` and `session_info` still name the connection and report
`locked: true`. Session connections are never locked: they are the agent's own.

Stored: only a salted scrypt hash of the passphrase (`lock_hash` on the
`connections` row). Held by the tab: an **unlock token**, a random string the
server issues for the passphrase and keeps in memory per session, kept in
`sessionStorage` (`qv_token`) and sent as `X-QV-Token` on every request.
Locking hands the locking tab its token, so the connection it is on keeps
working.

- **Opening** a locked card lands on it like any other; the shell then asks
  for the passphrase unless the tab holds a token for it, as it does when a
  session resumes on a locked connection without one (a new tab, a backend
  restart). Cancelling disconnects.
- **Reload** keeps the token; closing the tab drops it. A restart drops the
  server side, so the next request asks again.
- **Removing** the lock takes the passphrase. A forgotten passphrase means
  deleting and re-adding the connection.
- Attempts on a connection back off exponentially (2s, 4s … 30s), whoever
  sends them.

Not covered: typing the passphrase where the agent can read it, or handing the
agent the browser tab that holds the token.

## Sessions & reconnecting

Each **session** has one active connection, recorded on the session's own row in
SQLite and keyed by the `X-QV-Session` header the SPA sends with every request.
There is no session cookie: sessions are named by id, not by browser, so two
tabs can sit on two different connections and databases at once. Saved
connections themselves are shared (stored once in SQLite); the *active* one is
per session. See [session.md](./session.md).

Opening the app attaches a session and reconnects whatever connection that
session was on:

- On success the SPA loads already connected, with the previously selected
  database pre-selected and the indicator shown, on the page the session was
  last on (see [queryview.md](./queryview.md#landing-page)).
- On failure (server down, bad credentials) the SPA falls back to Connect;
  the saved connection is left in place to retry.
- If the connection was since deleted, or its config no longer decrypts, the
  session simply reads as disconnected. It is not repaired or repointed — you
  reconnect.

A session with no connection (`connection_name IS NULL`) is disconnected, and
stays that way across restarts: that is what `disconnect` records.

To open a **specific** connection on load, pass `…/?connection=<name>`
(equivalent to clicking its card); the SPA then cleans the URL so a later reload
resumes normally.

Only the live driver state — the decrypted config and the database list — is
held in memory, as a cache. A backend restart costs one reconnect, not the
session.

## API

| Method | Path                          | Body                                   | Result |
| ------ | ----------------------------- | -------------------------------------- | ------ |
| POST   | `/api/db/test`        | `{type, …driver config}`               | `{ok, message}` — test only |
| POST   | `/api/db/connect`     | `{type, name, session?, …driver config}` | `{ok, name, type, databases}` \| `{ok:false, message}`; saves + activates (new-connection form); `session:true` keeps it session-only |
| GET    | `/api/db/connections` | —                                      | `{connections:[{name, type, database, last_active_at, scope, created_by, locked}]}`: this session's connections, then the saved ones most recent first (never the config) |
| POST   | `/api/db/open`        | `{name}`                               | `{ok, …}` the same state as `GET /api/session` \| `{ok:false, message}`; opens a connection by name, this session's session connections first (a card); on a locked one `unlocked` says whether this tab's token opens it |
| POST   | `/api/db/lock`        | `{name, passphrase}`                   | Lock a saved connection; `{ok, token}` for this tab. Empty passphrase, unknown or already locked → `400` |
| POST   | `/api/db/unlock`      | `{name, passphrase}`                   | `{ok, token}` — this session's unlock token; wrong passphrase → `403`, not locked → `400` |
| DELETE | `/api/db/lock`        | `{name, passphrase}`                   | Remove the lock; `{ok}`, wrong passphrase → `403` |
| GET    | `/api/db/databases`   | —                                      | `{ok, name, databases}` \| `{ok:false, message}`; re-lists the session's connection's databases, refreshing the cached list; no session → `409` |
| POST   | `/api/db/database`    | `{database}`                           | `{ok}`; sets the session/connection database (a name missing from the cached list is re-listed once before failing) |
| POST   | `/api/db/query`       | `{query, limit?, offset?, format?}`    | `{ok, meta, data}` \| `{ok:false, message}`; paginated SQL against the session's selected database (`format:"csv"` returns `{ok, output}` CSV text) |
| GET    | `/api/predefined-queries`     | `?type=<connType>`                     | `{queries:[{query_name, query}]}`; global predefined queries by connection type |
| POST   | `/api/predefined-queries`     | `{query_name, type, query}`            | `{ok}`; upserts a global predefined query |
| GET    | `/api/session`                | —                                      | `{connected, name?, type?, databases?, database?}` for the calling session |

`test`/`connect` resolve the driver from `type` and validate per driver
(ClickHouse/Postgres require `host` + `port` `1..65535`; DuckDB requires a
`path`); validation errors return `400`. ClickHouse queries run over the HTTP
interface with HTTP Basic auth and a 5s timeout.

## CI

CI runs a real `clickhouse/clickhouse-server` service container so the e2e suite
exercises an actual connection: it asserts that connecting succeeds, a database
can be selected, the indicator shows `<connection> · <database>`, and a query
against a seeded `test` database returns its rows.
