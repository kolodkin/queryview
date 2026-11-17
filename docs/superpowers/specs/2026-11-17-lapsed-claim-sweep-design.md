# Lapsed-claim sweep

An unnamed session whose tab died without releasing it is never deleted. It
sits in the session dropdown as **Session <n>** until someone presses its **×**.

## Why

The sweep (`_sweep` in `sessions.py`, run on every claim) deletes an unnamed
session only when it is **unclaimed** and idle for a claim TTL (90 s). A tab
that closes normally beacons a release, so its session is unclaimed and goes
within two minutes. A tab that is killed (a crashed browser, a test runner,
a lost laptop) never releases: the row keeps its tab token with a stale
`claim_seen_at`, and the sweep skips it on purpose, so a sleeping laptop's tab
can wake and find its draft.

The two cases are indistinguishable at the server, so the only way to tell
them apart is time: a tab that has not been heard from in a day is not coming
back for its scratch.

## Goals

- An unnamed session is gone within a day of its tab's last heartbeat,
  released or not.
- A sleeping tab that wakes within that day still finds its session.
- Named sessions are untouched: they never expire.

## Non-goals

- Changing the claim TTL or the release path.
- Deleting named sessions, ever.
- A background timer: the sweep stays on the claim path, as today.

## Design

### Backend

- `SESSION_LAPSE_GRACE_MS = 24 * 60 * 60 * 1000` beside `SESSION_CLAIM_TTL_MS`
  in `sessions.py`.
- `_sweep` deletes an unnamed row when **either** holds:
  - unclaimed and `last_active_at` older than the claim TTL (today's rule);
  - claimed and `claim_seen_at` older than the grace.
- Nothing else changes: `forget_session` runs for the swept ids as today, and
  a tab that wakes after the grace attaches as a new tab does (`attach` already
  falls through when its id is gone).

### Docs

- `session.md`, "Refresh, new tabs, and the claim": the kept-it-may-wake
  sentence gains the grace: kept for a day, then swept.

## Tests

- Backend, `test_sessions.py`: `test_a_lapsed_unnamed_claim_is_not_swept`
  becomes two checks on one row: kept with `claim_seen_at` one grace minus a
  second ago, swept one grace plus a second ago. A named row with the same
  stale claim stays.

## Left to the builder

- Nothing: one constant, one `or_` in the delete, one sentence.
