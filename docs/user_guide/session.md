# Sessions

A **session** is one browser tab's working state: the page you are on and its
URL, the connection and database you are querying, your workspace, and the
per-view settings a reload should bring back. It lives in SQLite, so it survives
a browser refresh *and* a backend restart. You switch sessions from the
dropdown in the header on every page; letting an agent into one is in
[mcp.md](./mcp.md).

One tab holds a session at a time. A **named** session outlives the tab that
held it: close the tab and the next one you open picks it back up. An unnamed
one (`Session <n>`) is scratch — it lives only while a tab shows it, and is
deleted once that tab has closed or switched away from it.

> **`sessionStorage` holds identity. The server holds state.** The app uses no
> `localStorage` at all.

## What a session remembers

| | |
| --- | --- |
| Route and URL | `/explorer?table=events`, `/dashboard?name=sales` |
| Connection | the connection this session is on, and its selected database |
| Last visited | per connection, the database (or DuckDB folder) and table it was last on |
| Workspace | which workspace scopes its dashboards and git sync |
| Dashboard | the unsaved **New query** draft: its SQL |
| Scripts | the script text |
| Explorer | the Tables sidebar width |

**Results are not remembered** — a reload restores the SQL you were writing,
never the rows, so reopening a tab cannot re-fire an expensive query. Neither is
the page you were on: an offset is a cursor into a result set that no longer
exists, and restoring one would point a fresh query at nothing. The explorer is
the exception only because it is URL-driven — a restored `?table=` re-loads that
table exactly as following the link would.

Transient state is never written: open popovers, filter text, a drag in
progress, fetched rows.

## Last visited

<!-- req: last-visited -->
Each connection the session has been on keeps the database and table it was
last on. Reopening that connection in the same session — its card on the
Connect page, the pill menu, `?connection=`, an agent's `use_connection` —
goes straight back to them, skipping the picker:

- **Database** — restored if still listed. A DuckDB folder is checked by path
  and falls back to its nearest parent (see
  [explorer.md](./explorer.md#duckdb-folder-mode)); a database no longer
  listed lands on the picker.
- **Table** — the Explorer opens it if it is still in that database. Picking
  another database forgets it. SQLite and a DuckDB file have no database, so
  their entry is the table alone.

Deleting a connection forgets every session's entry for it, so a new
connection reusing the name starts fresh. The record is the session's, not
the connection's: a new session opens a
Postgres or ClickHouse connection on its picker, with the last database used
anywhere highlighted.

## Refresh, new tabs, and the claim

<!-- req: refresh-new-tab -->
What you get:

- **Refresh** → the same session, same page, same everything.
- **New tab while another is open** → a new session; the first tab holds its own.
- **New tab with nothing else open** → your last named session comes back,
  else a new one.

A session is **held** while its tab has been heard from within 90 seconds; a
crashed tab simply stops being heard and frees its session.

An unnamed session is swept 90 seconds after it is both unheld and idle. A
session whose tab still holds its claim but stopped heartbeating (a crash, a
sleeping laptop) is kept — it may wake.

<!-- req: taken-greys-out -->
A running tab is never moved silently. A sleeping laptop or a frozen tab can
still let a claim lapse and another tab take its session: the tab greys out and
stops writing until you pick **Use it here** (the other tab then greys out) or
**New session**. Any session change re-syncs the whole shell.

<!-- req: switch-elsewhere -->
A switch of connection or database made elsewhere (another tab, an API caller)
reaches the tab within a beat, and every view follows — the explorer reloads
its tables, the dashboard and the query panel re-run what is on screen.

How tabs claim, heartbeat and release a session is in
[sessions.md](../designs/sessions.md#claims-and-the-heartbeat).

## The session dropdown

The top-right dropdown lists every session, most recently active first. This
tab's session is highlighted with a ✓ and **this tab**. A session held by
another live tab is shown but not selectable: two tabs on one session would
overwrite each other's state.

<!-- req: new-session -->
- **New session** starts a fresh one in this tab.
  <!-- req: rename -->
- The pencil on this tab's row edits its name in place: Enter or focus-out
  saves, Escape cancels. A name pins the session, so it survives its tab;
  clearing it unpins. `Session <n>` names are refused: they belong to unnamed
  sessions.
- **×** deletes a session; a session a live tab holds (this one included) has none.

An unpinned label is `Session <n>`, with `n` a stable ordinal, so a name never
changes under you when you switch databases. Each row shows the session's
connection and database beside its name.

Named sessions never expire, so the list grows until you prune it — the cost of
sessions being durable and nameable rather than a capped history.

## Sessions and the agent

The id in the agent popover **is** the session id, and an agent pointed at it
acts on that session's connection, database and workspace, read straight from
the row. Arming is still the gate: disarming closes the channel and later pushes
fail with `unknown or inactive session`. Unlike the old per-arm id this one is
stable, so the command you copy stops changing under you. See
[mcp.md](./mcp.md).

## Tabs

A session an agent opened for itself with `new_tab`
([mcp.md](./mcp.md#let-the-agent-open-its-own-tabs)): an unnamed session whose `tab` names the
work, listed as **Agent › orders** until you pin a name on it. Scratch like
any unnamed session: swept once its browser tab has been closed for a claim
TTL, never resumed by a new tab. It has no connection until the agent opens
one on it.

A tab starts from its link, `/?session=<id>`: the browser tab takes that
session as the switcher would (one held elsewhere or gone shows a toast, and
the tab attaches as any new tab does) and drops the parameter from the URL. A
tab session arms itself whenever a browser tab loads it. Any unheld session
opens from such a link.
