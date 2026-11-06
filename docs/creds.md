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

## Design decisions

Each is a dilemma, how neighbouring tools resolve it, and the choice taken.

- **Hide connections or restrict queries?** DBeaver's MCP can be limited to
  read-only queries, DataGrip's allows everything; both show the agent every
  connection. QueryView takes the opposite trade: the per-connection lock
  hides the connections you choose, and on the rest the agent runs anything
  the credentials allow, writes included. The lock protects connections, not
  tables. Avoid giving QueryView privileged user credentials, since it has
  write capability.
- **Expose a REST API or MCP only?** DBeaver and DataGrip expose MCP alone.
  QueryView also serves REST, so a tab, a script, or a curl can drive it; the
  same lock and metadata-only rules apply on both surfaces.
- **Is a startup token protection?** Jupyter gates its client with a token
  printed at startup. That keeps strangers out, not the agent: an agent running
  commands on the machine reads the token. QueryView does not pretend
  otherwise and binds to localhost with no login instead.
- **What is real protection?** None of these local setups: the agent shares
  the machine with the credentials. Real protection is a hosted service with
  user authentication in front, where credentials stay on the server and the
  agent only holds a scoped user login.

## Errors never echo passwords

Driver auth is sent out of band — ClickHouse in an HTTP `Authorization`
header, Postgres as a discrete connect argument — never in a query string. A
failure surfaces the exception text, which can name the host, port, and
username, but the password is never interpolated into a message.

## Disk-access connections

DuckDB and SQLite read local files, unlike the network drivers. The agent
cannot switch to or create either — only a tab can open one. How far their SQL
reaches into the filesystem differs by driver, below.

## DuckDB

A file or in-memory connection runs with external file access turned off, which
blocks `read_text`, `read_blob`, `read_csv`, `glob`, `ATTACH`, and `COPY` —
every external read or write. Queries and writes to the connection's own
database still work, and DuckDB refuses to re-enable external access at
runtime, so a script cannot turn it back on; each query reopens the connection
fresh.

A folder connection must keep external access on to read its own data files,
and DuckDB 1.5.4 enforces no runtime directory scope, so it can read any local
file. That is not a driver defect: QueryView is a local, single-user tool whose
driving agent already has the user's filesystem read, `encryption.key` included
— no in-tool setting makes a local file private from it.

So credentials are protected operationally: store only read-only,
least-privilege connections, never production write credentials. Then a stolen
config, or the key itself, is worth little.

## SQLite

Browsing and queries open the database file read-only, with `ATTACH` and
`VACUUM INTO` disabled so unwrapped SQL cannot reach or write another file.
SQLite has no `read_text`-style function, so there is nothing to read an
arbitrary file with. The Scripts page opens the file read-write so a script's
own statements can write; `ATTACH` is available there.

## Related docs

- [connect.md](./connect.md) — creating, saving, and locking connections.
- [mcp.md](./mcp.md) — the agent's tools and what they expose.
