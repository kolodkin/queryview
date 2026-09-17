# Session Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a QueryView session a first-class, persisted, selectable unit of UI state — route and URL, connection, database, query-panel state and workspace — that survives a browser refresh, restores into a new tab when no other tab holds it, and is switchable from a dropdown.

**Architecture:** A new `sessions` table in SQLite becomes the single source of truth. Each browser tab mints a token in `sessionStorage` and claims exactly one session; the claim carries a 30s TTL refreshed by a heartbeat. Every `/api/*` request identifies its session with an `X-QV-Session` header instead of the old `qv_session` cookie. `localStorage` is removed from the app entirely, and the agent's remote-control channel is keyed by the session id so the UI no longer mirrors database/workspace into it.

**Tech Stack:** FastAPI + SQLModel + Alembic (aiosqlite) on the backend; React 19 + react-router-dom 7 + Vite on the frontend; pytest for backend and e2e (Playwright), vitest for frontend units.

**Spec:** `docs/superpowers/specs/2026-09-17-session-persistence-design.md` — read it before starting. The plan argues from the spec; where they disagree, the spec wins.

## Global Constraints

- **Python is run through uv.** `uv run --group test pytest backend/queryview` for backend units, `uv run --group test pytest` for e2e. Never `python -m`, never a manually activated virtualenv.
- **Frontend tests:** `npm run test -w frontend` (vitest). Lint: `npm run lint -w frontend`.
- **Tests live beside the code they test** inside the module package (`backend/queryview/test_sessions.py`, `frontend/src/app/session.test.ts`). Only Playwright e2e lives in the top-level `e2e/`.
- **No `__all__`.** Import names where they are defined; package `__init__` keeps no export list.
- **No AI-attribution trailers** in commit messages — no `Co-Authored-By: Claude`, no `Claude-Session:`. This repo's `CLAUDE.md` forbids them.
- **Never commit tenant data.** Invented generic names only (`sales_reporting`, `events`, `example.internal`) in tests, fixtures, docs and commit messages.
- **Line length 120** (ruff, `pyproject.toml`); target `py311`.
- **Alembic owns the schema.** The new revision chains from `c7d8e9f0a1b2` (current head). Migrations ship inside the package.
- **Claim TTL is 30_000 ms; heartbeat interval is 10_000 ms.** Copy these exact values.
- **Debounce for UI-state patches is 400 ms.** Navigation, database switch and column toggles patch immediately.

---

## File Structure

**Backend**

| File | Responsibility |
| --- | --- |
| `backend/queryview/sessions.py` (new) | The `sessions` table, CRUD, the claim decision, label derivation. No HTTP concerns. |
| `backend/queryview/migrations/versions/d8e9f0a1b2c3_sessions.py` (new) | Creates the table. |
| `backend/queryview/test_sessions.py` (new) | Unit tests for the store and claim protocol. |
| `backend/queryview/main.py` | `X-QV-Session` middleware; the `/api/sessions/*` endpoints; drops `/api/remote/db`. |
| `backend/queryview/connect.py` | `_sessions` becomes a live-driver cache seeded from session rows; `_disconnected` deleted; connect/open/select write through. |
| `backend/queryview/remote.py` | Channel keyed by session id; the database/workspace mirror deleted. |
| `backend/queryview/mcp_server.py` | Resolves database/workspace from `sessions.py`. |

**Frontend**

| File | Responsibility |
| --- | --- |
| `frontend/src/app/tabStorage.ts` (new) | The only `sessionStorage` touchpoint: `qv_tab` and `qv_session`, with an in-memory fallback. |
| `frontend/src/app/api.ts` (new) | `apiFetch` — injects `X-QV-Session` on every `/api/*` call. |
| `frontend/src/app/session.ts` (new) | Attach/heartbeat/release, the in-memory session mirror, debounced patches. |
| `frontend/src/app/controls/SessionSwitcher.tsx` (new) | The dropdown. |
| `frontend/src/app/App.tsx` | Attach gate, URL restore/patch, workspace from session, `remoteId` = session id. |
| `frontend/src/app/QueryView.tsx` | Query-panel state hydrates from and patches to the session. |
| `frontend/src/app/explorerSettings.ts` | Reads/writes through `session.ts`. |
| `frontend/src/app/viewSettings.ts`, `testStorage.ts` (+ their tests) | **Deleted.** |
| `frontend/src/app/workspace.ts` | localStorage accessors deleted; keeps the `/api/workspaces` client. |

**Ordering note.** Tasks 1–5 are backend, 6–10 frontend, 11 cleanup + e2e + docs. Task 3 keeps the `qv_session` cookie as a fallback so the app stays runnable at every commit; Task 11 removes it once the frontend sends the header.

---

### Task 1: Session store — model, migration, CRUD

**Files:**
- Create: `backend/queryview/sessions.py`
- Create: `backend/queryview/migrations/versions/d8e9f0a1b2c3_sessions.py`
- Test: `backend/queryview/test_sessions.py`

**Interfaces:**
- Consumes: `connect._engine_for_db`, `connect._ensure_schema`, `connect._now_ms` (existing helpers in `backend/queryview/connect.py`).
- Produces:
  - `SESSION_CLAIM_TTL_MS: int = 30_000`
  - `class Session(SQLModel, table=True)` with `__tablename__ = "sessions"`
  - `@dataclass SessionRec` — `id: str`, `seq: int`, `label: str | None`, `connection_name: str | None`, `database: str | None`, `workspace: str`, `url: str`, `ui: dict[str, Any]`, `held: bool`, `last_active_at: int`
  - `async def create_session() -> SessionRec`
  - `async def get_session_rec(sid: str) -> SessionRec | None`
  - `async def list_sessions() -> list[dict[str, Any]]`
  - `async def patch_session(sid: str, *, url: str | None = None, ui: dict[str, Any] | None = None, label: str | None = None, workspace: str | None = None) -> bool`
  - `async def delete_session(sid: str) -> tuple[bool, str]`
  - `def display_label(rec: SessionRec) -> str`

- [ ] **Step 1: Write the failing tests**

Create `backend/queryview/test_sessions.py`:

```python
"""Session store: rows persist UI state, labels derive from connection state,
and a held session refuses deletion."""

from __future__ import annotations

import asyncio

from queryview import sessions


def _run(coro):
    return asyncio.run(coro)


def test_create_assigns_increasing_seq():
    a = _run(sessions.create_session())
    b = _run(sessions.create_session())
    assert b.seq == a.seq + 1
    assert a.id != b.id


def test_new_session_defaults():
    rec = _run(sessions.create_session())
    assert rec.connection_name is None
    assert rec.database is None
    assert rec.workspace == "default"
    assert rec.url == "/queries"
    assert rec.ui == {}
    assert rec.held is False


def test_patch_round_trips_url_and_workspace():
    rec = _run(sessions.create_session())
    assert _run(sessions.patch_session(rec.id, url="/explorer?table=events", workspace="reporting"))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    assert again.url == "/explorer?table=events"
    assert again.workspace == "reporting"


def test_patch_ui_merges_per_view_and_keeps_unknown_keys():
    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, ui={"query": {"sql": "SELECT 1", "limit": 100}}))
    _run(sessions.patch_session(rec.id, ui={"query": {"limit": 50}, "explorer": {"sidebarWidth": 412}}))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    # The view namespace merges; the untouched sibling key survives.
    assert again.ui["query"] == {"sql": "SELECT 1", "limit": 50}
    assert again.ui["explorer"] == {"sidebarWidth": 412}


def test_patch_unknown_session_returns_false():
    assert _run(sessions.patch_session("nope", url="/queries")) is False


def test_delete_removes_the_row():
    rec = _run(sessions.create_session())
    ok, _ = _run(sessions.delete_session(rec.id))
    assert ok
    assert _run(sessions.get_session_rec(rec.id)) is None


def test_label_prefers_connection_and_database():
    rec = _run(sessions.create_session())
    rec.connection_name, rec.database = "reporting", "events"
    assert sessions.display_label(rec) == "reporting · events"


def test_label_falls_back_to_connection_then_seq():
    rec = _run(sessions.create_session())
    rec.connection_name, rec.database = "reporting", None
    assert sessions.display_label(rec) == "reporting"
    rec.connection_name = None
    assert sessions.display_label(rec) == f"Session {rec.seq}"


def test_explicit_label_wins():
    rec = _run(sessions.create_session())
    rec.label, rec.connection_name, rec.database = "nightly audit", "reporting", "events"
    assert sessions.display_label(rec) == "nightly audit"


def test_list_returns_display_label_and_held_flag():
    rec = _run(sessions.create_session())
    rows = _run(sessions.list_sessions())
    row = next(r for r in rows if r["id"] == rec.id)
    assert row["label"] == f"Session {rec.seq}"
    assert row["held"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --group test pytest backend/queryview/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'queryview.sessions'`

- [ ] **Step 3: Write the migration**

Create `backend/queryview/migrations/versions/d8e9f0a1b2c3_sessions.py`:

