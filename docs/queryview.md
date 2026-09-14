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
- **Popovers** — every header dropdown and panel (database, workspace, agent,
  git revisions) and the prompt's suggestion list close on a click outside them
  or on Escape.

## Sessions

The active connection is **session state**, not global UI state: each browser
session has its own active connection, held at the backend and keyed by a
cookie; saved connections are shared (SQLite). See [connect.md](./connect.md).

On load the SPA either:

- **resumes the latest active connection** (`GET /api/session`) — opening already
  connected, with the previously selected database pre-selected; or
- **opens a specific connection** when the URL has `?connection=<name>`.

If neither yields a connection it opens at the empty prompt.

## Commands

| Command          | Effect                                              |
| ---------------- | --------------------------------------------------- |
| `new clickhouse` | Reveals the form to create a new ClickHouse connection. |
| `connect <name>` | Opens the saved connection `<name>` and shows its database picker. |
| `query`          | Once a database is selected, opens the query panel — run SQL with pagination, save/load predefined queries, download CSV (see [query.md](./query.md)). |
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
- **Resumable.** Sessions reconnect to the last active connection on start, so
  the common case needs no typing at all.
