"""Run a dashboard's named SQL against a connection by name, decoupled from any
session/cookie. Reads the saved connection (and its stored database) via
connect.py, queries via the driver registry; dashboard persistence lives in
dashboards.py."""

from __future__ import annotations

from typing import Any

from .connect import _connection_by_name, unknown_connection_message
from .drivers import DRIVERS
from .drivers.base import rows_to_columns

# Row cap per dashboard query (matches /api/clickhouse/query's ceiling), applied
# as the LIMIT of the subselect wrapping each query.
DASHBOARD_ROW_CAP = 1000


async def run_queries_for_connection(
    name: str,
    queries: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """Run a dashboard's named queries against a saved connection by name.
    Fail-fast: an unknown connection, no selected database, or the first failing
    query aborts the call. On full success returns {"ok": True, "results": {name:
    {col: [values, …]}}, "meta": {name: [{name, type}, …]}} — column-oriented,
    ready for window.queries, values typed as the driver returned them.
    `limit`/`offset` page each query (default: the dashboard row cap, from row 0)."""
    stored = await _connection_by_name(name)
    if stored is None:
        return {
            "ok": False,
            "reason": "no-connection",
            "message": await unknown_connection_message(name),
        }
    driver = DRIVERS[stored.type]
    if driver.requires_database and not stored.database:
        return {
            "ok": False,
            "reason": "no-database",
            "message": (
                f'connection "{name}" has no selected database — select one for it '
                "or fully-qualify table names as db.table"
            ),
        }
    results: dict[str, dict[str, list[Any]]] = {}
    meta: dict[str, list[dict[str, str]]] = {}
    for qname, sql in queries.items():
        r = await driver.run_query(stored.config, sql, stored.database, limit=limit, offset=offset, order_by=None)
        if not r.ok or r.rows is None:
            return {"ok": False, "reason": "query", "message": f"{qname}: {r.message}"}
        results[qname] = rows_to_columns(r.rows)
        meta[qname] = [c._asdict() for c in r.rows.meta]
    return {"ok": True, "results": results, "meta": meta}