```python
"""sessions: persistent per-tab UI state (route, connection, query panel)

Creates the 'sessions' table. Nothing is backfilled: the previous session
concept was in-memory only, so there is no prior state to carry forward.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("connection_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("database", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("workspace", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ui", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("claimed_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("claim_seen_at", sa.Integer(), nullable=True),
        sa.Column("last_active_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_last_active_at"), "sessions", ["last_active_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sessions_last_active_at"), table_name="sessions")
    op.drop_table("sessions")
```

- [ ] **Step 4: Write the store**

Create `backend/queryview/sessions.py`:

```python
"""Session domain: a browser tab's persisted UI state — route and URL, active
connection and database, workspace, and per-view settings. One row per session;
a session is claimed by at most one tab at a time (see `attach`). No HTTP
concerns here. Docs: docs/session.md."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlmodel import Field, SQLModel, col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .connect import _engine_for_db, _ensure_schema, _now_ms

# A claim older than this is stale: the tab closed, crashed or slept, and the
# session is free for the next tab that asks.
SESSION_CLAIM_TTL_MS = 30_000

DEFAULT_URL = "/queries"


class Session(SQLModel, table=True):
    __tablename__: ClassVar[str] = "sessions"

    id: str = Field(primary_key=True)
    seq: int  # stable ordinal behind the "Session 3" fallback label
    label: str | None = Field(default=None)  # set = user-pinned name
    connection_name: str | None = Field(default=None)  # NULL = disconnected
    database: str | None = Field(default=None)
    workspace: str = Field(default="default")
    url: str = Field(default=DEFAULT_URL)  # path + search
    ui: str = Field(default="{}")  # JSON, namespaced by view
    claimed_by: str | None = Field(default=None)  # tab token
    claim_seen_at: int | None = Field(default=None)  # unix ms
    last_active_at: int = Field(index=True)  # unix ms


@dataclass
class SessionRec:
    id: str
    seq: int
    label: str | None
    connection_name: str | None
    database: str | None
    workspace: str
    url: str
    ui: dict[str, Any]
    held: bool
    last_active_at: int


def _is_held(row: Session, now: int) -> bool:
    """A claim counts only while its heartbeat is fresh."""
    if not row.claimed_by or row.claim_seen_at is None:
        return False
    return (now - row.claim_seen_at) < SESSION_CLAIM_TTL_MS


def _to_rec(row: Session, now: int | None = None) -> SessionRec:
    now = _now_ms() if now is None else now
    try:
        ui = json.loads(row.ui)
        if not isinstance(ui, dict):
            ui = {}
    except ValueError:
        # A hand-edited blob reads as "nothing remembered" rather than breaking
        # the page, the same way the old localStorage store did.
        ui = {}
    return SessionRec(
        id=row.id,
        seq=row.seq,
        label=row.label,
        connection_name=row.connection_name,
        database=row.database,
        workspace=row.workspace,
        url=row.url,
        ui=ui,
        held=_is_held(row, now),
        last_active_at=row.last_active_at,
    )


def display_label(rec: SessionRec) -> str:
    """A pinned name, else the connection state, else the stable ordinal."""
    if rec.label:
        return rec.label
    if rec.connection_name and rec.database:
        return f"{rec.connection_name} · {rec.database}"
    if rec.connection_name:
        return rec.connection_name
    return f"Session {rec.seq}"


def _merge_ui(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Merge one level deep, per view namespace, so a view can patch one setting
    without clobbering its siblings or another view's block."""
    merged = dict(current)
    for view, value in changes.items():
        if isinstance(value, dict) and isinstance(merged.get(view), dict):
            merged[view] = {**merged[view], **value}
        else:
            merged[view] = value
    return merged


async def create_session() -> SessionRec:
    """A fresh, unclaimed session at the default route."""
    await _ensure_schema()
    now = _now_ms()
    async with AsyncSession(_engine_for_db()) as s:
        next_seq = (await s.exec(select(func.coalesce(func.max(Session.seq), 0)))).one() + 1
        row = Session(id=uuid.uuid4().hex, seq=next_seq, last_active_at=now)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _to_rec(row, now)


async def get_session_rec(sid: str) -> SessionRec | None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        return _to_rec(row) if row else None


async def list_sessions() -> list[dict[str, Any]]:
    """Every session, most recently active first — the dropdown's rows."""
    await _ensure_schema()
    now = _now_ms()
    async with AsyncSession(_engine_for_db()) as s:
        rows = (await s.exec(select(Session).order_by(col(Session.last_active_at).desc()))).all()
    out = []
    for row in rows:
        rec = _to_rec(row, now)
        out.append(
            {
                "id": rec.id,
                "label": display_label(rec),
                "pinned": rec.label is not None,
                "connection": rec.connection_name,
                "database": rec.database,
                "held": rec.held,
                "last_active_at": rec.last_active_at,
            }
        )
    return out


async def patch_session(
    sid: str,
    *,
    url: str | None = None,
    ui: dict[str, Any] | None = None,
    label: str | None = None,
    workspace: str | None = None,
) -> bool:
    """Apply the fields given; `ui` merges, the rest replace. False if unknown."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return False
        if url is not None:
            row.url = url
        if workspace is not None:
            row.workspace = workspace
        if label is not None:
            # An empty label unpins, falling back to the derived one.
            row.label = label.strip() or None
        if ui is not None:
            row.ui = json.dumps(_merge_ui(_to_rec(row).ui, ui))
        row.last_active_at = _now_ms()
        s.add(row)
        await s.commit()
        return True


async def delete_session(sid: str) -> tuple[bool, str]:
    """Remove a session. Refused while a live tab holds it."""
    await _ensure_schema()
    now = _now_ms()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return False, "unknown session"
        if _is_held(row, now):
            return False, "session is open in another tab"
        await s.delete(row)
        await s.commit()
        return True, "deleted"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --group test pytest backend/queryview/test_sessions.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Verify the migration applies cleanly from scratch**

Run: `DATA_DIR=/tmp/qv-plan-t1 uv run --group test pytest backend/queryview/test_migrations.py -v`
Expected: PASS. Then confirm the table exists:
`DATA_DIR=/tmp/qv-plan-t1 uv run python -c "import sqlite3;print([r[0] for r in sqlite3.connect('/tmp/qv-plan-t1/db.sqlite').execute(\"select name from sqlite_master where type='table'\")])"`
Expected: the printed list includes `sessions`.

- [ ] **Step 7: Commit**

```bash
git add backend/queryview/sessions.py backend/queryview/test_sessions.py \
        backend/queryview/migrations/versions/d8e9f0a1b2c3_sessions.py
git commit -m "Add the sessions table and its store

A session row holds a tab's UI state: route and URL, connection, database,
workspace and per-view settings. Labels derive from connection state unless
pinned; ui patches merge per view namespace."
```

---

### Task 2: Claim protocol — attach, select, release

**Files:**
- Modify: `backend/queryview/sessions.py`
- Test: `backend/queryview/test_sessions.py`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces:
  - `async def attach(tab: str, session_id: str | None) -> tuple[SessionRec, bool]` — returns `(rec, created)`
  - `async def select(tab: str, sid: str | None) -> tuple[SessionRec | None, str]` — returns `(rec, message)`; `rec is None` means refused
  - `async def release(tab: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/queryview/test_sessions.py`:

```python
# --- claim protocol ---------------------------------------------------------


def _free_everything():
    """Release every claim so a test starts from a known, unheld world."""

    async def go():
        from sqlmodel import select as _select
        from sqlmodel.ext.asyncio.session import AsyncSession as _S

        from queryview.connect import _engine_for_db

        async with _S(_engine_for_db()) as s:
            for row in (await s.exec(_select(sessions.Session))).all():
                await s.delete(row)
            await s.commit()

    _run(go())


def test_attach_without_an_id_creates_when_there_is_nothing():
    _free_everything()
    rec, created = _run(sessions.attach("tab-a", None))
    assert created is True
    assert rec.held is True


def test_attach_with_own_id_reclaims_the_same_session():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    again, created = _run(sessions.attach("tab-a", first.id))
    assert created is False
    assert again.id == first.id


def test_attach_resumes_the_most_recent_unheld_session():
    _free_everything()
    older, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.release("tab-a"))
    newer, _ = _run(sessions.attach("tab-b", None))
    _run(sessions.release("tab-b"))
    resumed, created = _run(sessions.attach("tab-c", None))
    assert created is False
    assert resumed.id == newer.id
    assert resumed.id != older.id


def test_attach_creates_a_new_session_when_the_last_one_is_held():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    fresh, created = _run(sessions.attach("tab-b", None))
    assert created is True
    assert fresh.id != held.id


def test_attach_with_an_id_held_by_another_tab_does_not_hijack():
    """A duplicated tab copies sessionStorage, so it arrives with someone
    else's id; it must get its own session instead of stealing one."""
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    dup, created = _run(sessions.attach("tab-b", held.id))
    assert created is True
    assert dup.id != held.id


def test_a_stale_claim_is_reclaimable():
    _free_everything()
    stale, _ = _run(sessions.attach("tab-a", None))
    _run(
        sessions.patch_claim_seen_at_for_test(
            stale.id, _now_ms_for_test() - sessions.SESSION_CLAIM_TTL_MS - 1
        )
    )
    taken, created = _run(sessions.attach("tab-b", None))
    assert created is False
    assert taken.id == stale.id


