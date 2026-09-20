# QueryView — single-prompt page concept

QueryView's main page (`/queries`) is one centered prompt — the user types a
command and the page reacts to it inline; no sidebar, no toolbars. Two more
top-level pages exist: `/explorer`, the classical table navigator (see
[explorer.md](./explorer.md)), and `/dashboard`, which renders agent-authored
dashboards (see [dashboard.md](./dashboard.md)); a corner nav switches between
them, and the connection status pill persists across all three. This doc
describes the prompt page.

## Layout

```
┌─────────────────────────────────────────────┐
│ 🟢 connected - default   ← connection status  │
│                                               │
│                  QueryView                    │
│        ┌─────────────────────────────┐        │
│        │  Type a command…            │  ← prompt
│        └─────────────────────────────┘        │
│                                               │
│        (each mode renders its UI here)        │
│                                               │
└─────────────────────────────────────────────┘
```

- **Heading** — `QueryView`, centered.
- **Prompt** — a single centered, auto-focused text input. Enter interprets the
  typed text as a command.
- **Inline response** — each command renders its own UI directly under the
  prompt (e.g. the connection form and database picker — see
  [connect.md](./connect.md)). The prompt stays in place; the page does not
  navigate.
- **Connection status** — the one element that persists across every mode: a
  pill in the **top-left** corner, hidden until a database is selected, then
  showing 🟢 `connected - <database>`. Next to it, an **agent icon** opens the
  remote-control popover (opt-in "Allow remote control"); see
  [remote.md](./remote.md).
- **Popovers** — dropdowns and their panels close on a click outside or on
  Escape. Panels holding unsaved input are the exception — the workspace manage
  form and the cell-view editor close through their own buttons.

## Sessions

A **session** is one tab's working state — the page and URL, the connection and
database, the workspace, the query panel — persisted in SQLite and restored on
refresh. One tab holds a session at a time: a new tab resumes your last one, or
starts its own if another tab is already using it. A dropdown in the top-right
nav switches between them. See [session.md](./session.md).

## Landing page

A live connection lands on the **explorer**, not the prompt — there are tables
to browse (see [explorer.md](./explorer.md)).

- **Opening the app** (`/`) waits for the session to attach, then goes where
  that session left off. A session with no remembered URL lands on `/explorer`
  for a ready connection and `/queries` otherwise. Only `/` chooses: a deep link
  to a page is honored as typed, and becomes the session's URL.
- **Connecting** — picking a database (or connecting a picker-less driver)
  navigates from the connect handler itself. Nothing watches the connection, so
  the nav gets back to Queries, a pill database switch stays put, and an
  agent's query push is not pulled away.

## Commands

| Command          | Effect                                              |
| ---------------- | --------------------------------------------------- |
| `new clickhouse` | Reveals the form to create a new ClickHouse connection. |
| `connect <name>` | Opens the saved connection `<name>` and shows its database picker. |
| `query`          | Returns to the query panel from a connection form — a ready session shows it already: run SQL with pagination, save/load predefined queries, download CSV (see [query.md](./query.md)). |
| `explorer`       | Once a database is selected, opens the table navigator (`/explorer`) — browse tables without typing SQL (see [explorer.md](./explorer.md)). |
| `dashboard`           | Opens the dashboard page (`/dashboard`) — pick a saved dashboard from the dropdown. |
| `dashboard <name>`    | Opens the dashboard page at that dashboard (`/dashboard?name=<name>`). See [dashboard.md](./dashboard.md). |

Anything else shows a hint listing the commands above.

Command matching is case-insensitive and trims surrounding whitespace. See
[connect.md](./connect.md) for the full connection flow.

## Design principles

- **One thing at a time.** The prompt is the only persistent control. Each
  command owns the space beneath it.
- **No dead ends.** Unknown input is guided, never punished.
- **State is visible.** Once a database is selected, the top-left indicator
  makes the active connection and database obvious from anywhere.
- **Resumable.** A session restores where you left off — page, connection and
  query — so a refresh costs nothing and the common case needs no typing at all.
