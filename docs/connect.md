# Connecting

Connections have two halves: a **type** (the driver, e.g. `clickhouse`) and a
**name** (your label, e.g. `clickhouse`, `prod-ch`). You create a connection
once with `new <type>`, then open it by name with `connect <name>`. Connections
are persisted in SQLite and the latest active one is re-connected automatically
when a session starts.

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

## Commands

| Command          | Effect |
| ---------------- | ------ |
| `new clickhouse` | Open the form to create a new ClickHouse connection. |
| `new postgres`   | Open the form to create a new Postgres connection. |
| `new duckdb`     | Open the form to create a new DuckDB connection (file path; no database picker). |
| `connect <name>` | Open the saved connection `<name>` and show its database picker. |
| `query`          | Return to the query panel from a connection form. A ready session (a database is selected, or a picker-less driver like DuckDB) already shows it (see [query.md](./query.md)). |

**Drivers.** ClickHouse and Postgres take host/port/username/password and present
a database picker — for ClickHouse the picker lists `SHOW DATABASES`, for Postgres
it lists real databases (`pg_database`) and the chosen one is where queries run.
DuckDB takes a **path** (or `:memory:`), has no network and **no picker** —
connecting goes straight to the query panel; schema-qualify tables in SQL as
needed.

All matching is case-insensitive and whitespace-trimmed. An unknown command
shows a hint (`Try "new clickhouse" or "connect <name>"`); `connect <name>` for
an unknown name reports `no connection named "<name>"`.

## Concepts

- **Test connection** — a throwaway connectivity check (`SELECT 1`). It reports
  pass/fail and nothing else: it does **not** save the connection, does not open
  a steady connection, and does not change what the session is connected to.
- **Connect** — opens a *steady* connection: it validates, lists the databases,
  **saves** the connection to SQLite, marks it the latest active, and makes it
  the session's active connection. The UI then returns to the single prompt with
  a database picker.
- **Active connection** — held at the **session** level (see
  [queryview.md](./queryview.md)). One per session.
- **Database selection** — after connecting, the user picks a database. Only
  then does the top-left indicator read `🟢 connected - <database>`. The choice
  is remembered with the connection.

## Creating a connection (`new <type>`)

`new clickhouse` renders the connection form below the prompt.

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
- **Connect** — `POST /api/db/connect`. On success the form closes and
  the prompt view returns with a database picker.

## Flow

```
prompt ── "new clickhouse" ──▶ connection form
                                 │
                 ┌── Test ───────┤   (inline pass/fail, stays here)
                 │               │
                 └── Connect ────┴──▶ prompt "connect <name>" + database picker
                                              │
                              pick a database  │   (picker collapses)
                                              ▼
                                  🟢 connected - <database>

prompt ── "connect <name>" ──▶ opens saved <name> ──▶ database picker ──▶ pick
```

## Opening a saved connection (`connect <name>`)

`connect <name>` looks up the saved connection by name, opens it (lists its
databases), makes it the active session connection, and shows the database
picker. Pick a database from the picker to finish.

## Database picker

After connecting, the prompt view shows the databases returned by
`SHOW DATABASES`. While the picker is open the prompt reads `connect <name>`.
The picker panel is wider than the prompt so long database names fit several
per row. A filter input at
the top of the picker (focused on open) narrows the list by case-insensitive
substring; **Enter** selects the first remaining match, and an empty result
shows "No databases match". Selecting a database:

- sets the session's selected database,
- persists it on the saved connection (`POST /api/db/database`),
- collapses the picker and shows the top-left indicator `🟢 connected - <database>`,
- clears the prompt and opens the query panel (see [query.md](./query.md)).

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
  last_active_at INTEGER NOT NULL -- unix ms; the max is the "latest active"
);
```

- **Connect** upserts the row by `name` and bumps `last_active_at`.
- **Selecting a database** updates `database` for that row.
- **Latest active** = the row with the greatest `last_active_at`.

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
auto-connect simply skips that connection and the user reconnects, which
re-encrypts it with the current key.

## Sessions, cookies & auto-connect

Each browser session has **one active connection**, held server-side and keyed
by a session **cookie** (`qv_session`, HttpOnly, set on first request). Different
sessions (browsers / profiles) connect independently — one session switching
connections doesn't affect another. Saved connections themselves are shared
(stored once in SQLite); the *active* one is per session.

When a session starts (a cookie the backend hasn't seen), `GET /api/session`
lazily reconnects the **latest active** connection from SQLite, so a fresh
session resumes where the last one left off:

- On success the SPA loads already connected — prompt + database picker, with
  the previously selected database pre-selected and the indicator shown.
- On failure (server down, bad credentials) the SPA falls back to the empty
  prompt; the saved connection is left in place to retry.

To open a **specific** connection on load instead, pass `…/?connection=<name>`
(equivalent to `connect <name>`); the SPA then cleans the URL so a later reload
resumes normally.

Per-session state lives in memory, so a backend restart drops it; the next
request gets a new session that auto-connects the latest active connection.

## API

| Method | Path                          | Body                                   | Result |
| ------ | ----------------------------- | -------------------------------------- | ------ |
| POST   | `/api/db/test`        | `{type, …driver config}`               | `{ok, message}` — test only |
| POST   | `/api/db/connect`     | `{type, name, …driver config}`         | `{ok, name, type, databases}` \| `{ok:false, message}`; saves + activates (`new <type>` form) |
| POST   | `/api/db/open`        | `{name}`                               | `{ok, name, databases}` \| `{ok:false, message}`; opens a saved connection (`connect <name>`) |
| POST   | `/api/db/database`    | `{database}`                           | `{ok}`; sets the session/connection database |
| POST   | `/api/db/query`       | `{query, limit?, offset?, format?}`    | `{ok, meta, data}` \| `{ok:false, message}`; paginated SQL against the session's selected database (`format:"csv"` returns `{ok, output}` CSV text) |
| GET    | `/api/predefined-queries`     | `?type=<connType>`                     | `{queries:[{query_name, query}]}`; global predefined queries by connection type |
| POST   | `/api/predefined-queries`     | `{query_name, type, query}`            | `{ok}`; upserts a global predefined query |
| GET    | `/api/session`                | —                                      | `{connected, name?, type?, databases?, database?}`; auto-connects latest active |

`test`/`connect` resolve the driver from `type` and validate per driver
(ClickHouse/Postgres require `host` + `port` `1..65535`; DuckDB requires a
`path`); validation errors return `400`. ClickHouse queries run over the HTTP
interface with HTTP Basic auth and a 5s timeout.

## CI

CI runs a real `clickhouse/clickhouse-server` service container so the e2e suite
exercises an actual connection: it asserts that connecting succeeds, a database
can be selected, the indicator shows `connected - <database>`, and a query
against a seeded `test` database returns its rows.