def test_release_frees_the_tab_claim():
    _free_everything()
    rec, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.release("tab-a"))
    after = _run(sessions.get_session_rec(rec.id))
    assert after is not None
    assert after.held is False


def test_select_switches_and_frees_the_previous_one():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    second = _run(sessions.create_session())
    got, _ = _run(sessions.select("tab-a", second.id))
    assert got is not None
    assert got.id == second.id
    assert _run(sessions.get_session_rec(first.id)).held is False


def test_select_none_creates_a_new_session():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    got, _ = _run(sessions.select("tab-a", None))
    assert got is not None
    assert got.id != first.id
    assert got.held is True


def test_select_refuses_a_session_held_by_another_tab():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.attach("tab-b", None))
    got, message = _run(sessions.select("tab-b", held.id))
    assert got is None
    assert "another tab" in message


def test_delete_refuses_while_held():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    ok, message = _run(sessions.delete_session(held.id))
    assert ok is False
    assert "another tab" in message
```

Add this import at the top of the same file — `_free_everything` is already in the block above:

```python
from queryview.connect import _now_ms as _now_ms_for_test  # noqa: E402
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --group test pytest backend/queryview/test_sessions.py -v -k "attach or select or release or held"`
Expected: FAIL — `AttributeError: module 'queryview.sessions' has no attribute 'attach'`

- [ ] **Step 3: Implement the claim protocol**

Append to `backend/queryview/sessions.py`:

```python
# --- Claims (one tab holds a session at a time) ---------------------------


async def _claim(s: AsyncSession, row: Session, tab: str, now: int) -> None:
    """Take the session for `tab` and free whatever else that tab held."""
    for other in (await s.exec(select(Session).where(Session.claimed_by == tab))).all():
        if other.id != row.id:
            other.claimed_by = None
            other.claim_seen_at = None
            s.add(other)
    row.claimed_by = tab
    row.claim_seen_at = now
    row.last_active_at = now
    s.add(row)


async def attach(tab: str, session_id: str | None) -> tuple[SessionRec, bool]:
    """Resolve the session this tab should show, and claim it. The whole
    new-tab-vs-refresh rule lives here, decided server-side in one pass so
    concurrent tabs can't race:

    1. the id the tab already has, if free or already its own — a refresh, or
       the 10s heartbeat;
    2. otherwise the most recently active unheld session — "restore the last
       session if none is active";
    3. otherwise a fresh one — "otherwise open a new session".

    Step 1 falls through when another live tab holds that id: a duplicated tab
    carries a copy of sessionStorage, and must not hijack the original.
    """
    await _ensure_schema()
    now = _now_ms()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, session_id) if session_id else None
        if row is not None and (not _is_held(row, now) or row.claimed_by == tab):
            await _claim(s, row, tab, now)
            await s.commit()
            await s.refresh(row)
            return _to_rec(row, now), False

        candidates = (await s.exec(select(Session).order_by(col(Session.last_active_at).desc()))).all()
        free = next((r for r in candidates if not _is_held(r, now)), None)
        if free is not None:
            await _claim(s, free, tab, now)
            await s.commit()
            await s.refresh(free)
            return _to_rec(free, now), False

    created = await create_session()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, created.id)
        if row is None:
            return created, True
        await _claim(s, row, tab, now)
        await s.commit()
        await s.refresh(row)
        return _to_rec(row, now), True


async def select(tab: str, sid: str | None) -> tuple[SessionRec | None, str]:
    """Switch this tab to a specific session, or to a brand-new one when `sid`
    is None. Refuses a session another live tab holds — two tabs on one session
    would overwrite each other's state."""
    if sid is None:
        rec, _ = await attach(tab, (await create_session()).id)
        return rec, "created"
    await _ensure_schema()
    now = _now_ms()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return None, "unknown session"
        if _is_held(row, now) and row.claimed_by != tab:
            return None, "session is open in another tab"
        await _claim(s, row, tab, now)
        await s.commit()
        await s.refresh(row)
        return _to_rec(row, now), "attached"


