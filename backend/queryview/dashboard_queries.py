"""Run a dashboard's named SQL on a session's connection and selected
database — the viewer's, never one the dashboard names — with its params
resolved and substituted here. Dashboard persistence lives in dashboards.py."""

from __future__ import annotations

import asyncio
from typing import Any

from .connect import _gated_session
from .dashboard_params import Dialect, Param, ParamError, apply_to_queries, missing, parse_params, resolve, substitute
from .drivers import DRIVERS
from .drivers.base import Driver, DriverConfig, Err, RowsResult, rows_to_columns

# Row cap per dashboard query (matches /api/clickhouse/query's ceiling), applied
# as the LIMIT of the subselect wrapping each query.
DASHBOARD_ROW_CAP = 1000

# Most queries of one run in flight at once.
# shortcut: per run, not per connection, so N runs at once make 5N queries;
# share one limit per connection if a database starts refusing connections.
DASHBOARD_CONCURRENCY = 5

WAITING = "Waiting for a parameter choice."


def dialect_of(driver: Driver) -> Dialect:
    return Dialect(driver.ident_quote, driver.backslash_escapes)


def _sendable(text: str) -> bool:
    """Whether a reply can carry it: JSON parses a lone surrogate that UTF-8 cannot encode."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def clean_values(raw: object) -> dict[str, str]:
    """A request's param values: the string entries of a mapping, the rest dropped."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str) and _sendable(k) and _sendable(v)}


def resolved_part(r: dict[str, Any]) -> dict[str, Any]:
    """A run's resolved selectors as its reply carries them, on success or
    failure: absent when the run failed before resolving."""
    return {"params": r["params"]} if "params" in r else {}


def _params_error(message: str) -> dict[str, Any]:
    return {"ok": False, "reason": "params", "message": message}


def ready_sql(sql: str, params: object, values: dict[str, str], dialect: Dialect) -> tuple[str | None, str | None]:
    """One query with `values` substituted as given: (sql, None), or (None, why not)."""
    declared = parse_params(params)
    if missing(sql, declared, values):
        return None, WAITING
    try:
        return substitute(sql, declared, values, dialect), None
    except ParamError as e:
        return None, str(e)


async def run_queries_on(
    driver: Driver,
    config: DriverConfig,
    database: str | None,
    queries: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """Run named queries on one connection, DASHBOARD_CONCURRENCY at a time.
    Fail-fast: the first failing query, in the order given, aborts the call
    (`reason`: query) and cancels the ones still running. On full success
    returns {"ok": True, "results": {name: {col: [values, …]}}, "meta": {name:
    [{name, type}, …]}} — column-oriented, ready for window.queries, values
    typed as the driver returned them. `limit`/`offset` page each query."""
    slots = asyncio.Semaphore(DASHBOARD_CONCURRENCY)

    async def one(sql: str) -> RowsResult | Err:
        async with slots:
            return await driver.run_query(config, sql, database, limit=limit, offset=offset, order_by=None)

    tasks = {qname: asyncio.create_task(one(sql)) for qname, sql in queries.items()}
    results: dict[str, dict[str, list[Any]]] = {}
    meta: dict[str, list[dict[str, str]]] = {}
    try:
        for qname in queries:
            r = await tasks.pop(qname)  # popped: its rows are not kept twice
            if isinstance(r, Err):
                return {"ok": False, "reason": "query", "message": f"{qname}: {r.message}"}
            results[qname] = rows_to_columns(r.rows)
            meta[qname] = [c._asdict() for c in r.rows.meta]
    finally:
        # A failure, or the caller gone: the rest are cancelled, which stops
        # them wherever the driver can (drivers/duckdb.py interrupts its own).
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {"ok": True, "results": results, "meta": meta}


async def resolve_on(
    driver: Driver, config: DriverConfig, database: str | None, params: list[Param], values: dict[str, str]
) -> list[dict[str, Any]]:
    """Selectors resolved on one connection: their options_sql run there, each
    value kept only while its options offer it. Raises ParamError."""

    async def options(sql: str) -> list[Any]:
        r = await driver.run_query(config, sql, database, limit=DASHBOARD_ROW_CAP, offset=0, order_by=None)
        if isinstance(r, Err):
            raise ParamError(r.message)
        return [row[0] if row else None for row in r.rows.data]

    return await resolve(params, values, options, dialect_of(driver))


async def run_dashboard_on(
    driver: Driver,
    config: DriverConfig,
    database: str | None,
    queries: dict[str, str],
    params: object,
    values: dict[str, str],
) -> dict[str, Any]:
    """Resolve the selectors, then run the queries that are ready (one waiting
    on a choice is left out). run_queries_on's reply plus "params":
    [{name, kind, options, value}] — also on a failing query, so the page keeps
    its selectors. A bad declaration or value fails with `reason`: params."""
    try:
        declared = parse_params(params)
        resolved = await resolve_on(driver, config, database, declared, values)
        runnable = apply_to_queries(queries, declared, resolved, dialect_of(driver))
    except ParamError as e:
        return _params_error(str(e))
    return {**await run_queries_on(driver, config, database, runnable), "params": resolved}


async def run_dashboard_queries(
    sid: str,
    queries: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """run_queries_on session `sid`'s connection and selected database. Not
    connected or no database selected fails first (`reason`: no-session /
    no-database)."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    return await run_queries_on(DRIVERS[s.type], s.config, s.database, queries, limit, offset)


async def _no_options(sql: str) -> list[Any]:
    return []


async def run_dashboard(sid: str, queries: dict[str, str], params: object, values: dict[str, str]) -> dict[str, Any]:
    """run_dashboard_on session `sid`'s connection and selected database."""
    declared = parse_params(params)
    if not queries and not any(p.options_sql for p in declared):
        # Nothing touches the database, so no session is needed: a page of
        # static selectors (or of widgets alone) still renders disconnected.
        # No options_sql: the runner and dialect are never used.
        resolved = await resolve(declared, values, _no_options, Dialect('"', False))
        return {"ok": True, "results": {}, "meta": {}, "params": resolved}
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    return await run_dashboard_on(DRIVERS[s.type], s.config, s.database, queries, params, values)


async def session_sql(
    sid: str, sql: str, params: object, values: dict[str, str]
) -> tuple[str | None, dict[str, Any] | None]:
    """One query (a widget's) with `values` substituted on session `sid`'s
    dialect: (sql, None), or (None, a failed reply) whose `reason` is the
    session gate's or params."""
    s, err = await _gated_session(sid)
    if s is None:
        return None, err
    ready, why = ready_sql(sql, params, values, dialect_of(DRIVERS[s.type]))
    return (ready, None) if ready is not None else (None, _params_error(why or WAITING))
