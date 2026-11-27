# Storage and CI

Where connections live and how they are kept: the SQLite data directory, migrations, the `connections` table, config encryption and CI. Connecting from the app is in [connect.md](../user_guide/connect.md).

## Storage & migrations

<!-- req: data-dir -->
State lives in one data directory (`DATA_DIR`, defaulting to `~/.queryview`),
whose SQLite file is `db.sqlite`.

<!-- req: alembic-schema -->
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

## Persistence (SQLite)

Connection details are stored via SQLModel in the SQLite database (see
[Storage & migrations](#storage--migrations)). Schema (the `connections` table):

```sql
CREATE TABLE connections (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL UNIQUE,
  type           TEXT NOT NULL,   -- selects the driver (clickhouse | postgres | mysql | duckdb | sqlite)
  config         TEXT NOT NULL,   -- base64(AES-GCM(json.dumps(driver config)))
  database       TEXT,            -- last selected database (nullable)
  last_active_at INTEGER NOT NULL -- unix ms; when it was last opened
);
```

- **Connect** upserts the row by `name` and bumps `last_active_at`.
- **Selecting a database** updates `database` for that row.
- `last_active_at` orders the saved cards, most recent first.

Driver-specific fields (host/port/user/pass for ClickHouse, Postgres and MySQL, a file
path for DuckDB) are not columns — each driver serializes its own config to a
dict that is JSON-encoded and stored encrypted in `config`. Adding a future
driver needs no schema change.

## Config encryption

<!-- req: config-encrypted -->
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

## CI

CI runs a real `clickhouse/clickhouse-server` service container so the e2e suite
exercises an actual connection: it asserts that connecting succeeds, a database
can be selected, the indicator shows `<connection> · <database>`, and a query
against a seeded `test` database returns its rows.

## Related docs

- [connect.md](../user_guide/connect.md) — connections, drivers and the Connect page.
- [creds.md](../user_guide/creds.md) — how credentials are protected.
- [api.md](./api.md) — backend JSON API.
