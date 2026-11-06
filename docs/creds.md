# Credentials

**Give QueryView only read-only, least-privilege database credentials — never
production write credentials.** It is a local, agent-driven analytic tool, so
treat anything it can reach as readable by the agent.

How QueryView stores connection credentials and keeps them from leaking: where
they live, and why neither the agent nor a stray error can read them back. For
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

## Disk-access connections

DuckDB and SQLite read local files, unlike the network drivers, so their SQL
is sandboxed away from QueryView's own `encryption.key` and `db.sqlite`. The
agent cannot switch to or create either — only a tab can open one.

## DuckDB

A file or in-memory connection runs with external file access turned off, which
blocks `read_text`, `read_blob`, `read_csv`, `glob`, `ATTACH`, and `COPY` —
every external read or write. Queries and writes to the connection's own
database still work. A folder connection instead scopes access to its folder
with `allowed_directories`, so relative reads of the folder's own data files
work while reads outside it do not.

`lock_configuration` seals both: a script that tries to re-enable external
access fails on that statement, so SQL cannot lift the lockdown, and every
query reopens a freshly-locked connection.

A folder connection keeps external file access on so the folder's data files
can be read, and that reach is not perfectly confined to the folder. This is
not a driver defect: QueryView is a local, single-user tool, and the agent that
drives it generally already has read access to the user's files, `encryption.key`
included. No in-tool setting makes a local file private from an agent that can
already read the disk.

So credentials are protected operationally, not by a sandbox: store only
read-only, least-privilege connections in QueryView, never production or write
credentials. Then a stored config, or the key itself, yields nothing powerful.

## SQLite

Browsing and queries open the database file read-only, with `ATTACH` and
`VACUUM INTO` disabled so unwrapped SQL cannot reach or write another file.
SQLite has no `read_text`-style function, so there is nothing to read an
arbitrary file with. The Scripts page opens the file read-write so a script's
own statements can write; `ATTACH` is available there.

## Related docs

- [connect.md](./connect.md) — creating, saving, and locking connections.
- [mcp.md](./mcp.md) — the agent's tools and what they expose.
