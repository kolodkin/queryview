"""Predefined query store: reusable SQL keyed by connection type within a
workspace (names are unique per workspace). Reuses the SQLite engine owned by
connect.py."""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .connect import _engine_for_db, _ensure_schema


class PredefinedQuery(SQLModel, table=True):
    __tablename__: ClassVar[str] = "predefined_queries"
    __table_args__ = (UniqueConstraint("workspace_id", "type", "query_name", name="uq_predefined_ws_type_name"),)

    id: int | None = Field(default=None, primary_key=True)
    query_name: str = Field(index=True)
    type: str = Field(index=True)
    workspace_id: int  # owning workspace (workspaces.id); names unique per workspace
    query: str
    # Raw YAML (column_name -> {type, value}) controlling cell rendering; NULL =
    # none. Never parsed here — interpreted client-side, matched to columns by name.
    cell_view: str | None = Field(default=None)
    # Raw JSON text (or NULL) for saved presentation, stored verbatim like
    # cell_view: order_by is [{"name","dir"}], fields is ["col", ...].
    order_by: str | None = Field(default=None)
    fields: str | None = Field(default=None)
    # The git commit holding this row as it is; NULL = not in git yet. Every
    # write clears it, a successful commit sets it (docs/gitsync.md).
    git_sha: str | None = Field(default=None)


def _row_dict(r: PredefinedQuery) -> dict[str, Any]:
    """The row shape every accessor here returns (order_by/fields stay the
    stored JSON text)."""
    return {
        "query_name": r.query_name,
        "query": r.query,
        "cell_view": r.cell_view,
        "order_by": r.order_by,
        "fields": r.fields,
    }


async def list_predefined_queries(conn_type: str, workspace_id: int) -> list[dict[str, Any]]:
    """Saved queries for a connection type within one workspace, ordered by name."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        q = select(PredefinedQuery).where(
            PredefinedQuery.type == conn_type,
            PredefinedQuery.workspace_id == workspace_id,
        )
        rows = (await s.exec(q.order_by(PredefinedQuery.query_name))).all()
    return [_row_dict(r) for r in rows]


async def list_all_predefined_queries(workspace_id: int) -> list[dict[str, Any]]:
    """Every saved query in one workspace regardless of connection type,
    ordered by (type, name) — the row shape of list_predefined_queries plus
    `type`. Used by the whole-workspace YAML export."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = (
            await s.exec(
                select(PredefinedQuery)
                .where(PredefinedQuery.workspace_id == workspace_id)
                .order_by(PredefinedQuery.type, PredefinedQuery.query_name)
            )
        ).all()
    return [{"type": r.type, **_row_dict(r)} for r in rows]


async def _find(s: AsyncSession, conn_type: str, query_name: str, workspace_id: int) -> PredefinedQuery | None:
    """The row holding (workspace, type, name)."""
    return (
        await s.exec(
            select(PredefinedQuery).where(
                PredefinedQuery.type == conn_type,
                PredefinedQuery.query_name == query_name,
                PredefinedQuery.workspace_id == workspace_id,
            )
        )
    ).first()


async def get_predefined_query(conn_type: str, query_name: str, workspace_id: int) -> dict[str, Any] | None:
    """One saved query by (workspace, type, name) — the unique key — in the
    same row shape as list_predefined_queries items, or None."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
    return _row_dict(row) if row is not None else None


async def list_predefined_queries_view(conn_type: str, workspace_id: int) -> list[dict]:
    """Like list_predefined_queries but with order_by/fields parsed from their
    stored JSON text into values (cell_view stays raw YAML). Shared by the HTTP
    list endpoint and the MCP list_queries tool so both present the same shape."""
    import json

    rows = await list_predefined_queries(conn_type, workspace_id)
    for r in rows:
        ob, fl = r.get("order_by"), r.get("fields")
        r["order_by"] = json.loads(ob) if ob else None
        r["fields"] = json.loads(fl) if fl else None
    return rows


async def save_predefined_queries(rows: list[dict[str, Any]], *, workspace_id: int) -> None:
    """Upsert many predefined queries — each a dict with string `type`,
    `query_name`, `query` and optional `cell_view`/`order_by`/`fields` (JSON
    text or None) — in one transaction, keyed by (workspace, type, query_name)."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        for r in rows:
            row = await _find(s, r["type"], r["query_name"], workspace_id)
            if row is None:
                row = PredefinedQuery(query_name=r["query_name"], type=r["type"], workspace_id=workspace_id, query="")
            row.query = r["query"] or ""
            row.cell_view = r.get("cell_view")
            row.order_by = r.get("order_by")
            row.fields = r.get("fields")
            row.git_sha = None
            s.add(row)
        await s.commit()


