# Sessions as persistent UI state — design

A QueryView **session** becomes a first-class, persisted, selectable unit of UI
state: route and URL, connection and database, query-panel state and workspace.
It survives a browser refresh, is restored when a new tab opens with no other
tab holding it, and is switchable from a dropdown.

## Why

Today "session" is a thin, implicit thing: an in-memory map in `connect.py`
keyed by an `HttpOnly` `qv_session` cookie, holding only the active connection
and selected database.

Three consequences motivate the change:

- **A refresh loses your work.** SQL text, limit/offset, the column picker and
  sort are `useState` in `QueryView.tsx`. Nothing outside the URL survives.
- **Tabs fight.** The cookie is per *browser*, so every tab shares one active
  connection. Two tabs on two databases is impossible.
- **The session dies with the backend.** State is in memory only, while
  connections, workspaces, queries and dashboards are all in SQLite.

## Model

One session = one browser tab's working state. Exactly one tab holds a session
at a time; sessions outlive the tabs that held them.

### Schema

A new `sessions` table, owned by a new `backend/queryview/sessions.py` module
alongside `connect.py` and `workspaces.py`, with an Alembic revision:

```sql
CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,   -- uuid4 hex
  seq             INTEGER NOT NULL,   -- stable ordinal for the "Session 3" fallback label
  label           TEXT,               -- NULL = auto-derived; set = user-pinned name
  connection_name TEXT,               -- NULL is the durable "disconnected" state
  database        TEXT,
  workspace       TEXT NOT NULL DEFAULT 'default',
  url             TEXT NOT NULL DEFAULT '/queries',  -- path + search
  ui              TEXT NOT NULL DEFAULT '{}',        -- JSON, namespaced by view
  claimed_by      TEXT,               -- tab token, NULL = free
  claim_seen_at   INTEGER,            -- unix ms of last heartbeat
  last_active_at  INTEGER NOT NULL
);
```

`ui` is a JSON blob rather than columns for the same reason `connections.config`
is one: a view can remember a new setting without a migration. It keeps the
view-namespaced shape the old `viewSettings.ts` used:

```json
{"query": {"sql": "…", "limit": 100, "offset": 0, "visibleCols": [], "orderBy": []},
 "explorer": {"sidebarWidth": 256}}
```

Query text is stored in plaintext, consistent with predefined queries; only
connection configs are encrypted, and nothing here holds credentials.

### One store, one path

`localStorage` is removed from the app entirely — the session row supersedes it,
and keeping both would mean two stores for one concept.

| Today | After |
| --- | --- |
| `viewSettings.ts` (`qv_view_<view>` keys) | deleted, with its test — the `ui` blob replaces the key convention |
| `workspace.ts` `activeWorkspace()` / `setActiveWorkspace()` (`qv_workspace`) | accessors deleted; the module keeps only its `/api/workspaces` client |
| `explorerSettings.ts` | keeps its clamp logic; reads/writes through `session.ts` instead of `viewSettings.ts` |
| `testStorage.ts` (the localStorage fake) | deleted — no consumers remain |
| `e2e/test_workspaces.py:43`, `e2e/test_explorer.py:155` (assert on localStorage keys) | rewritten against session state |

The resulting rule, stated in `docs/session.md`:

> `sessionStorage` holds identity (`qv_tab`, `qv_session`). The server holds
> state. No browser storage holds anything durable.

There is deliberately **no one-time carry-over** of the old `qv_workspace` /
`qv_view_explorer` values: reading keys we are deleting reintroduces the
duplication one layer down. On upgrade the active workspace resets to `default`
and the explorer sidebar to its default width, once.

`sessionStorage` can throw (private windows, blocked site data), so `session.ts`
wraps both keys in try/catch with an in-memory fallback: the tab works normally
for its lifetime, it just cannot re-attach after a refresh. This replaces the
`stubBrokenStorage` handling being deleted.

## Claim protocol

Two `sessionStorage` keys: `qv_tab`, a token minted per tab, and `qv_session`,
the attached session id. Both survive a refresh; neither crosses to a new tab.
That is the refresh-vs-new-tab discriminator, and it is why a refresh can never
reset the session.

A session is **held** when `claimed_by` is set *and* `claim_seen_at` is within a
30s TTL. The tab heartbeats every 10s, which is just a repeat `attach` — no
separate endpoint.

`POST /api/sessions/attach {tab, session_id?}` resolves everything server-side
in one decision, so there is no client-side race:

1. `session_id` given, and free or already this tab's → re-claim it.
   *(refresh, heartbeat)*
2. `session_id` given but held by a **different** live tab → fall through to 3.
   *(tab duplication: Chrome copies `sessionStorage`, so it must not hijack)*
3. Otherwise the **unheld** session with the greatest `last_active_at` →
   claim it. *("restore last session if none is active")*
4. Otherwise create one. *("otherwise open a new session")*

`pagehide` fires a `sendBeacon` release; the TTL is the backstop for a tab that
crashed or was killed.

## API

```
POST   /api/sessions/attach   {tab, session_id?}   -> {session, created}
POST   /api/sessions/select   {tab, id|null}       -> switch; null creates a new one; refuses a held id
GET    /api/sessions                               -> rows for the dropdown, each with label + held
PATCH  /api/sessions/{id}     {url?, ui?, label?, workspace?}
DELETE /api/sessions/{id}                          -> refuses while held
POST   /api/sessions/release  {tab}
```

Connection and database are deliberately **not** in `PATCH`: the existing
`/api/db/connect|open|database` endpoints write through to the session row, so
connection changes keep one path.