async def release(tab: str) -> None:
    """Drop whatever this tab holds (the pagehide beacon). Idempotent; the TTL
    covers the tab that never got to send it."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        for row in (await s.exec(select(Session).where(Session.claimed_by == tab))).all():
            row.claimed_by = None
            row.claim_seen_at = None
            s.add(row)
        await s.commit()


async def patch_claim_seen_at_for_test(sid: str, seen_at: int) -> None:
    """Age a claim from a test — there is no other way to reach the TTL branch
    without sleeping for 30 seconds."""
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is not None:
            row.claim_seen_at = seen_at
            s.add(row)
            await s.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --group test pytest backend/queryview/test_sessions.py -v`
Expected: PASS (22 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/queryview/sessions.py backend/queryview/test_sessions.py
git commit -m "Claim a session per tab, with a TTL

attach resolves refresh, resume-last and open-new in one server-side decision
so concurrent tabs cannot race. A duplicated tab arrives carrying a copy of
another tab's id and gets its own session rather than hijacking."
```

---

### Task 3: HTTP surface — `/api/sessions/*` and the `X-QV-Session` header

**Files:**
- Modify: `backend/queryview/main.py:119-138` (the `session_cookie` middleware and the `/api/session` route)
- Test: `backend/queryview/test_session_api.py` (new)

**Interfaces:**
- Consumes: `sessions.attach`, `sessions.select`, `sessions.release`, `sessions.list_sessions`, `sessions.patch_session`, `sessions.delete_session`, `sessions.get_session_rec`, `sessions.display_label`.
- Produces: `request.state.sid` resolved from the `X-QV-Session` header; the six `/api/sessions/*` routes; `_session_payload(rec) -> dict[str, Any]`.

**Transition note.** The middleware still falls back to the `qv_session` cookie so the not-yet-updated frontend keeps working at this commit. Task 11 deletes the fallback.

- [ ] **Step 1: Write the failing tests**

Create `backend/queryview/test_session_api.py`, following `test_api_db.py`'s shape (module-level imports, a `TestClient` per test):

```python
"""The /api/sessions surface: attach claims a session, patches round-trip, and
a session a live tab holds refuses deletion."""

from __future__ import annotations

from fastapi.testclient import TestClient

from queryview.main import app


def test_attach_creates_a_session_and_returns_it():
    client = TestClient(app)
    r = client.post("/api/sessions/attach", json={"tab": "tab-http-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["session"]["url"] == "/queries"
    assert body["session"]["id"]


def test_attach_requires_a_tab_token():
    from fastapi.testclient import TestClient

    from queryview.main import app

    with TestClient(app) as client:
        r = client.post("/api/sessions/attach", json={})
        assert r.status_code == 400


def test_patch_and_read_back_through_the_header():
    from fastapi.testclient import TestClient

    from queryview.main import app

    with TestClient(app) as client:
        sid = client.post("/api/sessions/attach", json={"tab": "tab-http-2"}).json()["session"]["id"]
        r = client.patch(f"/api/sessions/{sid}", json={"url": "/explorer?table=events"})
        assert r.json() == {"ok": True}
        listed = client.get("/api/sessions").json()["sessions"]
        assert any(row["id"] == sid for row in listed)


def test_delete_refuses_a_held_session():
    from fastapi.testclient import TestClient

    from queryview.main import app

    with TestClient(app) as client:
        sid = client.post("/api/sessions/attach", json={"tab": "tab-http-3"}).json()["session"]["id"]
        r = client.request("DELETE", f"/api/sessions/{sid}")
        assert r.status_code == 409


def test_release_frees_the_claim_so_the_next_tab_resumes_it():
    from fastapi.testclient import TestClient

    from queryview.main import app

    with TestClient(app) as client:
        sid = client.post("/api/sessions/attach", json={"tab": "tab-http-4"}).json()["session"]["id"]
        client.post("/api/sessions/release", json={"tab": "tab-http-4"})
        again = client.post("/api/sessions/attach", json={"tab": "tab-http-5"}).json()
        assert again["created"] is False
        assert again["session"]["id"] == sid
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --group test pytest backend/queryview/test_session_api.py -v`
Expected: FAIL — 404, because `/api/sessions/attach` does not exist yet.

- [ ] **Step 3: Replace the cookie middleware**

In `backend/queryview/main.py`, replace the `session_cookie` middleware (lines 119-131) with:

```python
@app.middleware("http")
async def session_header(request: Request, call_next):
    """Identify the session from the header the SPA sends. The `qv_session`
    cookie is still honored as a fallback while the frontend is migrated; it is
    removed once nothing depends on it."""
    sid = request.headers.get("X-QV-Session") or request.cookies.get("qv_session") or ""
    request.state.sid = sid
    return await call_next(request)
```

Delete the now-unused `import uuid` at the top of the file if nothing else uses it (check with `grep -n "uuid" backend/queryview/main.py`).

- [ ] **Step 4: Add the session routes**

Add to `backend/queryview/main.py`, immediately after the `/api/session` route:

```python
def _session_payload(rec: sessions.SessionRec) -> dict[str, Any]:
    return {
        "id": rec.id,
        "label": sessions.display_label(rec),
        "pinned": rec.label is not None,
        "connection": rec.connection_name,
        "database": rec.database,
        "workspace": rec.workspace,
        "url": rec.url,
        "ui": rec.ui,
    }


# Resolve this tab's session: a refresh re-claims its own, a new tab resumes the
# last unheld session or gets a fresh one. Also serves as the claim heartbeat.
@app.post("/api/sessions/attach")
async def sessions_attach(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("session_id"))
    rec, created = await sessions.attach(tab, raw_id or None)
    return {"ok": True, "created": created, "session": _session_payload(rec)}


# Switch this tab to a specific session, or (id omitted/null) to a new one.
@app.post("/api/sessions/select")
async def sessions_select(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("id"))
    rec, message = await sessions.select(tab, raw_id or None)
    if rec is None:
        return JSONResponse({"ok": False, "message": message}, status_code=409)
    return {"ok": True, "session": _session_payload(rec)}


@app.get("/api/sessions")
async def sessions_list() -> dict[str, Any]:
    return {"sessions": await sessions.list_sessions()}


@app.patch("/api/sessions/{sid}")
async def sessions_patch(sid: str, request: Request):
    b = await _read_json(request) or {}
    ui = b.get("ui")
    ok = await sessions.patch_session(
        sid,
        url=b.get("url") if isinstance(b.get("url"), str) else None,
        ui=ui if isinstance(ui, dict) else None,
        label=b.get("label") if isinstance(b.get("label"), str) else None,
        workspace=b.get("workspace") if isinstance(b.get("workspace"), str) else None,
    )
    if not ok:
        return JSONResponse({"ok": False, "message": "unknown session"}, status_code=404)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
async def sessions_delete(sid: str):
    ok, message = await sessions.delete_session(sid)
    if not ok:
        status = 404 if message == "unknown session" else 409
        return JSONResponse({"ok": False, "message": message}, status_code=status)
    return {"ok": True}


# Sent by the pagehide beacon so a closed tab frees its session immediately
# rather than waiting out the claim TTL.
@app.post("/api/sessions/release")
async def sessions_release(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if tab:
        await sessions.release(tab)
    return {"ok": True}
```

Add `sessions` to the package import line at the top:

```python
from . import gitsync, remote, sessions, workspaces, yamlio
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --group test pytest backend/queryview -v`
Expected: PASS — the new tests plus every existing backend test (the cookie fallback keeps them green).

- [ ] **Step 6: Commit**

```bash
git add backend/queryview/main.py backend/queryview/test_session_api.py
git commit -m "Serve the session API and identify sessions by header

X-QV-Session replaces the cookie as session identity; the cookie stays as a
fallback until the frontend sends the header."
```

---

### Task 4: Rewire `connect.py` onto session rows

**Files:**
- Modify: `backend/queryview/connect.py:246-330` (the session block: `_sessions`, `_disconnected`, `_ensure_session`, `connect_new`, `open_saved`, `disconnect`, `select_database`)
- Test: `backend/queryview/test_connect_flow.py`

**Interfaces:**
- Consumes: `sessions.get_session_rec`, `sessions.patch_session`, plus two new writers this task adds to `sessions.py`.
- Produces (added to `sessions.py`):
  - `async def set_connection(sid: str, connection_name: str | None, database: str | None = None) -> None`
  - `async def set_database(sid: str, database: str | None) -> None`
  - `async def database_of(sid: str) -> str | None`
  - `async def workspace_of(sid: str) -> str | None`

**Why:** the in-memory `_sessions` map currently *is* the session. After this task it is only a cache of live driver state (decrypted config + the database list), rebuilt from the session row on demand. `_disconnected` disappears because `connection_name IS NULL` records the same thing durably.

- [ ] **Step 1: Write the failing test**

Append to `backend/queryview/test_connect_flow.py`:

```python
def test_connect_writes_through_to_the_session_row(monkeypatch):
    """The session row, not the in-memory map, is what survives a restart."""
    from queryview import sessions

    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    assert again.connection_name == "reporting"


def test_session_state_rebuilds_from_the_row_after_the_cache_is_dropped(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    connect._sessions.clear()  # as a backend restart would
    out = _run(connect.get_session(rec.id))
    assert out["connected"] is True
    assert out["name"] == "reporting"


def test_disconnect_clears_the_connection_durably(monkeypatch):
    from queryview import sessions

    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    _run(connect.disconnect(rec.id))
    connect._sessions.clear()
    assert _run(connect.get_session(rec.id)) == {"connected": False}
```

Add `from queryview import sessions` to that file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --group test pytest backend/queryview/test_connect_flow.py -v -k "writes_through or rebuilds or durably"`
Expected: FAIL — the row's `connection_name` stays `None`, and `get_session` reports `connected: False` after the cache is cleared.

- [ ] **Step 3: Add the session writers**

Append to `backend/queryview/sessions.py`:

```python
async def set_connection(sid: str, connection_name: str | None, database: str | None = None) -> None:
    """Record which connection a session is on. A None name is the durable
    disconnected state — there is no separate 'disconnected' set."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        row.connection_name = connection_name
        row.database = database
        row.last_active_at = _now_ms()
        s.add(row)
        await s.commit()


async def set_database(sid: str, database: str | None) -> None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        row.database = database
        row.last_active_at = _now_ms()
        s.add(row)
        await s.commit()


async def database_of(sid: str) -> str | None:
    rec = await get_session_rec(sid)
    return rec.database if rec else None


async def workspace_of(sid: str) -> str | None:
    rec = await get_session_rec(sid)
    return rec.workspace if rec else None
```

- [ ] **Step 4: Rewire `connect.py`**

In `backend/queryview/connect.py`:

1. Delete `_disconnected`, `_mark_disconnected`, and every `_disconnected` reference.
2. Replace `_ensure_session` with:

```python
async def _ensure_session(sid: str) -> None:
    """Rebuild this session's live driver state from its row. The row is the
    durable truth; `_sessions` is only a cache of the decrypted config and the
    database list, so a backend restart costs one reconnect, not the session."""
    if not sid or _get_session_entry(sid):
        return
    from . import sessions as sessions_store

    rec = await sessions_store.get_session_rec(sid)
    if rec is None or rec.connection_name is None:
        return
    stored = await _connection_by_name(rec.connection_name)
    if stored is None:
        # The connection was deleted, or its config no longer decrypts. The
        # session stays as it is and reads as disconnected; the user reconnects.
        return
    state, _ = await _build_session(stored.name, stored.config, rec.database, stored.type)
    if state is not None:
        _set_session_entry(sid, state)
```

3. In `connect_new`, replace `_disconnected.pop(sid, None)` with a write-through:

```python
    _set_session_entry(sid, state)
    await _save_active_connection(name, config, conn_type)
    from . import sessions as sessions_store

    await sessions_store.set_connection(sid, name, None)
```

4. In `open_saved`, do the same (after `await _touch_connection(name)`):

```python
    from . import sessions as sessions_store

    await sessions_store.set_connection(sid, name, None)
```

5. In `disconnect`:

```python
async def disconnect(sid: str) -> dict[str, Any]:
    """Drop this session's active connection. Saved connections are left intact
    — `connect <name>` still reopens them."""
    _sessions.pop(sid, None)
    from . import sessions as sessions_store

    await sessions_store.set_connection(sid, None, None)
    return {"ok": True}
```

6. In `select_database`, after `await _save_selected_database(s.name, database)`:

```python
    from . import sessions as sessions_store

    await sessions_store.set_database(sid, database)
```

The `from . import sessions as sessions_store` imports are function-local on purpose: `sessions.py` imports from `connect.py`, so a module-level import here would be circular.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --group test pytest backend/queryview -v`
Expected: PASS. Existing tests that call `connect.connect_new("s-fake", ...)` with an id that has no session row still pass — `set_connection` no-ops on an unknown id, and the in-memory cache carries those tests.

- [ ] **Step 6: Commit**

```bash
git add backend/queryview/connect.py backend/queryview/sessions.py backend/queryview/test_connect_flow.py
git commit -m "Back the active connection with the session row

The in-memory map becomes a cache of live driver state, rebuilt from the row on
demand, so a backend restart no longer drops the session. A null connection_name
replaces the separate disconnected set."
```

---

### Task 5: Key the agent channel by the session id

**Files:**
- Modify: `backend/queryview/remote.py:31-33, 80-110` (the channel map and the database/workspace mirror)
- Modify: `backend/queryview/main.py` (the `/api/remote/events` route; delete `/api/remote/db`)
- Modify: `backend/queryview/mcp_server.py:64, 115-121, 201`
- Test: `backend/queryview/test_remote.py`

**Interfaces:**
- Consumes: `sessions.database_of`, `sessions.workspace_of` (Task 4).
- Produces: `remote.register(session_id: str) -> str` (returns the id it was given), and the removal of `remote.set_session_database`, `remote.session_database`, `remote.set_session_workspace`, `remote.session_workspace`.

