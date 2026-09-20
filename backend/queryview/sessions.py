"""Session domain: a browser tab's persisted UI state — route and URL, active
connection and database, workspace, and per-view settings. One row per session;
a session is claimed by at most one tab at a time (see `attach`). No HTTP
concerns here. Docs: docs/session.md."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy.orm import load_only
from sqlmodel import Field, SQLModel, col, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from .connect import _engine_for_db, _ensure_schema, _now_ms

# A claim older than this is stale: the tab closed, crashed or slept, and the
# session is free for the next tab that asks.
SESSION_CLAIM_TTL_MS = 30_000

DEFAULT_URL = "/queries"


def _open() -> AsyncSession:
    """A session whose rows stay readable after commit. Every value written here
    is assigned in Python — nothing is server-generated — so expiring on commit
    only bought a redundant re-SELECT per write."""
    return AsyncSession(_engine_for_db(), expire_on_commit=False)


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
    claimed_by: str | None = Field(default=None, index=True)  # tab token
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


def _label(label: str | None, seq: int) -> str:
    """A pinned name, else the stable ordinal. Connection and database are shown
    beside the name rather than folded into it, so a session's name does not
    change under you when you switch databases."""
    return label or f"Session {seq}"


def display_label(rec: SessionRec) -> str:
    return _label(rec.label, rec.seq)


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


def _unheld_query(now: int):
    """The session a new tab should resume: most recently active, not held."""
    stale = now - SESSION_CLAIM_TTL_MS
    return (
        select(Session)
        .where(
            col(Session.claimed_by).is_(None)
            | col(Session.claim_seen_at).is_(None)
            | (col(Session.claim_seen_at) < stale)
        )
        .order_by(col(Session.last_active_at).desc())
        .limit(1)
    )


async def _new_row(s: AsyncSession, now: int) -> Session:
    """A fresh row in the caller's transaction, so a create-and-claim is one pass."""
    next_seq = (await s.exec(select(func.coalesce(func.max(Session.seq), 0)))).one() + 1
    row = Session(id=uuid.uuid4().hex, seq=next_seq, last_active_at=now)
    s.add(row)
    return row


async def create_session() -> SessionRec:
    """A fresh, unclaimed session at the default route."""
    await _ensure_schema()
    now = _now_ms()
    async with _open() as s:
        row = await _new_row(s, now)
        await s.commit()
        return _to_rec(row, now)


async def get_session_rec(sid: str) -> SessionRec | None:
    await _ensure_schema()
    async with _open() as s:
        row = await s.get(Session, sid)
        return _to_rec(row) if row else None


async def list_sessions() -> list[dict[str, Any]]:
    """Every session, most recently active first — the dropdown's rows. Reads
    only the columns a row needs, so opening the dropdown does not pull (and
    JSON-parse) every session's saved SQL."""
    await _ensure_schema()
    now = _now_ms()
    async with _open() as s:
        rows = (
            await s.exec(
                select(Session)
                .options(
                    load_only(
                        Session.seq,  # type: ignore[arg-type]
                        Session.label,  # type: ignore[arg-type]
                        Session.connection_name,  # type: ignore[arg-type]
                        Session.database,  # type: ignore[arg-type]
                        Session.claimed_by,  # type: ignore[arg-type]
                        Session.claim_seen_at,  # type: ignore[arg-type]
                    )
                )
                .order_by(col(Session.last_active_at).desc())
            )
        ).all()
    return [
        {
            "id": r.id,
            "label": _label(r.label, r.seq),
            "connection": r.connection_name,
            "database": r.database,
            "held": bool(
                r.claimed_by and r.claim_seen_at is not None and (now - r.claim_seen_at) < SESSION_CLAIM_TTL_MS
            ),
        }
        for r in rows
    ]


async def patch_session(
    sid: str,
    *,
    url: str | None = None,
    ui: dict[str, Any] | None = None,
    label: str | None = None,
    workspace: str | None = None,
) -> SessionRec | None:
    """Apply the fields given; `ui` merges, the rest replace. The updated record
    comes back so callers see server-derived values (the label an empty `label`
    unpins). None if the session is unknown."""
    await _ensure_schema()
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return None
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
        return _to_rec(row)


