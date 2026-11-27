# Connecting

Connections have two halves: a **type** (the driver, e.g. `clickhouse`) and a
**name** (your label, e.g. `clickhouse`, `prod-ch`). Create one from a **New
connection** card on the Connect page (see [queryview.md](./queryview.md)),
reopen it from its saved card. Connections persist in SQLite, and a session
reconnects whichever one it was last on.

## Add a connection

<!-- req: add-connection -->
A user can save a connection to a ClickHouse, Postgres, MySQL, DuckDB or SQLite
database.

- Each of the five drivers offers a new-connection form: host, port and
  credentials, or a file path for DuckDB and SQLite.
- Connecting saves the connection under the name given; it is listed among the
  saved connections when the user comes back.

## Open a database

<!-- req: open-database -->
A user can open a saved connection, pick a database, and find it reconnected
next time.

- Opening a saved connection offers its databases to pick from, narrowed by
  typing.
- Picking one opens its tables and shows the connection and database in use.
- Opening the app again reconnects to the same connection and database; the
  saved connection is marked active and reopens on that database.
- The database can be switched from any page.

## Drivers

ClickHouse, Postgres and MySQL take host/port/username/password and present
a database picker — for ClickHouse and MySQL the picker lists
`SHOW DATABASES`, for Postgres it lists real databases (`pg_database`); the
chosen one is where queries run.
A named **Database** narrows the picker to that one and opens on it.
DuckDB takes a **path** (or `:memory:`) and has no network. A `.duckdb` file
has **no picker** — connecting goes straight to the explorer; schema-qualify
tables in SQL as needed. A **folder** gets the folder picker instead: its
subfolders are the "databases" and its data files the tables, landing on the
folder itself (see [explorer.md](./explorer.md#duckdb-folder-mode)).
SQLite takes a **path** to an existing file (`:memory:` is refused: every
request opens a fresh connection) and, like a `.duckdb` file, has no picker;
every page but the script run opens it read-only. Windows network (UNC) paths
like `\\fileserver\share\reports.db` don't open; map the share to a drive
letter instead.

A saved card that fails to open reports the error under the cards.
When QueryView runs in a container and a connect to `localhost` / `127.0.0.1`
fails, the error suggests `host.docker.internal` (see
[Connecting to databases on your machine](./docker.md#connecting-to-databases-on-your-machine)).

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
  is remembered with the connection, and reopening the connection in the same
  session goes straight back to it (see
  [session.md](./session.md#last-visited)).

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
| Show all | on          | Checked while **Database** is blank; checking it clears it. |
| Database | *(empty)*   | The only database listed, opened on connect.   |

Two actions:

- **Test connection** — `POST /api/db/test`. Shows a pass/fail message
  inline. No side effects.
- **Connect** — `POST /api/db/connect`. On success the picker opens.

## Editing and deleting

Each saved card has **✎** and **✕**:

- **✎** reopens the driver form on the saved values (password blank) with the
  name fixed; **Save & connect** re-saves it under that name and opens it. A
  blank password keeps the saved one, so a host or user can change alone.
- **✕** deletes the connection after a confirm. Every session on it is
  disconnected; the lock, if any, goes with it.

A session connection has **✕** only.

## Flow

```
cards -- "New connection" card --> connection form
                                     |
                     +-- Test -------+   (inline pass/fail, stays here)
                     |               |
                     +-- Connect ----+--> database picker
                                              |
                              pick a database |
                                              v
                              (o) <connection> - <database>  (explorer)

cards -- saved card --> opens <name>, activates it --> last visited database
                                                     (else the picker --> pick)
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
- makes the [Scripts](./scripts.md) page available,
- and lands on the explorer (see
  [queryview.md](./queryview.md#landing-page)).

Clicking the `🟢 <connection> · <database>` pill reopens the same list as a
dropdown — same filter, plus **Escape** to close — so the database can be
switched from any page without going back to Connect. Below the databases it
lists the connections; clicking one opens it. Both the dropdown and the picker
re-list the databases on open, so one created since the connect appears; a
failed re-list keeps the list on screen.

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
- The agent may switch to any unlocked ClickHouse, Postgres or MySQL connection and
  pick the database of whichever unlocked one it is on; it may add (also
  ClickHouse, Postgres or MySQL only: DuckDB and SQLite read local files) and remove
  only its own. See [mcp.md](../architecture/mcp.md#tools).
- This keeps a cooperating agent in its lane; it is not a security boundary.
  For one, lock the connection.

## Locked connections

A saved connection can be **locked** behind a passphrase: click the lock on
its card and type one. On a session whose active connection is locked, every
MCP tool that reads or writes data (`run_sql`, `run_script`, `select_database`,
the table list in `session_info`, every push) answers `connection is locked`,
as does `use_connection` naming a locked one,
and so does every REST call without the tab's unlock token (`403`).
`list_connections` and `list_databases` leave a locked connection out
entirely, even while a tab has it unlocked: the lock is the connection's
stored state, an unlock only that tab's. Session connections are never
locked. A lock holds against the API only: an agent's script on any unlocked
DuckDB or SQLite connection can reach every file QueryView can, a locked
connection's file and `db.sqlite` included
([scripts.md](./scripts.md#file-writes)).

<!-- req: locked-hidden-from-agent -->
The agent's tools tell it nothing about a locked connection but that the
session is on one: `session_info` reports `locked: true` with no name, type,
database or tables.

Stored: only a salted scrypt hash of the passphrase (`lock_hash` on the
`connections` row). Held by the tab: an **unlock token**, a random string the
server issues for the passphrase and keeps in memory per session, kept in
`sessionStorage` (`qv_token`) and sent as `X-QV-Token` on every request.
Locking hands the locking tab its token, so the connection it is on keeps
working.
A [federated dashboard](./dashboard.md#federated-dashboards) naming a
locked connection runs its queries only from a tab holding that token; the
[federated pill](./queryview.md#layout) marks it 🔒 with **Unlock**.

- **Opening** a locked card lands on it like any other; the shell then asks
  for the passphrase unless the tab holds a token for it, as it does when a
  session resumes on a locked connection without one (a new tab, a backend
  restart). Cancelling disconnects.
- **Reload** keeps the token; closing the tab drops it. A restart drops the
  server side, so the next request asks again.
- **Removing** the lock takes the passphrase, and so does **deleting** the
  connection. **Editing** needs the tab's token: without one the passphrase
  is asked first. A forgotten passphrase means deleting and re-adding the
  connection.
- Attempts on a connection back off exponentially (2s, 4s … 30s), whoever
  sends them.

Not covered: typing the passphrase where the agent can read it, or handing the
agent the browser tab that holds the token. Nor a caller that makes its own
REST calls with the session id: `GET /api/session` and the connection list
still give a locked connection's name, type and database list, because a tab
needs them to ask for the passphrase.

## Sessions & reconnecting

Each **session** has one active connection, so two tabs can sit on two
different connections and databases at once. Saved connections themselves are
shared; the *active* one is per session. See [session.md](./session.md); how
the session's row records it is in
[sessions.md](../designs/sessions.md#how-it-is-stored).

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

A session with no connection is disconnected, and stays that way across
restarts.

To open a **specific** connection on load, pass `…/?connection=<name>`
(equivalent to clicking its card); the SPA then cleans the URL so a later reload
resumes normally.