async def save_predefined_query(
    query_name: str,
    conn_type: str,
    query: str,
    cell_view: str | None = None,
    order_by: str | None = None,
    fields: str | None = None,
    *,
    workspace_id: int,
) -> None:
    """Upsert a predefined query by (workspace, type, query_name)."""
    await save_predefined_queries(
        [
            {
                "type": conn_type,
                "query_name": query_name,
                "query": query,
                "cell_view": cell_view,
                "order_by": order_by,
                "fields": fields,
            }
        ],
        workspace_id=workspace_id,
    )


async def set_query_git_sha(
    conn_type: str, query_name: str, workspace_id: int, sha: str, *, unchanged_from: dict[str, Any] | None = None
) -> None:
    """Record the git commit holding this query — unless it is gone, or has
    changed since `unchanged_from` (its row as committed) was read."""
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
        if row is None or (unchanged_from is not None and _row_dict(row) != unchanged_from):
            return
        if row.git_sha is not None and unchanged_from is not None:
            return  # already marked: a sync finding it identical needn't rewrite every row
        row.git_sha = sha
        s.add(row)
        await s.commit()


async def snapshot_queries(conn_type: str, names: list[str], workspace_id: int) -> dict[str, dict[str, Any] | None]:
    """Each named row's full columns (None: no such row), for restore_queries."""
    await _ensure_schema()
    snap: dict[str, dict[str, Any] | None] = {}
    async with AsyncSession(_engine_for_db()) as s:
        for n in names:
            row = await _find(s, conn_type, n, workspace_id)
            snap[n] = row.model_dump(exclude={"id"}) if row is not None else None
    return snap


async def restore_queries(conn_type: str, snap: dict[str, dict[str, Any] | None], workspace_id: int) -> None:
    """Put the snapshot's rows back exactly, dropping rows it had as None."""
    async with AsyncSession(_engine_for_db()) as s:
        for n in snap:
            row = await _find(s, conn_type, n, workspace_id)
            if row is not None:
                await s.delete(row)
        await s.flush()  # free the (workspace, type, name) keys first
        for data in snap.values():
            if data is not None:
                s.add(PredefinedQuery(**data))
        await s.commit()


async def unsynced_queries(workspace_id: int) -> list[tuple[str, str]]:
    """(type, name) of every query not in git as it is."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = (
            await s.exec(
                select(PredefinedQuery)
                .where(PredefinedQuery.workspace_id == workspace_id, col(PredefinedQuery.git_sha).is_(None))
                .order_by(PredefinedQuery.type, PredefinedQuery.query_name)
            )
        ).all()
    return [(r.type, r.query_name) for r in rows]


class PredefinedQueryError(Exception):
    """A rename or delete that can't apply; `status` is the HTTP code."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


async def rename_predefined_query(conn_type: str, query_name: str, new_name: str, *, workspace_id: int) -> None:
    """Rename one saved query: 404 if it doesn't exist, 409 if `new_name` is taken."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
        if row is None:
            raise PredefinedQueryError(f"query {query_name!r} not found", status=404)
        if new_name != query_name:
            if await _find(s, conn_type, new_name, workspace_id) is not None:
                raise PredefinedQueryError(f"a query named {new_name!r} already exists", status=409)
            row.query_name = new_name
        row.git_sha = None
        s.add(row)
        await s.commit()


async def delete_predefined_query(conn_type: str, query_name: str, *, workspace_id: int) -> None:
    """Delete one saved query for good; 404 if it doesn't exist."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
        if row is None:
            raise PredefinedQueryError(f"query {query_name!r} not found", status=404)
        await s.delete(row)
        await s.commit()
