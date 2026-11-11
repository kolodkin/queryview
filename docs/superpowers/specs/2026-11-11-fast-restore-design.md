# Fast restore

Restoring a session whose connection is slow or unreachable shows **Restoring
session…** for the whole query timeout (30 s by default, up to the session's
**Query timeout**), then lands on Connect as if the session were disconnected,
with no word on why.

## Why

Opening the app awaits two things before anything renders: the attach, and
`/api/session`, which rebuilds the session's live driver state by listing the
connection's databases (`SHOW DATABASES`, `pg_database`). The listing borrows
the query timeout as its connect timeout. A sleeping or firewalled server
therefore costs a blank tab for the full timeout, and the failure is reported
as `connected: false`, indistinguishable from "never connected".

## Goals

- The shell renders as soon as the attach answers: header, session, the page
  the session was on.
- The reconnect probe runs in the background with its own short budget.
- A probe that fails says which connection and why, and leaves the session's
  connection in place to retry, as today.

## Non-goals

- Caching the database list on the session row. A stale list would show
  databases that are gone and hide new ones; the probe stays live.
- Changing the query timeout setting or its bounds.
- The `?connection=<name>` deep link keeps awaiting its open: the user asked
  for that connection, and a Connect card is the right place to wait.

## Design

### Backend

- `PROBE_TIMEOUT_SECONDS = 5` in `connect.py`. The rebuild in
  `_ensure_session` runs its database listing under
  `min(query_timeout, PROBE_TIMEOUT_SECONDS)`; both drivers already read the
  context var for their connect timeout, so no driver changes. User-initiated
  opens (`/api/db/open`, `/connect`) keep the full timeout: a user who clicked
  a card is waiting on purpose.
- A rebuild that fails is remembered on the session's cache entry for the
  request, and `/api/session` returns
  `{"connected": false, "name": "<connection>", "error": "<message>"}`.
  A session with no connection keeps returning `{"connected": false}`.
  The next request on that session probes again, as today.

### Frontend

- The bootstrap awaits the attach only. `sessionChecked` flips, the shell
  renders, and `refreshConnection()` runs without being awaited when the
  row names a connection.
- `connection` gains a third state while that probe is out:
  `{ probing: true, name }`. `withDatabase` renders a
  `Loading` with **Connecting to <name>…** instead of redirecting to Connect,
  and the header pill shows the name dimmed.
- When the probe answers:
  - connected: the view mounts as it does today.
  - `error`: navigate to `/connect` and toast **Couldn't reach <name>: <error>**.
    The card is still highlighted as the session's connection; clicking it
    retries with the full timeout.
- A tab the agent opened (`new_tab`) has no connection on its row, so arming
  on attach is unchanged.

### Docs

- `connect.md` "Sessions & reconnecting": the probe budget and the failure
  toast.
- `api.md`: the `error` field on `/api/session`.

## Tests

- Backend: `_ensure_session` lists databases under the capped timeout (a stub
  driver records `query_timeout.get()`), and a failed listing surfaces as
  `name` + `error` on `/api/session`.
- Frontend unit: none; the probing state is React wiring.
- e2e: a session on a connection to a closed port renders the shell, then
  lands on Connect with the toast, within the probe budget. The user's
  Studio text from before the restart is still there.

## Left to the builder

- Whether `Loading` or a smaller inline spinner fits the view area.
- Exact wording of the toast.
