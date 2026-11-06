# Credentials

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

One gap remains on a folder connection: DuckDB does not apply
`allowed_directories` to `read_text`, `read_blob`, or `glob`, so SQL on a
folder connection can still read a file outside the folder, including
`encryption.key`. A DuckDB build that enforces `allowed_directories` for those
functions, or an OS-level filesystem sandbox (for example a Linux Landlock
ruleset that denies the query process any path outside the folder), closes it.

Connecting a folder to the agent is itself read access. The agent reads every
data file in that folder, as the connection intends, and — through the residual
above — can reach files outside it. This is inherent in pointing a SQL agent at
local files: the agent borrows the user's own filesystem read, independent of
QueryView. The protections here limit its reach and bar it from opening a
file-driver connection on its own; they do not make a folder the user has
connected private from the agent.

## SQLite

Browsing and queries open the database file read-only, with `ATTACH` and
`VACUUM INTO` disabled so unwrapped SQL cannot reach or write another file.
SQLite has no `read_text`-style function, so there is nothing to read an
arbitrary file with. The Scripts page opens the file read-write so a script's
own statements can write; `ATTACH` is available there.

## Related docs

- [connect.md](./connect.md) — creating, saving, and locking connections.
- [mcp.md](./mcp.md) — the agent's tools and what they expose.
