"""Predefined query store: reusable SQL keyed by connection type within a
workspace (names are unique per workspace). Deleting is soft: the row stays,
marked with `deleted_at`, until it is saved again or undeleted. Reuses the
SQLite engine owned by connect.py."""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .connect import _engine_for_db, _ensure_schema, _now_ms


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
    # Unix ms when deleted; NULL = live. Deleted rows keep their content and
    # still hold their name.
    deleted_at: int | None = Field(default=None)


def _row_dict(r: PredefinedQuery) -> dict[str, Any]:
    """The row shape every accessor here returns (order_by/fields stay the
    stored JSON text; deleted_at is None for a live query)."""
    return {
        "query_name": r.query_name,
        "query": r.query,
        "cell_view": r.cell_view,
        "order_by": r.order_by,
        "fields": r.fields,
        "deleted_at": r.deleted_at,
    }


def _live():
    """The WHERE clause for live (not deleted) rows."""
    return col(PredefinedQuery.deleted_at).is_(None)


async def list_predefined_queries(
    conn_type: str, workspace_id: int, *, include_deleted: bool = False
) -> list[dict[str, Any]]:
    """Saved queries for a connection type within one workspace, ordered by
    name: the live ones, plus the deleted ones with `include_deleted`."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        q = select(PredefinedQuery).where(
            PredefinedQuery.type == conn_type,
            PredefinedQuery.workspace_id == workspace_id,
        )
        if not include_deleted:
            q = q.where(_live())
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
                .where(PredefinedQuery.workspace_id == workspace_id, _live())
                .order_by(PredefinedQuery.type, PredefinedQuery.query_name)
            )
        ).all()
    return [{"type": r.type, **_row_dict(r)} for r in rows]


async def _find(s: AsyncSession, conn_type: str, query_name: str, workspace_id: int) -> PredefinedQuery | None:
    """The row holding (workspace, type, name), live or deleted."""
    return (
        await s.exec(
            select(PredefinedQuery).where(
                PredefinedQuery.type == conn_type,
                PredefinedQuery.query_name == query_name,
                PredefinedQuery.workspace_id == workspace_id,
            )
        )
    ).first()


async def get_predefined_query(
    conn_type: str, query_name: str, workspace_id: int, *, include_deleted: bool = False
) -> dict[str, Any] | None:
    """One live saved query by (workspace, type, name) — the unique key — in
    the same row shape as list_predefined_queries items, or None. With
    `include_deleted` a deleted row counts too."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
    if row is None or (row.deleted_at is not None and not include_deleted):
        return None
    return _row_dict(row)


async def list_predefined_queries_view(
    conn_type: str, workspace_id: int, *, include_deleted: bool = False
) -> list[dict]:
    """Like list_predefined_queries but with order_by/fields parsed from their
    stored JSON text into values (cell_view stays raw YAML). Shared by the HTTP
    list endpoint and the MCP list_queries tool so both present the same shape."""
    import json

    rows = await list_predefined_queries(conn_type, workspace_id, include_deleted=include_deleted)
    for r in rows:
        ob, fl = r.get("order_by"), r.get("fields")
        r["order_by"] = json.loads(ob) if ob else None
        r["fields"] = json.loads(fl) if fl else None
    return rows


async def save_predefined_queries(rows: list[dict[str, Any]], *, workspace_id: int) -> None:
    """Upsert many predefined queries — each a dict with string `type`,
    `query_name`, `query` and optional `cell_view`/`order_by`/`fields` (JSON
    text or None) and `deleted` — in one transaction, keyed by (workspace,
    type, query_name). Saving over a deleted query brings it back unless
    `deleted` is set."""
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
            # A deleted row saved deleted again keeps its original deletion time.
            row.deleted_at = (row.deleted_at or _now_ms()) if r.get("deleted") else None
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
    deleted: bool = False,
) -> None:
    """Upsert a predefined query by (workspace, type, query_name), live or
    (`deleted`) deleted."""
    await save_predefined_queries(
        [
            {
                "type": conn_type,
                "query_name": query_name,
                "query": query,
                "cell_view": cell_view,
                "order_by": order_by,
                "fields": fields,
                "deleted": deleted,
            }
        ],
        workspace_id=workspace_id,
    )


class PredefinedQueryError(Exception):
    """A rename/delete/undelete that can't apply; `status` is the HTTP code."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


async def update_predefined_query(
    conn_type: str,
    query_name: str,
    *,
    workspace_id: int,
    new_name: str | None = None,
    deleted: bool | None = None,
    strict: bool = True,
) -> None:
    """Rename (`new_name`) and/or delete or undelete (`deleted`) one saved
    query, all or nothing in one transaction. Renaming applies to a live
    query: an undelete happens before it, a delete after. 404 when the query
    doesn't exist in the state the change needs, 409 when `new_name` is taken,
    by a live or a deleted query. `strict=False` turns "already in the
    `deleted` state" into a no-op, for a git sync acting on an earlier read."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = await _find(s, conn_type, query_name, workspace_id)
        was_deleted = row is not None and row.deleted_at is not None
        live_after_undelete = not was_deleted or deleted is False
        already = deleted is not None and was_deleted == deleted
        if row is None or (already and strict) or (new_name and not live_after_undelete):
            what = "deleted query" if deleted is False else "query"
            raise PredefinedQueryError(f"{what} {query_name!r} not found", status=404)
        if new_name and new_name != query_name:
            taken = await _find(s, conn_type, new_name, workspace_id)
            if taken is not None:
                what = "a deleted query" if taken.deleted_at is not None else "a query"
                raise PredefinedQueryError(f"{what} named {new_name!r} already exists", status=409)
            row.query_name = new_name
        if deleted is not None and not already:
            row.deleted_at = _now_ms() if deleted else None
        s.add(row)
        await s.commit()


async def rename_predefined_query(conn_type: str, query_name: str, new_name: str, *, workspace_id: int) -> None:
    """Rename one live saved query (see update_predefined_query)."""
    await update_predefined_query(conn_type, query_name, workspace_id=workspace_id, new_name=new_name)


async def set_predefined_query_deleted(conn_type: str, query_name: str, deleted: bool, *, workspace_id: int) -> None:
    """Delete (soft) or undelete one saved query. 404 unless it exists in the
    other state."""
    await update_predefined_query(conn_type, query_name, workspace_id=workspace_id, deleted=deleted)
