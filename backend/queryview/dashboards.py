"""Dashboard store: dashboards (HTML layout + named SQL queries) keyed by name
within a workspace. Reuses connect.py's SQLite engine, mirroring queries.py.
Also hosts the shared upsert-and-push helper that both the REST endpoint and
the MCP tool call."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from . import remote, workspaces
from .connect import _engine_for_db, _ensure_schema, _now_ms


class Dashboard(SQLModel, table=True):
    __tablename__: ClassVar[str] = "dashboards"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_dashboards_ws_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # unique per workspace, not globally
    workspace_id: int  # owning workspace (workspaces.id)
    html: str  # agent-authored HTML document
    queries: str  # JSON text: {query_name: SQL}
    params: str = Field(default="[]")  # JSON text: selector specs (docs/dashboard.md)
    updated_at: int  # unix ms


async def upsert_dashboards(items: list[dict[str, Any]], *, workspace_id: int) -> None:
    """Upsert many dashboards — each a dict with `name`, `html`, a `queries`
    dict and an optional `params` list — in one transaction, keyed by
    (workspace, name). `queries` and `params` are serialized to JSON text."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        for d in items:
            row = (
                await s.exec(
                    select(Dashboard).where(Dashboard.name == d["name"], Dashboard.workspace_id == workspace_id)
                )
            ).first()
            if row is None:
                row = Dashboard(name=d["name"], workspace_id=workspace_id, html="", queries="", updated_at=0)
            row.html = d["html"]
            row.queries = json.dumps(d["queries"])
            row.params = json.dumps(d.get("params") or [])
            row.updated_at = _now_ms()
            s.add(row)
        await s.commit()


async def upsert_dashboard(
    name: str,
    html: str,
    queries: dict[str, str],
    params: list[dict[str, Any]] | None = None,
    *,
    workspace_id: int,
) -> None:
    """Upsert a dashboard by (workspace, name); `queries`/`params` are serialized to JSON text."""
    await upsert_dashboards(
        [{"name": name, "html": html, "queries": queries, "params": params or []}], workspace_id=workspace_id
    )


def _payload(row: Dashboard) -> dict[str, Any]:
    """A row's full payload with `queries`/`params` parsed back (leniently —
    unparsable stored text degrades to empty)."""
    return {
        "name": row.name,
        "html": row.html,
        "queries": _loads(row.queries, {}),
        "params": _loads(row.params, []),
    }


def _loads(text: str, empty: Any) -> Any:
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return empty
    return value if isinstance(value, type(empty)) else empty


async def get_dashboard(name: str, workspace_id: int) -> dict[str, Any] | None:
    """A single dashboard with its `queries` parsed back to a dict, or None."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (
            await s.exec(select(Dashboard).where(Dashboard.name == name, Dashboard.workspace_id == workspace_id))
        ).first()
    return _payload(row) if row is not None else None


async def list_dashboards(workspace_id: int) -> list[dict[str, Any]]:
    """One workspace's dashboards ordered by name, without the html/queries payload."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = (
            await s.exec(select(Dashboard).where(Dashboard.workspace_id == workspace_id).order_by(Dashboard.name))
        ).all()
    return [{"name": r.name, "updated_at": r.updated_at} for r in rows]


async def list_dashboards_full(workspace_id: int) -> list[dict[str, Any]]:
    """One workspace's dashboards ordered by name, with the full payload in
    get_dashboard's shape (`queries` parsed to a dict). Used by the
    whole-workspace YAML export."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = (
            await s.exec(select(Dashboard).where(Dashboard.workspace_id == workspace_id).order_by(Dashboard.name))
        ).all()
    return [_payload(r) for r in rows]


def _dashboard_event(
    name: str, html: str, queries: dict[str, str], params: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The SSE payload the browser renders for a pushed dashboard."""
    return {
        "type": "dashboard",
        "name": name,
        "html": html,
        "queries": queries,
        "params": params or [],
    }


async def _push_dashboard(
    name: str,
    html: str,
    queries: dict[str, str],
    session_id: str | None,
    params: list[dict[str, Any]] | None = None,
    workspace: str | None = None,
) -> tuple[bool, bool, str]:
    """Push a dashboard to a live session. A DRAFT unless `workspace` (the
    session's) has autosave on: then a delivered push is also persisted — only
    once delivered, since a disarmed session grants nothing. Otherwise only the
    user's Save (POST /api/dashboards) writes it. Returns (pushed, persisted,
    message); no session_id -> (False, False, "no session")."""
    if not session_id:
        return False, False, "no session"
    pushed, message = remote.push(session_id, _dashboard_event(name, html, queries, params))
    if not pushed:
        return False, False, message
    ws = await (workspaces.resolve(workspace) if workspace else workspaces.fallback())
    if not ws.autosave:
        return True, False, message
    await upsert_dashboard(name, html, queries, params, workspace_id=ws.id)
    return True, True, message


async def _upsert_and_push(
    name: str,
    html: str,
    queries: dict[str, str],
    session_id: str | None,
    params: list[dict[str, Any]] | None = None,
    *,
    workspace_id: int,
) -> tuple[bool, bool, str]:
    """Persist a dashboard, then (if `session_id` given) push it to that live
    browser session. Returns (persisted, pushed, message). Push is best-effort:
    an unknown/inactive session leaves it saved with pushed=False, per
    remote.push's contract. Used by the REST endpoint (the user-Save path)."""
    await upsert_dashboard(name, html, queries, params, workspace_id=workspace_id)
    if session_id:
        ok, message = remote.push(session_id, _dashboard_event(name, html, queries, params))
        return True, ok, message
    return True, False, "persisted"