- [ ] **Step 1: Write the failing test**

Append to `backend/queryview/test_remote.py`:

```python
def test_register_keys_the_channel_by_the_session_id():
    from queryview import remote

    remote.register("session-abc")
    ok, message = remote.push("session-abc", {"type": "query", "query": "SELECT 1"})
    assert ok, message
    remote.unregister("session-abc")


def test_push_to_an_unarmed_session_is_refused():
    """Disarming still revokes: the id alone is not access."""
    from queryview import remote

    remote.unregister("session-xyz")
    ok, message = remote.push("session-xyz", {"type": "query", "query": "SELECT 1"})
    assert ok is False
    assert message == "unknown or inactive session"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --group test pytest backend/queryview/test_remote.py -v -k "keys_the_channel or unarmed"`
Expected: FAIL — `register()` takes no argument.

- [ ] **Step 3: Rework `remote.py`**

Replace `register` and delete the mirror:

```python
def register(session_id: str) -> str:
    """Open a channel for a newly-armed session, keyed by the session's own id.
    Arming is the gate: `unregister` on disarm makes every later push fail, so
    a shared id grants nothing once the session is disarmed."""
    _channels[session_id] = _Channel()
    return session_id
```

Delete `set_session_database`, `session_database`, `set_session_workspace`, `session_workspace`, and the `database` / `workspace` fields on `_Channel`. Delete the now-unused `import secrets`.

- [ ] **Step 4: Rework the callers**

In `backend/queryview/main.py`:

```python
@app.get("/api/remote/events")
async def remote_events(request: Request):
    remote_id = remote.register(request.state.sid)
    return StreamingResponse(
        _event_stream(remote_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Delete the whole `/api/remote/db` route.

In `backend/queryview/mcp_server.py`:
- line 64: `return {"ok": ok, "message": message, "database": await sessions.database_of(session_id)}`
- line 201: the same substitution in `push_dashboard`'s return.
- `_session_workspace_rec`: replace `remote.session_workspace(session_id)` with `await sessions.workspace_of(session_id)`.
- Add `from . import sessions` to its imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --group test pytest backend/queryview -v`
Expected: PASS. Any existing test that posted to `/api/remote/db` must be deleted in this step — the endpoint is gone by design; grep for it with `grep -rn "remote/db" backend e2e`.

- [ ] **Step 6: Commit**

```bash
git add backend/queryview/remote.py backend/queryview/main.py backend/queryview/mcp_server.py backend/queryview/test_remote.py
git commit -m "Key the agent channel by the session id

The channel can now read the session row directly, so the UI stops mirroring
its database and workspace into it and /api/remote/db goes away. Arming still
gates access and disarming still revokes."
```

---

### Task 6: Frontend session client

**Files:**
- Create: `frontend/src/app/tabStorage.ts`
- Create: `frontend/src/app/api.ts`
- Create: `frontend/src/app/session.ts`
- Test: `frontend/src/app/session.test.ts`

**Interfaces:**
- Consumes: the `/api/sessions/*` routes from Task 3.
- Produces:
  - `tabStorage.ts`: `TAB_KEY = 'qv_tab'`, `SESSION_KEY = 'qv_session'`, `tabRead(key: string): string | null`, `tabWrite(key: string, value: string): void`
  - `api.ts`: `apiFetch(path: string, init?: RequestInit): Promise<Response>`
  - `session.ts`: `type SessionState`, `attachSession(): Promise<SessionState>`, `currentSession(): SessionState | null`, `patchSession(changes: SessionPatch, immediate?: boolean): void`, `sessionId(): string | null`, `viewState(view: string): Record<string, unknown>`, `patchView(view: string, changes: Record<string, unknown>): void`, `listSessions(): Promise<SessionSummary[]>`, `selectSession(id: string | null): Promise<SessionState | null>`, `removeSession(id: string): Promise<{ ok: boolean; message?: string }>`, `renameSession(label: string): Promise<void>`, `startHeartbeat(): () => void`, `releaseSession(): void`, `flushPatches(): Promise<void>`

**Why three files:** `api.ts` must inject the session id on every call, and `session.ts` must call the API — routing both through `tabStorage.ts` keeps them from importing each other.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/session.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TAB_KEY, SESSION_KEY, tabRead, tabWrite } from './tabStorage'

function stubTabStorage(initial?: Record<string, string>) {
  const store = new Map<string, string>(Object.entries(initial ?? {}))
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  return store
}

const SESSION = {
  id: 's1',
  label: 'Session 1',
  pinned: false,
  connection: null,
  database: null,
  workspace: 'default',
  url: '/queries',
  ui: {},
}

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllGlobals())

describe('tabStorage', () => {
  it('round-trips a value', () => {
    stubTabStorage()
    tabWrite(TAB_KEY, 'tab-1')
    expect(tabRead(TAB_KEY)).toBe('tab-1')
  })

  it('falls back to memory when sessionStorage throws', () => {
    const boom = () => {
      throw new Error('denied')
    }
    vi.stubGlobal('sessionStorage', { getItem: boom, setItem: boom, removeItem: boom })
    tabWrite(SESSION_KEY, 's-mem')
    // The tab still works for its lifetime; it just cannot survive a refresh.
    expect(tabRead(SESSION_KEY)).toBe('s-mem')
  })
})

describe('attachSession', () => {
  it('posts the tab token and remembers the returned id', async () => {
    const store = stubTabStorage()
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, created: true, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession } = await import('./session')

    const state = await attachSession()

    expect(state.id).toBe('s1')
    expect(store.get(SESSION_KEY)).toBe('s1')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.tab).toBe(store.get(TAB_KEY))
  })

  it('sends the id it already has, so a refresh re-attaches', async () => {
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's-existing' })
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, created: false, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession } = await import('./session')

    await attachSession()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.session_id).toBe('s-existing')
  })
})

describe('apiFetch', () => {
  it('sends the session id as a header', async () => {
    stubTabStorage({ [SESSION_KEY]: 's-header' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const { apiFetch } = await import('./api')

    await apiFetch('/api/db/tables')

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers['X-QV-Session']).toBe('s-header')
  })
})

describe('patchView', () => {
  it('coalesces rapid changes into one request', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession, patchView } = await import('./session')
    await attachSession()
    fetchMock.mockClear()

    patchView('query', { sql: 'S' })
    patchView('query', { sql: 'SE' })
    patchView('query', { sql: 'SEL' })
    await vi.advanceTimersByTimeAsync(500)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.ui.query.sql).toBe('SEL')
    vi.useRealTimers()
  })

  it('reads back locally before the write lands', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }))
    const { attachSession, patchView, viewState } = await import('./session')
    await attachSession()

    patchView('explorer', { sidebarWidth: 412 })

    expect(viewState('explorer').sidebarWidth).toBe(412)
    vi.useRealTimers()
  })

  it('never rejects when the patch request fails', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const { attachSession, patchView, flushPatches } = await import('./session')
    await attachSession()

    patchView('query', { sql: 'SELECT 1' })
    await vi.advanceTimersByTimeAsync(500)

    await expect(flushPatches()).resolves.toBeUndefined()
    vi.useRealTimers()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -w frontend -- session`
Expected: FAIL — `Cannot find module './tabStorage'`

- [ ] **Step 3: Write `tabStorage.ts`**

```ts
// The app's only browser-storage touchpoint. `sessionStorage` survives a
// refresh but never crosses to a new tab, which is exactly the distinction the
// session claim needs: a tab that already has an id is refreshing, a tab
// without one is new. It holds identity only — the server holds state.
//
// Access can throw (private windows, blocked site data), so every read and
// write falls back to a module-level map: the tab works normally for its
// lifetime, it just cannot re-attach after a refresh.

export const TAB_KEY = 'qv_tab'
export const SESSION_KEY = 'qv_session'

const memory = new Map<string, string>()

export function tabRead(key: string): string | null {
  try {
    const stored = sessionStorage.getItem(key)
    if (stored !== null) return stored
  } catch {
    /* fall through to the in-memory copy */
  }
  return memory.get(key) ?? null
}

export function tabWrite(key: string, value: string): void {
  memory.set(key, value)
  try {
    sessionStorage.setItem(key, value)
  } catch {
    /* non-persistent contexts still work within the tab's lifetime */
  }
}
```

- [ ] **Step 4: Write `api.ts`**

```ts
// Every /api/* call goes through here so it carries the caller's session. The
// backend resolves `X-QV-Session` into the session whose connection, database
// and workspace the request acts on.

import { SESSION_KEY, tabRead } from './tabStorage'

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const sid = tabRead(SESSION_KEY)
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (sid) headers['X-QV-Session'] = sid
  return fetch(path, { ...init, headers })
}
```

- [ ] **Step 5: Write `session.ts`**

```ts
// The session client: attach/heartbeat/release, the in-memory mirror every view
// reads, and debounced write-back. The server owns the state; this module keeps
// a local copy so the UI renders from it synchronously and a patch in flight is
// never something the user waits on. See docs/session.md.

import { apiFetch } from './api'
import { SESSION_KEY, TAB_KEY, tabRead, tabWrite } from './tabStorage'

