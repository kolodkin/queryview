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


async def select_session(tab: str, sid: str | None) -> tuple[SessionRec | None, str]:
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


async def touch_for_test(
    sid: str,
    *,
    claim_seen_at: int | None = None,
    last_active_at: int | None = None,
) -> None:
    """Move a session's timestamps from a test. The claim-TTL and most-recent
    branches are otherwise only reachable by waiting, or by hoping two rows
    land in different milliseconds."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        if claim_seen_at is not None:
            row.claim_seen_at = claim_seen_at
        if last_active_at is not None:
            row.last_active_at = last_active_at
        s.add(row)
        await s.commit()
