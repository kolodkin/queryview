# Agent tabs: a browser tab per push — design

An agent working in a QueryView session can put something in front of the user
only by filling that session's one tab: its Scripts editor, its Studio query
panel, its dashboard, its Explorer. This design lets it open **several browser
tabs side by side, each with its own script, query, dashboard or table**, by
spawning a child session per tab from the session it is on.

## Why

A session is one browser tab's state ([session.md](../../session.md)): the
claim, the **Use it here** guard on a taken session, and the `ui` blob with one
`scripts.sql` all assume one tab. Two tabs on one session would overwrite each
other's script. Letting a session hold several tabs would need per-tab state
inside the session, which is a session by another name. So the unit stays the
session, and the agent gets more of them.

## Goals

- An agent pushes N things and the user sees N browser tabs, each on the
  page the push targets (Scripts, Studio, a dashboard, the Explorer), all on
  the agent's connection and database.
- Re-pushing to a tab updates that tab in place.
- The tabs clean themselves up: closing them is enough.
- No new consent: arming the parent session is the consent for its tabs.

## Non-goals

- Tabs inside a page (an editor with several named scripts).
- Results or history per tab beyond what a session already keeps.

## Anti-goals

- A child outliving its tab by default, so the session list fills with
  `orders`, `orders (2)`, …
- A pending push persisted in a session and replayed on every reload (the
  reason a push to a closed page is refused rather than queued today). A push
  parked for a tab that is opening is in memory, delivered once, and dropped
  if the tab never arms.
- A new tab that hijacks the parent's session. `window.open` copies
  `sessionStorage`, so the new tab starts with the parent's `qv_tab` and
  `qv_session`; an attach with those would reclaim the parent.

## Constraints

- A browser blocks a window the page opens without a user gesture, and an
  SSE event is not one.
- Session connections the agent added live in memory keyed by session id
  (`connect.py`); a child on such a connection cannot find it by its own id.
- The push layer never talks to the database; a child must be usable through
  the same `/api/*` paths as any session.

## The tools

Every tool that pushes into a browser — `push_script`, `push_query`,
`push_dashboard`, `open_explorer` — gains `tab=None`, a name. Without it
nothing changes. With it:

1. **Resolve the child**: the session whose `parent` is `session_id` and whose
   `label` is `tab`, created if missing with the parent's connection,
   database and workspace. `(parent, label)` is unique. The tool's own checks
   (`not connected`, `select a database first`, an unlisted table) run against
   the child, which has the same connection and database.
2. **Deliver** the tool's usual payload:
   - child armed (its tab is open) → `remote.push` to the child's channel,
     exactly as a push to any armed session; `blocked, user editing` applies.
   - child not armed → **park** the payload for the child in `remote.py`
     (in memory, one payload per child, the newest wins, dropped after 60 s),
     and `remote.notify` the **parent's** channel a `tab` event
     `{type: "tab", session, label, url}` with
     `url = /?session=<child>&armed=1`. The parent tab opens it; when the new
     tab arms, `remote.register` hands the parked payload to its channel
     first, and the tab navigates to the pushed page as it would for any
     push. No per-tool state is written into the child's row and nothing
     replays on reload.
   - parent not armed → `unknown or inactive session`, as for any push.
3. **Reply** the tool's usual shape plus `tab_session`, the child's id, usable
   with every session-scoped tool.

## The child session

- A row in `sessions` with a new nullable `parent` column (Alembic revision)
  and `label` = the tab name. The switcher shows it as **Agent › orders**
  (parent label, `›`, name); the browser tab's title is the name.
- Scratch: `_sweep` deletes it once it is unclaimed and idle for a claim TTL,
  the rule unnamed sessions already follow. `_unheld_query` never resumes it
  in a new tab. Not renamable (the name is the agent's key); deletable when
  not held.
- Deleting a parent that still has children is refused like a held session
  (`held`); they go when their tabs close.
- Session connections: the lookup `_session_conn(sid, name)` falls back to
  the parent's entry, so a child opens on a connection the agent added to the
  parent. The child's own in-memory active connection is built from its row
  by `_ensure_session`, as for any session.
- Any armed session can be a parent. A child is never a parent (a push with
  `tab` to a child is refused: `a tab can't have tabs`).

## The browser

- **Opening**: on the `tab` event the parent tab calls
  `window.open(url, session)` (the child's id as the window name, so a second
  open of the same child focuses it). When the browser returns `null`, a toast
  **Agent opened orders** with an **Open** button appears; the click opens it.
  The docs tell the user that allowing pop-ups for QueryView's origin removes
  the click.
- **Attaching**: a page that loads with `?session=` mints a fresh tab token
  before anything else, writes the id to `qv_session`, and attaches as that
  tab. `attach` claims the child because it is unheld. The page then strips
  `session` and `armed` from the URL with `history.replaceState`, so a reload
  is an ordinary reload.
- **Arming**: `armed=1` sets the arm toggle on at mount; the popover shows the
  child's id like any armed session. The SSE channel then delivers the parked
  payload, and the tab lands on the pushed page the way an armed tab does.

## Docs that change when it ships

`remote.md` (the `tab` argument on each tool, the `tab` event and parking
under "How it works"), `session.md` ("The Agent session" gains the child rules
and the `parent` column), `scripts.md` ("Agent pushes"), `dashboard.md`,
`query.md` and `explorer.md` where they describe their push, `api.md` if any
endpoint shape changes. This file is deleted in the same change.

## Left to the builder

- The exact `›` rendering and ordering of children in the session switcher
  (under their parent, or by activity like every other row).
- Where the parked payload lives in `remote.py` and how its 60 s expiry runs.
- Test layout per the project `testing` skill: store rules in
  `test_sessions.py`, the tools in `test_mcp_connections.py` or a sibling, the
  browser flow in `e2e/remote.spec.ts` with Playwright's `context.waitForEvent('page')`.