export type SessionState = {
  id: string
  label: string
  pinned: boolean
  connection: string | null
  database: string | null
  workspace: string
  url: string
  ui: Record<string, Record<string, unknown>>
}

export type SessionSummary = {
  id: string
  label: string
  pinned: boolean
  connection: string | null
  database: string | null
  held: boolean
  last_active_at: number
}

export type SessionPatch = { url?: string; label?: string; workspace?: string }

// Matches the backend's claim TTL of 30s: a heartbeat every 10s leaves room for
// two missed beats before another tab may take the session.
const HEARTBEAT_MS = 10_000
// Long enough that typing SQL coalesces into one write, short enough that a
// refresh a moment later still finds it.
const DEBOUNCE_MS = 400

let state: SessionState | null = null
let pendingUi: Record<string, Record<string, unknown>> = {}
let pendingFields: SessionPatch = {}
let timer: ReturnType<typeof setTimeout> | undefined
let inFlight: Promise<void> = Promise.resolve()

function tabToken(): string {
  const existing = tabRead(TAB_KEY)
  if (existing) return existing
  const minted = crypto.randomUUID()
  tabWrite(TAB_KEY, minted)
  return minted
}

export function currentSession(): SessionState | null {
  return state
}

export function sessionId(): string | null {
  return state?.id ?? null
}

function adopt(next: SessionState): SessionState {
  state = { ...next, ui: next.ui ?? {} }
  tabWrite(SESSION_KEY, state.id)
  return state
}

