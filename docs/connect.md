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
  then does the top-left indicator read `🟢 connected - <database>`. The choice
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
                              🟢 connected - <database>  (explorer)

cards ── saved card ──▶ opens <name>, activates it ──▶ database picker ──▶ pick
```

## Database picker

After connecting, the picker lists the databases (`SHOW DATABASES`), the last
one used highlighted; **← Connections** returns to the cards, leaving the
connection open. A filter input (focused on open) narrows the list by case-insensitive
substring; **Enter** selects the first remaining match, and an empty result
shows "No databases match". Selecting a database:

- sets the session's selected database,
- persists it on the saved connection (`POST /api/db/database`),
- collapses the picker and shows the top-left indicator `🟢 connected - <database>`,
- makes the query panel available on Queries (see [query.md](./query.md)),
- and lands on the explorer (see
  [queryview.md](./queryview.md#landing-page)).

Clicking the `🟢 connected - <database>` pill reopens the same list as a
dropdown — same filter, plus **Escape** to close — so the database can be
switched from any page without going back to Connect.

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
| POST   | `/api/db/connect`     | `{type, name, …driver config}`         | `{ok, name, type, databases}` \| `{ok:false, message}`; saves + activates (new-connection form) |
| GET    | `/api/db/connections` | —                                      | `{names, connections:[{name, type, database, last_active_at}]}`, most recent first; the saved cards (never the config) |
| POST   | `/api/db/open`        | `{name}`                               | `{ok, name, databases}` \| `{ok:false, message}`; opens a saved connection (a saved card) |
| POST   | `/api/db/database`    | `{database}`                           | `{ok}`; sets the session/connection database |
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
can be selected, the indicator shows `connected - <database>`, and a query
against a seeded `test` database returns its rows.