The `qv_session` **cookie is removed**. The frontend sends `X-QV-Session: <id>`
on every `/api/*` call; the middleware reads it into `request.state.sid`, and
session-scoped endpoints return the existing `no-session` error shape when it is
absent. Inside `connect.py` the parameter stays named `sid` and keeps its
meaning, so the churn there is contained:

- `_sessions` becomes a live-driver cache (decrypted config + database list),
  rebuilt lazily from the session row rather than from "latest active".
- `_disconnected` is **deleted** — `connection_name IS NULL` expresses the
  disconnected state durably.
- A `connection_name` naming a connection that was since deleted, or whose
  config no longer decrypts, resolves to disconnected — the same fallback
  `_row_to_stored` already takes today. The session is not repaired or
  repointed; the user reconnects.

## The agent channel

The remote-control channel is keyed by the session id instead of a random
per-arm `secrets.token_hex(8)`. The old id existed so the `HttpOnly` cookie
would never reach the agent; under this design the session id is an identifier,
not a credential — JS reads it and sends it as a plain header — so that reason
no longer applies.

This removes a mirror the UI had to keep in sync, because the channel can now
read the session row directly:

- `POST /api/remote/db` — deleted
- `_Channel.database`, `_Channel.workspace` and their four accessors in
  `remote.py` — deleted
- the `useEffect` in `App.tsx` that re-reported on every arm / database /
  workspace change — deleted

`GET /api/remote/events` takes the id from `request.state.sid` (the
`X-QV-Session` header the browser already sends), so `register()` needs no new
parameter from the client and the SSE `ready` event still carries the id the
popover displays. `sessionLock.ts` is unchanged in shape — it keeps posting a
`session_id`, which is now the session's own id rather than `remoteId`.

`remote.py` keeps only push-hub concerns (queue, SSE, advisory edit lock);
`mcp_server.py` resolves database and workspace from `sessions.py` directly,
which also keeps the async DB access out of the synchronous hub.

**Arming remains the gate.** `register(session_id)` creates the channel, disarm
unregisters it, and a push to an unarmed session still fails with the existing
`unknown or inactive session`. What changes is rotation: the id is now stable
across refreshes and re-arms, so the copied agent command stops changing under
the user — and an id shared once stays valid whenever that session is armed.

## Frontend

- **`session.ts`** (new): tab token, attach/heartbeat/release, a debounced
  `patch()` (400ms for SQL text; immediate for discrete events such as
  navigation or a database switch), and the in-memory mirror the views read.
- **`controls/SessionSwitcher.tsx`** (new): modelled on `WorkspaceSwitcher.tsx`
  — the same `glass-popover` + `useDismiss` idiom. Rows show the label, a badge
  on sessions held by another tab (selecting one is refused, since two tabs on
  one session would fight over its state), inline rename, `×` to delete, and
  "New session". Sits in the top-right nav beside the workspace switcher.
- **`App.tsx`**: attaches before routing, reusing the existing `sessionChecked`
  gate. A tab that opened at `/` navigates to the session's stored `url`; a tab
  opened at an explicit path keeps that path and writes it into the session. A
  `location` effect patches `url` thereafter. `?connection=` keeps working,
  applied to whichever session the tab attached to.
- **`QueryView.tsx`**: `sql`, `limit`, `offset`, `visibleCols` and `orderBy`
  hydrate from the session on mount and patch on change.

**Restoring does not auto-run the query.** Text and pagination come back;
results do not, so a refresh cannot fire an expensive query. The explorer keeps
its current URL-driven auto-fetch, so `/explorer?table=events` does re-load its
rows. The split is consistent: URL-driven views re-run, the free-text SQL panel
does not.

## Labels

Derived at list time: `"<connection> · <database>"`, falling back to the
connection name, then `"Session <seq>"`. A rename sets `label` and pins it.

Deletion is manual only — nothing expires. Rows therefore accumulate: every tab
opened while another holds a session adds one, and the dropdown grows until the
user prunes it. That is the accepted cost of sessions being durable and
nameable rather than a capped history. The in-memory live-driver cache keeps its
existing `MAX_SESSIONS` LRU bound, which is now independent of how many session
rows exist.

## Testing

Tests sit beside the code they test, per `CLAUDE.md`; e2e stays in `e2e/`.

- `backend/queryview/test_sessions.py` — the attach decision table (resume free
  / skip held / re-claim own / create), claim expiry, release, patch round-trip,
  delete-refused-while-held, label derivation.
- `frontend/src/app/session.test.ts` — attach, debounce coalescing, heartbeat,
  release beacon, the `sessionStorage`-throws fallback.
- `e2e/test_sessions.py` — refresh preserves SQL text, URL and database; a
  second tab gets a *different* session; the dropdown switches session and the
  URL and connection pill follow.

Existing backend tests need their request setup moved from the cookie to the
`X-QV-Session` header; `viewSettings.test.ts` and `testStorage.ts` are deleted
and `workspace.test.ts` loses its localStorage-fallback case.

## Docs

- New `docs/session.md` — the doc of record.
- `docs/queryview.md` — rewrite §Sessions and the landing rule.
- `docs/connect.md` — §"Sessions, cookies & auto-connect" is wrong once the
  cookie is gone.
- `docs/api.md` — the §Sessions preamble, the new `/api/sessions/*` rows, and
  the removal of `/api/remote/db`.
- `docs/remote.md` — the agent id is now the session id.
- Per the docs convention in `CLAUDE.md`, this spec is deleted in the same
  change that ships the feature.

## Risks

- The cookie→header switch touches every existing backend test's request setup.
- Lifting `QueryView.tsx` state into a patched store is the largest single edit
  (1289 lines today).

Neither changes the design; both are where the time goes.
