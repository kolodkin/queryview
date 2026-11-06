# Security

How QueryView keeps connection credentials from leaking: where they are
stored, and why neither the agent nor a stray error can read them back. For
how you create and lock connections see [connect.md](./connect.md); for the
agent's tool surface see [mcp.md](./mcp.md).

## Credentials at rest

A saved connection's config — host, port, username, password — is encrypted
with AES-GCM before it is written to the SQLite store. The 256-bit key lives
in `encryption.key` in the data directory (`~/.queryview` by default), created
`0600` on first run, or supplied as `DB_ENCRYPTION_KEY`. The store holds only
ciphertext; a config is decrypted in memory to open a driver connection and
never written back in the clear.

## The agent never reads credentials

The agent's tools return connection metadata only — name, type, scope,
creator, selected database. No tool returns a stored config. The edit form's
endpoint blanks the password before sending it, so a saved password leaves the
server only as an empty string. A connection the agent adds itself with
`add_connection` is held in session memory and is never readable back.

## Locked connections

A saved connection can be locked behind a passphrase. Only its scrypt hash is
stored, never the passphrase. Unlocking exchanges the passphrase for a
per-session token; wrong attempts back off exponentially, up to 30 seconds. A
locked connection is hidden from the agent entirely and cannot be queried
until a tab unlocks it.

## Errors never echo passwords

Driver auth is sent out of band — ClickHouse in an HTTP `Authorization`
header, Postgres as a discrete connect argument — never in a query string. A
failure surfaces the exception text, which can name the host, port, and
username, but the password is never interpolated into a message.

## Local-file drivers cannot read the store

DuckDB and SQLite connections read local files, so their SQL is sandboxed
away from QueryView's own `encryption.key` and `db.sqlite`. SQLite opens
read-only with `ATTACH` disabled. A DuckDB file or in-memory connection runs
with external file access turned off; a DuckDB folder connection is scoped to
its folder with `allowed_directories`. The lockdown is locked so SQL cannot
lift it. The agent also cannot switch to or create a file-driver connection.

A folder connection keeps one gap: DuckDB does not apply `allowed_directories`
to `read_text`, `read_blob`, or `glob`, so SQL on a folder connection can still
read a file outside the folder, including `encryption.key`. A DuckDB build that
enforces `allowed_directories` for those functions, or an OS-level sandbox,
closes it.

## Related docs

- [connect.md](./connect.md) — creating, saving, and locking connections.
- [mcp.md](./mcp.md) — the agent's tools and what they expose.
