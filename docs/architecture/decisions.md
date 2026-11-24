# Decisions

Decisions behind two features: the credential choices cut from [creds.md](../system/creds.md) and the folder-mode listing choice cut from [explorer.md](../system/explorer.md).

## Design decisions

Each dilemma, how neighbouring tools resolve it, and the choice taken.

- **Hide connections or restrict statements?** Database MCP servers restrict
  statements: [mcp-clickhouse](https://github.com/ClickHouse/mcp-clickhouse)
  runs with `readonly=1` unless `CLICKHOUSE_ALLOW_WRITE_ACCESS` is set;
  [Postgres MCP Pro](https://github.com/crystaldba/postgres-mcp) has
  `--access-mode=restricted`. IDEs pick per connection:
  [DBeaver](https://dbeaver.com/docs/dbeaver/Model-Context-Protocol-Server/)
  exposes only connections with **Enable MCP access to this connection**
  ticked; [DataGrip](https://www.jetbrains.com/help/datagrip/mcp-server.html)
  lists every data source, with no read-only switch. QueryView follows the
  IDEs: the lock hides the connections you choose; on the rest the agent runs
  anything the credentials allow, writes included. The lock protects
  connections, not tables. Avoid giving QueryView privileged user
  credentials, since it has write capability.
- **Who enforces read-only?** The database user, per every vendor. DataGrip:
  "use a database user with properly restricted (read-only) privileges".
  mcp-clickhouse: its statement check "is not a security boundary. The
  security boundary is the ClickHouse user's grants." QueryView adds no
  statement filter and relies on the same rule.
- **REST API or MCP only?** DBeaver and DataGrip serve MCP alone, DBeaver
  bound to localhost. QueryView also serves REST, so a tab, script, or curl
  can drive it; lock and metadata-only rules apply on both surfaces.
- **Is a startup token protection?** [Jupyter](https://jupyter-server.readthedocs.io/en/latest/operators/security.html)
  gates its server with a token printed at startup. That keeps other hosts
  out, not the agent: a process on the same machine reads the token from the
  server's runtime files. QueryView binds to localhost with no login instead.
- **What is real protection?** Not a local setup: the agent shares the
  machine with the credentials. A hosted service with user authentication in
  front, where credentials stay on the server and the agent holds only a
  scoped user login.

## Why folder mode lists one level at a time

The folder list is read per level, centred on the selected folder, rather than
scanned across the whole tree at connect:

- **The limit trims a view, not reachability.** With a whole-tree scan, a cap
  hides deep folders whenever the tree grows or the cap drops, and a restart
  or a saved dashboard then loses the selected folder. Per level, the selected
  folder is reached by its path, so neither can drop it.
- **Connect costs one directory read** on any root size, instead of a scan
  bounded only by the cap.
- **Checking each step of the path,** not just the final folder, is what keeps
  a symlink partway along (`link` -> `/etc`) from leading outside the root.
- **A missing step stops at the nearest parent** rather than the root, so a
  deleted folder leaves the user as close as possible to where they were.
- The cost: the menu re-reads a level on each pick, and an agent listing
  folders without a selection sees only the root's top level.

## Related docs

- [creds.md](../system/creds.md) — how credentials are stored and protected.
- [explorer.md](../system/explorer.md) — the table navigator.
