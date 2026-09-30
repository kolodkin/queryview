# QueryView — the Connect page

The Connect page (`/connect`) is where a disconnected session lands: a card per
saved connection and a "new connection" card per driver. The other pages are
`/queries` (redirects here until a database is selected), `/explorer` (see
[explorer.md](./explorer.md)) and `/dashboard` (see
[dashboard.md](./dashboard.md)). The old `/prompt` URL redirects here.

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

- **Saved connections** — most recent first: driver monogram, name, last
  database, last used; the active one has a green dot. Clicking opens it: the
  database picker (last-used database highlighted), or the explorer for a
  picker-less driver (DuckDB).
- **New connection** — a card per driver, and the same entries in the **+ New**
  menu; either opens that driver's form in place (see
  [connect.md](./connect.md)).
- **Many connections** — past six, the page reorganizes
  (`savedConnections.ts`):
  - the three most recent sit in a **Recent** row; the rest scroll in a
    height-capped **All connections** box, so the page never grows;
  - a **search** box (`/` focuses it) matches every typed term against name,
    driver and last database, with an "N of M" count; arrow keys move a
    highlight across the results and Enter opens the highlighted card;
  - **driver chips** (with counts) narrow to one driver;
  - the new-connection cards are hidden; **+ New** remains.
- **← Connections** — on the form and the picker; back to the cards.
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
