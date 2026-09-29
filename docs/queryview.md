# QueryView — the Connect page

QueryView's Connect page (`/connect`) is where a disconnected session lands:
cards for every saved connection and one "new connection" card per driver,
centered, with nothing else on the page. It stays reachable once connected
(e.g. to switch connections). Once a database is selected, `/queries` shows the
query panel; before that it redirects to `/connect`. Two more top-level pages
exist: `/explorer`, the classical table navigator (see
[explorer.md](./explorer.md)), and `/dashboard`, which renders agent-authored
dashboards (see [dashboard.md](./dashboard.md)); a corner nav switches between
them, and the connection status pill persists across all of them. This doc
describes the Connect page. `/prompt`, its name before the command prompt was
retired, redirects here.

## Layout

```
┌───────────────────────────────────────────────────────────┐
│ 🟢 connected - default   ← connection status               │
│                                                           │
│                        QueryView                          │
│                   Choose a connection                     │
│  SAVED CONNECTIONS                          [Filter…]     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │ CH prod-ch 🟢 │ │ PG warehouse │ │ DK local     │       │
│  │ default  2 h │ │ sales   3 d  │ │ —      just  │       │
│  └──────────────┘ └──────────────┘ └──────────────┘       │
│  NEW CONNECTION                                           │
│  [CH ClickHouse +] [PG Postgres +] [DK DuckDB +]           │
└───────────────────────────────────────────────────────────┘
```

- **Saved connections** — one card per saved connection, most recently used
  first: the driver's monogram, the name, the database it was last on and how
  long ago it was used. The session's active connection carries a green dot.
  Clicking a card opens it: a driver with a database picker swaps the cards for
  the picker (the last-used database highlighted), a picker-less one (DuckDB)
  goes straight to the explorer. Past six connections a **filter** box appears;
  Enter opens the first match.
- **New connection** — one card per driver; clicking it opens that driver's
  form in place (see [connect.md](./connect.md)).
- **← Connections** — the form and the picker both carry it, back to the cards.
- **Connection status** — the one element that persists across every page: a
  pill in the **top-left** corner, hidden until a database is selected, then
  showing 🟢 `connected - <database>` (just the database below `md` width).
  Clicking it opens a searchable database switcher; each row's **copy** icon
  copies the name without switching, and **Disconnect** at the bottom drops the
  connection and goes to `/connect` (a picker-less driver's menu is just that).
  Next to it, an **agent icon** opens the remote-control popover (opt-in "Allow
  remote control"); see [remote.md](./remote.md).
- **Narrow windows** — below `md` the cards stack in one column, the session,
  workspace and page links collapse into one **☰ &lt;page&gt;** menu, and
  full-height pages keep a 48rem minimum width, scrolling sideways rather than
  squeezing.
- **Popovers** — dropdowns and their panels close on a click outside or on
  Escape. Panels holding unsaved input are the exception: the workspace manage
  form once edited, and the cell-view editor, close through their own buttons.

## Sessions

A **session** is one tab's working state — the page and URL, the connection and
database, the workspace, the query panel — persisted in SQLite and restored on
refresh. One tab holds a session at a time: a new tab resumes your last one, or
starts its own if another tab is already using it. A dropdown in the top-right
nav switches between them. See [session.md](./session.md).

## Landing page

A live connection lands on the **explorer**, not the Connect page — there are tables
to browse (see [explorer.md](./explorer.md)).

- **Opening the app** (`/`) waits for the session to attach, then goes where
  that session left off. A session with no remembered URL lands on `/explorer`
  for a ready connection and `/connect` otherwise. Only `/` chooses: a deep link
  to a page is honored as typed, and becomes the session's URL.
- **Connecting** — picking a database (or connecting a picker-less driver)
  navigates from the connect handler itself. Nothing watches the connection, so
  the nav gets back to Queries, a pill database switch stays put, and an
  agent's query push is not pulled away.

## Design principles

- **Click, don't type.** Every connection is a card; nothing needs a name
  remembered or a command learned.
- **One thing at a time.** The cards, a form or a picker — never two at once.
- **State is visible.** Once a database is selected, the top-left indicator
  makes the active connection and database obvious from anywhere.
- **Resumable.** A session restores where you left off — page, connection and
  query — so a refresh costs nothing and the common case needs no typing at all.
