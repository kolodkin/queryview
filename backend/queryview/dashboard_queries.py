"""Run a dashboard's named SQL on a session's connection and selected
database — the viewer's, never one the dashboard names. Dashboard persistence
lives in dashboards.py."""

from __future__ import annotations

from typing import Any

from .connect import _gated_session
from .drivers import DRIVERS
from .drivers.base import rows_to_columns

# Row cap per dashboard query (matches /api/clickhouse/query's ceiling), applied
# as the LIMIT of the subselect wrapping each query.
DASHBOARD_ROW_CAP = 1000


async def run_dashboard_queries(
    sid: str,
    queries: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """Run a dashboard's named queries on session `sid`'s connection and
    selected database. Fail-fast: not connected, no database selected, or the
    first failing query aborts the call (`reason`: no-session / no-database /
    query). On full success returns {"ok": True, "results": {name: {col:
    [values, …]}}, "meta": {name: [{name, type}, …]}} — column-oriented, ready
    for window.queries, values typed as the driver returned them.
    `limit`/`offset` page each query (default: the dashboard row cap, from row 0)."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    driver = DRIVERS[s.type]
    results: dict[str, dict[str, list[Any]]] = {}
    meta: dict[str, list[dict[str, str]]] = {}
    for qname, sql in queries.items():
        r = await driver.run_query(s.config, sql, s.database, limit=limit, offset=offset, order_by=None)
        if not r.ok or r.rows is None:
            return {"ok": False, "reason": "query", "message": f"{qname}: {r.message}"}
        results[qname] = rows_to_columns(r.rows)
        meta[qname] = [c._asdict() for c in r.rows.meta]
    return {"ok": True, "results": results, "meta": meta}