export async function attachSession(): Promise<SessionState> {
  const body: Record<string, string> = { tab: tabToken() }
  const known = tabRead(SESSION_KEY)
  if (known) body.session_id = known
  const res = await apiFetch('/api/sessions/attach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  return adopt(data.session as SessionState)
}

// Re-attaching is the heartbeat: it refreshes the claim without a second
// endpoint, and re-adopts the session if the server handed us a different one.
export function startHeartbeat(): () => void {
  const handle = setInterval(() => void attachSession().catch(() => {}), HEARTBEAT_MS)
  return () => clearInterval(handle)
}

export function releaseSession(): void {
  const tab = tabRead(TAB_KEY)
  if (!tab) return
  const payload = JSON.stringify({ tab })
  try {
    // A beacon survives the page going away; a fetch would be cancelled.
    navigator.sendBeacon?.('/api/sessions/release', new Blob([payload], { type: 'application/json' }))
  } catch {
    /* the claim TTL frees the session anyway */
  }
}

function schedule(): void {
  clearTimeout(timer)
  timer = setTimeout(() => void flushPatches(), DEBOUNCE_MS)
}

// Patches are fire-and-forget and last-write-wins: a failed one loses a
// remembered preference, never the user's work in the live tab.
export async function flushPatches(): Promise<void> {
  clearTimeout(timer)
  const sid = state?.id
  const ui = pendingUi
  const fields = pendingFields
  pendingUi = {}
  pendingFields = {}
  if (!sid || (Object.keys(ui).length === 0 && Object.keys(fields).length === 0)) return
  inFlight = apiFetch(`/api/sessions/${encodeURIComponent(sid)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, ...(Object.keys(ui).length ? { ui } : {}) }),
  })
    .then(() => undefined)
    .catch(() => undefined)
  return inFlight
}

export function viewState(view: string): Record<string, unknown> {
  return state?.ui?.[view] ?? {}
}

export function patchView(view: string, changes: Record<string, unknown>): void {
  if (!state) return
  state.ui = { ...state.ui, [view]: { ...(state.ui[view] ?? {}), ...changes } }
  pendingUi = { ...pendingUi, [view]: { ...(pendingUi[view] ?? {}), ...changes } }
  schedule()
}

export function patchSession(changes: SessionPatch, immediate = false): void {
  if (!state) return
  state = { ...state, ...changes } as SessionState
  pendingFields = { ...pendingFields, ...changes }
  if (immediate) void flushPatches()
  else schedule()
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await (await apiFetch('/api/sessions')).json()
  return (r.sessions ?? []) as SessionSummary[]
}

// id === null asks for a brand-new session. Returns null when the target is
// open in another tab, which the switcher reports rather than stealing it.
export async function selectSession(id: string | null): Promise<SessionState | null> {
  await flushPatches()
  const res = await apiFetch('/api/sessions/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tab: tabToken(), id }),
  })
  const data = await res.json()
  if (!data.ok) return null
  return adopt(data.session as SessionState)
}

export async function removeSession(id: string): Promise<{ ok: boolean; message?: string }> {
  const res = await apiFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  return res.json()
}

export async function renameSession(label: string): Promise<void> {
  patchSession({ label }, true)
  await inFlight
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm run test -w frontend -- session`
Expected: PASS (8 tests)

- [ ] **Step 7: Lint**

Run: `npm run lint -w frontend`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/tabStorage.ts frontend/src/app/api.ts frontend/src/app/session.ts frontend/src/app/session.test.ts
git commit -m "Add the frontend session client

sessionStorage holds identity, the server holds state. Patches are debounced,
fire-and-forget and last-write-wins, and the local mirror answers reads so the
UI never waits on a write."
```

---

### Task 7: Wire the shell — attach gate, URL restore and patch

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Test: covered by `e2e/test_sessions.py` in Task 11 (this task is wiring; its behavior is only observable in a browser)

**Interfaces:**
- Consumes: `attachSession`, `startHeartbeat`, `releaseSession`, `patchSession`, `currentSession`, `sessionId` from `session.ts`; `apiFetch` from `api.ts`.
- Produces: nothing new for later tasks; `Shell` now renders only after `attachSession()` resolves.

- [ ] **Step 1: Replace every `fetch('/api/…')` in the app with `apiFetch`**

Run to find them all:

```bash
grep -rn "fetch('/api\|fetch(\`/api" frontend/src --include=*.ts --include=*.tsx
```

In each file, import `apiFetch` from the right relative path (`./api` inside `src/app`, `../api` inside `src/app/controls`) and swap the call. Leave `new EventSource('/api/remote/events')` alone — `EventSource` cannot send headers; Task 11 covers how it identifies its session.

- [ ] **Step 2: Replace the session probe with the attach gate**

In `App.tsx`, replace the `useEffect` that calls `/api/session` (around lines 155-176) with:

```tsx
  // Attach before anything renders: the session decides which page we land on,
  // which connection is live and what the query panel holds. A refresh
  // re-attaches to the very same session; a new tab resumes the last unheld one
  // or is given a fresh session. The server makes that call — see attach() in
  // backend/queryview/sessions.py.
  useEffect(() => {
    let stopHeartbeat = () => {}
    void (async () => {
      let restored: Awaited<ReturnType<typeof attachSession>> | null = null
      try {
        restored = await attachSession()
      } catch {
        /* no session: the app still runs, it just remembers nothing */
      }
      if (restored) {
        setWorkspace(restored.workspace)
        // Only `/` restores the remembered URL. A deep link is what the user
        // asked for, so it wins and is written into the session instead.
        if (window.location.pathname === '/' && restored.url) {
          navigate(restored.url, { replace: true })
        }
        if (initialConnection) {
          await openConnection(initialConnection)
        } else if (restored.connection) {
          await refreshConnection()
        }
        stopHeartbeat = startHeartbeat()
      }
      setSessionChecked(true)
    })()
    window.addEventListener('pagehide', releaseSession)
    return () => {
      stopHeartbeat()
      window.removeEventListener('pagehide', releaseSession)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
```

Add `refreshConnection`, which replaces the old inline probe:

```tsx
  // The live connection for the attached session. `/api/session` reads the
  // session's own row now, so this is a per-session question.
  async function refreshConnection() {
    try {
      const s = await (await apiFetch('/api/session')).json()
      if (!s.connected) {
        setConnection(null)
        return
      }
      setConnection({
        name: s.name as string,
        type: (s.type ?? 'clickhouse') as string,
        databases: (s.databases ?? []) as string[],
        database: (s.database ?? null) as string | null,
      })
    } catch {
      /* leave the connection as-is */
    }
  }
```

- [ ] **Step 3: Persist the URL as the user navigates**

Add below the attach effect:

```tsx
  // The URL is session state: it is what a refresh and a session switch restore.
  // Immediate rather than debounced — navigation is a discrete act, and a
  // refresh right after it must land on the new page.
  useEffect(() => {
    if (!sessionChecked) return
    patchSession({ url: `${location.pathname}${location.search}` }, true)
  }, [sessionChecked, location.pathname, location.search])
```

- [ ] **Step 4: Make the workspace a session field**

Replace `switchWorkspace`:

```tsx
  function switchWorkspace(name: string) {
    patchSession({ workspace: name }, true)
    setWorkspace(name)
  }
```

Change the initial state to `useState('default')` — the session supplies the real value once attached — and delete the `activeWorkspace` / `setActiveWorkspace` imports.

- [ ] **Step 5: Use the session id as the agent id and drop the mirror**

Replace the `ready` SSE handler's body with `setRemoteId(sessionId())`, and **delete** the entire `useEffect` that posts to `/api/remote/db` (around lines 213-227) — the backend reads the session row now.

- [ ] **Step 6: Verify the app runs**

Run `npm run dev` in one terminal. In the browser:
1. Open `http://localhost:5173`, connect, pick a database, navigate to Explorer and open a table.
2. **Refresh.** Expected: the same page, the same table, the same connection pill.
3. Open a second tab at `/`. Expected: a *different* session — the first tab's session is held, so the new tab starts fresh at the prompt.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app
git commit -m "Attach a session before the shell renders

The session decides the landing URL, the live connection and the workspace. A
deep link still wins over the remembered URL, and the agent id is now the
session id."
```

---

### Task 8: Query-panel state in the session

**Files:**
- Modify: `frontend/src/app/QueryView.tsx:601-617` (the `QueryPanel` state block)
- Test: `e2e/test_sessions.py` (Task 11)

**Interfaces:**
- Consumes: `viewState`, `patchView` from `session.ts`.
- Produces: nothing for later tasks.

- [ ] **Step 1: Hydrate the panel's initial state from the session**

In `QueryPanel`, replace the first four `useState` calls with lazy initialisers reading the session:

```tsx
  // Restored from the session so a refresh keeps the query you were writing.
  // Deliberately inputs only: results are not restored, so a reload can never
  // re-fire an expensive query. The explorer, being URL-driven, still refetches.
  const saved = viewState('query')
  const [sql, setSql] = useState(() => (typeof saved.sql === 'string' ? saved.sql : ''))
  const [limit, setLimit] = useState(() => (typeof saved.limit === 'number' ? saved.limit : 100))
  const [offset, setOffset] = useState(() => (typeof saved.offset === 'number' ? saved.offset : 0))
```

and, further down, the two presentation ones:

```tsx
  const [visibleCols, setVisibleCols] = useState<string[]>(() =>
    Array.isArray(saved.visibleCols) ? (saved.visibleCols as string[]) : [],
  )
  const [orderBy, setOrderBy] = useState<OrderCol[]>(() =>
    Array.isArray(saved.orderBy) ? (saved.orderBy as OrderCol[]) : [],
  )
```

- [ ] **Step 2: Write each change back**

Add one effect after the state block:

```tsx
  // Write-back is debounced inside session.ts, so this coalesces while typing.
  useEffect(() => {
    patchView('query', { sql, limit, offset, visibleCols, orderBy })
  }, [sql, limit, offset, visibleCols, orderBy])
```

- [ ] **Step 3: Verify in the browser**

With `npm run dev` running: connect, type `SELECT 1` in the query panel, set the limit to 50, **refresh**. Expected: the SQL text and the limit come back; the results area is empty until Run is pressed.

- [ ] **Step 4: Run the unit tests and lint**

Run: `npm run test -w frontend && npm run lint -w frontend`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/QueryView.tsx
git commit -m "Restore the query panel from the session

SQL text, pagination, visible columns and sort survive a refresh. Results do
not: a reload must never re-fire an expensive query."
```

---

### Task 9: Remove localStorage from the app

**Files:**
- Modify: `frontend/src/app/explorerSettings.ts`, `frontend/src/app/workspace.ts`, `frontend/src/app/workspace.test.ts`, `frontend/src/app/explorerSettings.test.ts`
- Delete: `frontend/src/app/viewSettings.ts`, `frontend/src/app/viewSettings.test.ts`, `frontend/src/app/testStorage.ts`

**Interfaces:**
- Consumes: `viewState`, `patchView` from `session.ts`.
- Produces: `explorerSettings.ts` keeps `loadSidebarWidth()`, `saveSidebarWidth(width: number)`, `clampSidebarWidth(width: number)`, `MIN_SIDEBAR_WIDTH`, `MAX_SIDEBAR_WIDTH`, `DEFAULT_SIDEBAR_WIDTH` — same names, new backing store.

- [ ] **Step 1: Point `explorerSettings.ts` at the session**

Replace its import and the two accessors:

```ts
import { patchView, viewState } from './session'

const VIEW = 'explorer'
```

```ts
export function loadSidebarWidth(): number {
  const stored = viewState(VIEW).sidebarWidth
  return typeof stored === 'number' ? clampSidebarWidth(stored) : DEFAULT_SIDEBAR_WIDTH
}

export function saveSidebarWidth(width: number): void {
  patchView(VIEW, { sidebarWidth: clampSidebarWidth(width) })
}
```

- [ ] **Step 2: Delete the dead modules**

```bash
git rm frontend/src/app/viewSettings.ts frontend/src/app/viewSettings.test.ts frontend/src/app/testStorage.ts
```

- [ ] **Step 3: Strip the localStorage accessors from `workspace.ts`**

Delete `const KEY = 'qv_workspace'`, `activeWorkspace()` and `setActiveWorkspace()`, and update the module comment:

```ts
// Client for /api/workspaces. The active workspace is session state (see
// session.ts); this module only talks to the workspace API.
```

- [ ] **Step 4: Fix the tests that referenced the deleted modules**

In `workspace.test.ts`, delete the `falls back to "default" when localStorage is unavailable` case and any `stubStorage` import. In `explorerSettings.test.ts`, replace `stubStorage` usage with a mocked session module:

```ts
vi.mock('./session', () => {
  let ui: Record<string, unknown> = {}
  return {
    viewState: () => ui,
    patchView: (_view: string, changes: Record<string, unknown>) => {
      ui = { ...ui, ...changes }
    },
  }
})
```

- [ ] **Step 5: Confirm no localStorage remains**

Run: `grep -rn "localStorage" frontend/src`
Expected: **no matches.**

- [ ] **Step 6: Run the tests and lint**

Run: `npm run test -w frontend && npm run lint -w frontend`
Expected: PASS, clean.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src
git commit -m "Drop localStorage in favour of the session

The session row supersedes qv_workspace and qv_view_*; keeping both would be
two stores for one concept. sessionStorage now holds identity only."
```

---

### Task 10: The session switcher

**Files:**
- Create: `frontend/src/app/controls/SessionSwitcher.tsx`
- Modify: `frontend/src/app/App.tsx` (render it in the nav)

**Interfaces:**
- Consumes: `listSessions`, `selectSession`, `removeSession`, `renameSession`, `currentSession` from `session.ts`; `useDismiss` from `./useDismiss`.
- Produces: `export default function SessionSwitcher({ label, onSwitch }: { label: string; onSwitch: (s: SessionState) => void })`

- [ ] **Step 1: Write the component**

Create `frontend/src/app/controls/SessionSwitcher.tsx`:

```tsx
import { useEffect, useState } from 'react'

import { useDismiss } from './useDismiss'
import {
  listSessions,
  removeSession,
  renameSession,
  selectSession,
  type SessionState,
  type SessionSummary,
} from '../session'

type Props = {
  label: string
  onSwitch: (session: SessionState) => void
}

// Header dropdown listing every session. A session held by another live tab is
// shown but not selectable: two tabs on one session would overwrite each
// other's state, which is the whole point of the per-tab claim.
export default function SessionSwitcher({ label, onSwitch }: Props) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<SessionSummary[]>([])
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const rootRef = useDismiss<HTMLDivElement>(open && !renaming, () => setOpen(false))

  async function reload() {
    try {
      setList(await listSessions())
    } catch {
      /* keep the last list */
    }
  }

  useEffect(() => {
    if (!open) return
    // setList runs after the fetch await, so it doesn't cascade renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [open])

  async function switchTo(id: string | null) {
    setError('')
    const next = await selectSession(id)
    if (!next) {
      setError('That session is open in another tab.')
      await reload()
      return
    }
    setOpen(false)
    onSwitch(next)
  }

  async function remove(id: string) {
    const r = await removeSession(id)
    if (!r.ok) {
      setError(r.message ?? 'delete failed')
      return
    }
    await reload()
  }

  async function saveName() {
    await renameSession(draft.trim())
    setRenaming(false)
    setOpen(false)
    await reload()
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="session-switcher"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="glass-toggle px-3 py-1.5 text-sm"
      >
        {label} <span className="text-xs text-slate-400">▾</span>
      </button>
      {open && (
        <div
          data-testid="session-menu"
          role="listbox"
          className="glass-popover absolute right-0 top-full z-10 mt-2 flex max-h-96 w-72 flex-col p-1 text-sm"
        >
          <div className="overflow-auto">
            {list.map((s) => (
              <div key={s.id} className="flex items-center gap-1">
                <button
                  type="button"
                  role="option"
                  aria-selected={s.label === label}
                  disabled={s.held && s.label !== label}
                  data-testid={`session-row-${s.id}`}
                  onClick={() => void switchTo(s.id)}
                  className="flex-1 truncate rounded px-2 py-1.5 text-left text-slate-200 hover:bg-white/10 disabled:text-slate-500 disabled:hover:bg-transparent"
                >
                  {s.label}
                  {s.held && s.label !== label && (
                    <span className="ml-2 text-xs text-slate-400">in another tab</span>
                  )}
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${s.label}`}
                  data-testid={`session-delete-${s.id}`}
                  onClick={() => void remove(s.id)}
                  className="rounded px-2 py-1.5 text-slate-400 hover:bg-white/10"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          {error && <p className="px-2 py-1.5 text-xs text-amber-300">{error}</p>}
          <div className="mt-1 border-t border-white/10 pt-1">
            {renaming ? (
              <form
                className="flex gap-1 p-1"
                onSubmit={(e) => {
                  e.preventDefault()
                  void saveName()
                }}
              >
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  aria-label="Session name"
                  data-testid="session-rename-input"
                  autoFocus
                  className="glass-input w-full px-2 py-1 text-sm"
                />
                <button type="submit" className="glass-btn px-2 py-1 text-xs">
                  Save
                </button>
              </form>
            ) : (
              <>
                <button
                  type="button"
                  data-testid="session-new"
                  onClick={() => void switchTo(null)}
                  className="block w-full rounded px-2 py-1.5 text-left text-indigo-200 hover:bg-white/10"
                >
                  New session
                </button>
                <button
                  type="button"
                  data-testid="session-rename"
                  onClick={() => {
                    setDraft(label)
                    setRenaming(true)
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-slate-200 hover:bg-white/10"
                >
                  Rename this session
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Render it in the nav**

In `App.tsx`, inside the `<nav>` before `WorkspaceSwitcher`:

```tsx
        <SessionSwitcher
          label={sessionLabel}
          onSwitch={(s) => {
            setWorkspace(s.workspace)
            navigate(s.url || '/queries')
            void refreshConnection()
          }}
        />
```

Track the label with `const [sessionLabel, setSessionLabel] = useState('Session')`, set it from `restored.label` in the attach effect and from `s.label` in `onSwitch`.

- [ ] **Step 3: Verify in the browser**

With `npm run dev`: open the dropdown, create a new session, switch back to the first — the URL, connection pill and query panel should all follow. A session open in the other tab shows `in another tab` and is not clickable.

- [ ] **Step 4: Run tests and lint**

Run: `npm run test -w frontend && npm run lint -w frontend`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app
git commit -m "Add the session switcher

Lists every session, switches between them, renames and deletes. A session a
live tab holds is shown but not selectable."
```

---

### Task 11: Remove the cookie, add e2e coverage, update the docs

**Files:**
- Modify: `backend/queryview/main.py` (drop the cookie fallback), `backend/queryview/conftest.py` if it sets cookies
- Create: `e2e/test_sessions.py`
- Modify: `e2e/test_workspaces.py:43`, `e2e/test_explorer.py:155`
- Create: `docs/session.md`
- Modify: `docs/queryview.md`, `docs/connect.md`, `docs/api.md`, `docs/remote.md`
- Delete: `docs/superpowers/specs/2026-09-17-session-persistence-design.md`, `docs/superpowers/plans/2026-09-17-session-persistence.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the shipped feature.

**The EventSource problem.** `EventSource` cannot set headers, so `/api/remote/events` cannot read `X-QV-Session`. Pass the id in the query string instead: the frontend opens `new EventSource('/api/remote/events?session=' + sessionId())`, and the route reads `request.query_params.get("session") or request.state.sid`. Do this **before** removing the cookie fallback, or arming breaks.

- [ ] **Step 1: Fix the SSE session identity**

In `App.tsx`: `const es = new EventSource('/api/remote/events?session=' + encodeURIComponent(sessionId() ?? ''))`.

In `main.py`:

```python
@app.get("/api/remote/events")
async def remote_events(request: Request):
    # EventSource cannot send headers, so the id travels in the query string.
    remote_id = request.query_params.get("session") or request.state.sid
    ...
```

- [ ] **Step 2: Remove the cookie fallback**

```python
    sid = request.headers.get("X-QV-Session") or ""
```

Then `grep -rn "qv_session" backend e2e frontend/src` — the only remaining hits should be `frontend/src/app/tabStorage.ts` (the `sessionStorage` key name).

- [ ] **Step 3: Write the e2e tests**

Create `e2e/test_sessions.py`:

```python
"""Sessions survive a refresh, are per-tab, and are switchable."""

import re

from playwright.sync_api import Page, expect

from conftest import connect_clickhouse_test_db, open_query_panel


def test_refresh_keeps_the_query_and_the_page(page: Page) -> None:
    connect_clickhouse_test_db(page)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT 1")
    # Let the debounced write land before reloading.
    page.wait_for_timeout(800)

    page.reload(wait_until="networkidle")

    expect(page.get_by_test_id("query-input")).to_have_value("SELECT 1")
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - test")


def test_refresh_keeps_the_explorer_url(page: Page) -> None:
    connect_clickhouse_test_db(page)
    page.get_by_test_id("nav-explorer").click()
    expect(page).to_have_url(re.compile(r"/explorer"))

    page.reload(wait_until="networkidle")

    expect(page).to_have_url(re.compile(r"/explorer"))


def test_a_second_tab_gets_its_own_session(page: Page, context) -> None:
    connect_clickhouse_test_db(page)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT 1")
    page.wait_for_timeout(800)

    second = context.new_page()
    second.goto("/", wait_until="networkidle")
    second.get_by_test_id("nav-queries").click()

    # The first tab holds its session, so this one is fresh.
    expect(second.get_by_test_id("sql-input")).to_have_value("")
    second.close()


def test_the_switcher_lists_and_switches_sessions(page: Page) -> None:
    connect_clickhouse_test_db(page)
    page.get_by_test_id("session-switcher").click()
    expect(page.get_by_test_id("session-menu")).to_be_visible()

    page.get_by_test_id("session-new").click()

    # A new session starts disconnected, at the prompt.
    expect(page.get_by_test_id("prompt-input")).to_be_visible()
```

The SQL textarea's testid is `query-input` (`frontend/src/app/QueryView.tsx:1154`). `e2e/` modules import helpers straight from `conftest`, as `test_query.py` does.

- [ ] **Step 4: Fix the two e2e tests that assert on localStorage**

`e2e/test_workspaces.py:43` — replace `page.evaluate("localStorage.setItem('qv_workspace', 'default')")` with a UI switch through the workspace dropdown, or drop the line if the test no longer needs to force a workspace.

`e2e/test_explorer.py:155` — replace the `localStorage.getItem('qv_view_explorer')` assertion with a reload-and-check: the sidebar keeps its dragged width after `page.reload()`.

- [ ] **Step 5: Run the whole suite**

With `npm run dev` running in another terminal:

```bash
uv run --group test pytest backend/queryview -v
npm run test -w frontend
uv run --group test pytest e2e -v
npm run lint -w frontend
uv run pre-commit run --all-files
```

Expected: all PASS, lint clean.

- [ ] **Step 6: Write `docs/session.md`**

Cover: what a session is; the `sessions` table; the claim protocol and its four-way attach decision; refresh vs new tab; the switcher; that `sessionStorage` holds identity and the server holds state; that restoring does not auto-run a query; that rows accumulate and are deleted by hand. Link it from `docs/queryview.md`.

- [ ] **Step 7: Update the other docs**

- `docs/queryview.md` — rewrite §Sessions and the landing rule (the `/` route now restores the session's URL).
- `docs/connect.md` — §"Sessions, cookies & auto-connect" is wrong: no cookie, no "latest active" auto-connect; a session remembers its own connection.
- `docs/api.md` — the §Sessions preamble, the six `/api/sessions/*` rows, the removal of `/api/remote/db`, and `/api/remote/events` taking `?session=`.
- `docs/remote.md` — the agent id is the session id; arming still gates, disarming still revokes.
- `docs/future.md` — no change needed.

- [ ] **Step 8: Delete the spec and this plan**

`CLAUDE.md`: "when a plan ships, delete its plan and spec in the same change".

```bash
git rm docs/superpowers/specs/2026-09-17-session-persistence-design.md \
       docs/superpowers/plans/2026-09-17-session-persistence.md
```

Check nothing links to them: `grep -rn "session-persistence" docs README.md CONTRIBUTING.md`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Identify sessions by header only, and document them

Removes the qv_session cookie now that the SPA sends X-QV-Session; the SSE
stream takes the id in its query string because EventSource cannot set headers.
Adds the session e2e suite and docs/session.md, and retires the shipped spec
and plan."
```

---

## Final verification

Run everything one more time from a clean data dir, to prove the migration path works for a user upgrading in place:

```bash
DATA_DIR=/tmp/qv-verify uv run --group test pytest backend/queryview -v
npm run test -w frontend
npm run lint -w frontend
npm run build          # tsc -b must pass with no unused-import errors from the deletions
uv run pre-commit run --all-files
```

Then, with `npm run dev` running: `uv run --group test pytest e2e -v`.

**Acceptance, checked by hand in a browser:**

- [ ] Refresh keeps the page, the URL, the connection, the database and the typed SQL.
- [ ] A second tab opened while the first is in use gets its own session.
- [ ] Closing the first tab and opening a new one resumes that session.
- [ ] The dropdown lists sessions, switches between them, renames and deletes.
- [ ] A session open in another tab is shown but not selectable.
- [ ] Arming remote control shows an id equal to the session id; pushing a query from the agent still works; disarming makes a push fail.