async def delete_session(sid: str) -> tuple[bool, str]:
    """Remove a session. Refused while a live tab holds it. The second element is
    a reason code ("unknown" / "held"), not prose: the route maps it to a status,
    so rewording a message cannot change an HTTP code."""
    await _ensure_schema()
    now = _now_ms()
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return False, "unknown"
        if _is_held(row, now):
            return False, "held"
        await s.delete(row)
        await s.commit()
        return True, ""


# --- Claims (one tab holds a session at a time) ---------------------------


async def _claim(s: AsyncSession, row: Session, tab: str, now: int) -> None:
    """Take the session for `tab` and free whatever else that tab held. The
    release is one UPDATE rather than a scan: this runs on every heartbeat, and
    the rows it would otherwise hydrate carry the saved SQL."""
    await s.exec(
        update(Session)
        .where(col(Session.claimed_by) == tab, col(Session.id) != row.id)
        .values(claimed_by=None, claim_seen_at=None)
    )
    row.claimed_by = tab
    row.claim_seen_at = now
    row.last_active_at = now
    s.add(row)


async def attach(tab: str, session_id: str | None, force_new: bool = False) -> tuple[SessionRec, bool]:
    """Resolve and claim the session this tab should show: the id it already has,
    else the most recently active unheld session, else a fresh one.

    Decided in one server-side pass so concurrent tabs can't race. The first
    case falls through when another live tab holds that id — a duplicated tab
    carries a copy of sessionStorage and must not hijack the original.
    """
    await _ensure_schema()
    now = _now_ms()
    async with _open() as s:
        row = None if force_new else await s.get(Session, session_id) if session_id else None
        if row is not None and (not _is_held(row, now) or row.claimed_by == tab):
            await _claim(s, row, tab, now)
            await s.commit()
            return _to_rec(row, now), False

        free = None if force_new else (await s.exec(_unheld_query(now))).first()
        if free is not None:
            await _claim(s, free, tab, now)
            await s.commit()
            return _to_rec(free, now), False

        row = await _new_row(s, now)
        await _claim(s, row, tab, now)
        await s.commit()
        return _to_rec(row, now), True


async def select_session(tab: str, sid: str | None) -> tuple[SessionRec | None, str]:
    """Switch this tab to a specific session, or to a brand-new one when `sid`
    is None. Refuses a session another live tab holds — two tabs on one session
    would overwrite each other's state."""
    if sid is None:
        rec, _ = await attach(tab, None, force_new=True)
        return rec, ""
    await _ensure_schema()
    now = _now_ms()
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return None, "unknown"
        if _is_held(row, now) and row.claimed_by != tab:
            return None, "held"
        await _claim(s, row, tab, now)
        await s.commit()
        return _to_rec(row, now), ""


async def release(tab: str) -> None:
    """Drop whatever this tab holds (the pagehide beacon). Idempotent; the TTL
    covers the tab that never got to send it."""
    await _ensure_schema()
    async with _open() as s:
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
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        if claim_seen_at is not None:
            row.claim_seen_at = claim_seen_at
        if last_active_at is not None:
            row.last_active_at = last_active_at
        s.add(row)
        await s.commit()


async def set_connection(sid: str, connection_name: str | None) -> None:
    """Record which connection a session is on, clearing its database — both
    connecting and disconnecting reset the picker. A None name is the durable
    disconnected state; there is no separate 'disconnected' set."""
    await _ensure_schema()
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        row.connection_name = connection_name
        row.database = None
        row.last_active_at = _now_ms()
        s.add(row)
        await s.commit()


async def set_database(sid: str, database: str | None) -> None:
    await _ensure_schema()
    async with _open() as s:
        row = await s.get(Session, sid)
        if row is None:
            return
        row.database = database
        row.last_active_at = _now_ms()
        s.add(row)
        await s.commit()


async def _scope_of(sid: str) -> tuple[str | None, str | None]:
    """A session's (database, workspace). Column-scoped: every MCP tool call
    lands here, and the full row carries the ui blob."""
    await _ensure_schema()
    async with _open() as s:
        row = (await s.exec(select(Session.database, Session.workspace).where(Session.id == sid))).first()
    if row is None:
        return None, None
    database, workspace = row
    return database, workspace


async def database_of(sid: str) -> str | None:
    return (await _scope_of(sid))[0]


async def workspace_of(sid: str) -> str | None:
    return (await _scope_of(sid))[1]
