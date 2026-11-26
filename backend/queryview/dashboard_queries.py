"""Run a dashboard's named SQL with its params resolved and substituted here.
Queries run on the session's connection and selected database (the caller's
one `default` target) unless their entry names a connection: then the
dashboard is federated, and each query and `options_sql` runs on the target
the caller's `Lookup` gives for its connection, quoted in that target's
dialect. Each `(connection, database)` is looked up once per run, before any
query runs, and the reply carries `connections`. Dashboard persistence lives
in dashboards.py; the entry shape in dashboard_entries.py."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .connect import _gated_session, connection_target
from .dashboard_entries import MIXED, Entry, entry_connection, entry_sql, is_federated
from .dashboard_params import (
    Dialect,
    Param,
    ParamError,
    apply_to_queries,
    each_in,
    missing,
    option_text,
    parse_params,
    resolve,
    substitute,
)
from .drivers import DRIVERS
from .drivers.base import Driver, DriverConfig, Err, QueryRows, RowsResult, rows_to_columns

# Row cap per dashboard query (matches /api/clickhouse/query's ceiling), applied
# as the LIMIT of the subselect wrapping each query.
DASHBOARD_ROW_CAP = 1000

# Most queries of one run in flight at once.
# shortcut: per run, not per connection, so N runs at once make 5N queries;
# share one limit per connection if a database starts refusing connections.
DASHBOARD_CONCURRENCY = 5

WAITING = "Waiting for a parameter choice."
NO_FAN_OUT = "a widget cannot page a query run per value"


@dataclass(frozen=True)
class Target:
    """Where a query runs: a driver, its connection config, and the database."""

    driver: Driver
    config: DriverConfig
    database: str | None


@dataclass(frozen=True)
class LookupError_:
    """Why a connection has no target: `status` unknown, locked or failed (no
    database), and the message without the query's name."""

    status: str
    message: str


# A connection name and an entry's `database` -> its target, or why not.
Lookup = Callable[[str, str | None], Awaitable[Target | LookupError_]]
Pair = tuple[str, str | None]


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
    """A request's param values: the string entries of a mapping, a number or
    boolean as the text the page would send, the rest dropped."""
    if not isinstance(raw, dict):
        return {}
    texts = {k: option_text(v) if isinstance(v, (bool, int, float)) else v for k, v in raw.items()}
    return {
        k: v for k, v in texts.items() if isinstance(k, str) and isinstance(v, str) and _sendable(k) and _sendable(v)
    }


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
        if each_in(sql, declared):
            return None, NO_FAN_OUT
        return substitute(sql, declared, values, dialect), None
    except ParamError as e:
        return None, str(e)


async def run_queries_on(
    targets: Mapping[str, Target],
    queries: Mapping[str, str | dict[str, str]],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """Run named queries, each on `targets[name]`, DASHBOARD_CONCURRENCY at a
    time across them all.
    Fail-fast: the first failing query, in the order given, aborts the call
    (`reason`: query) and cancels the ones still running. On full success
    returns {"ok": True, "results": {name: {col: [values, …]}}, "meta": {name:
    [{name, type}, …]}} — column-oriented, ready for window.queries, values
    typed as the driver returned them. `limit`/`offset` page each query.

    A query given as `{value: sql}` runs every SQL and is the rows of all of
    them, stacked in that order and cut at `limit`; the runs must return the
    same columns. See docs/system/dashboard.md — "A query run once per value"."""
    return (await _run_queries(targets, queries, limit, offset))[0]


async def _run_queries(
    targets: Mapping[str, Target], queries: Mapping[str, str | dict[str, str]], limit: int, offset: int
) -> tuple[dict[str, Any], str | None]:
    """run_queries_on's reply, and the name of the query that failed it."""
    slots = asyncio.Semaphore(DASHBOARD_CONCURRENCY)

    async def one(t: Target, sql: str) -> RowsResult | Err:
        async with slots:
            return await t.driver.run_query(t.config, sql, t.database, limit=limit, offset=offset, order_by=None)

    # One run per SQL: a plain query's under None, a fan-out's under each value.
    runs = {qname: {None: sql} if isinstance(sql, str) else sql for qname, sql in queries.items()}
    tasks = {(q, v): asyncio.create_task(one(targets[q], sql)) for q, parts in runs.items() for v, sql in parts.items()}
    results: dict[str, dict[str, list[Any]]] = {}
    meta: dict[str, list[dict[str, str]]] = {}
    try:
        for qname, parts in runs.items():
            stacked: QueryRows | None = None
            for value in parts:
                task = tasks.pop((qname, value))  # popped: its rows are not kept twice
                if stacked is not None and len(stacked.data) >= limit:
                    task.cancel()  # full: the values left free their slots unread
                    continue
                r = await task
                if isinstance(r, Err):
                    label = qname if value is None else f"{qname}[{value}]"
                    return {"ok": False, "reason": "query", "message": f"{label}: {r.message}"}, qname
                if stacked is None:
                    stacked = r.rows
                elif [c.name for c in r.rows.meta] != [c.name for c in stacked.meta]:
                    return {"ok": False, "reason": "query", "message": f"{qname}: columns differ between values"}, qname
                else:
                    stacked.data.extend(r.rows.data[: limit - len(stacked.data)])
            stacked = stacked or QueryRows([], [])  # an `each` with no values
            results[qname] = rows_to_columns(stacked)
            meta[qname] = [c._asdict() for c in stacked.meta]
    finally:
        # A failure, or the caller gone: the rest are cancelled, which stops
        # them wherever the driver can (drivers/duckdb.py interrupts its own).
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {"ok": True, "results": results, "meta": meta}, None


def _pair(connection: str | None, database: str | None) -> Pair:
    # "" for what names no connection: a mixed dashboard then fails its lookup.
    return (connection or "", database)


def _entry_pair(entry: Entry) -> Pair:
    return _pair(*(entry_connection(entry) or (None, None)))


async def _look_up(lookup: Lookup | None, pairs: list[Pair]) -> dict[Pair, Target | LookupError_]:
    """Each distinct pair looked up once, in first-use order."""
    assert lookup is not None, "a federated run needs a lookup"
    found: dict[Pair, Target | LookupError_] = {}
    for pair in pairs:
        if pair not in found:
            found[pair] = await lookup(*pair)
    return found


def _param_targets(
    default: Target | None, found: Mapping[Pair, Target | LookupError_], params: list[Param]
) -> dict[str, Target]:
    """The target of each param with an options_sql. Raises ParamError on a failed lookup."""
    out: dict[str, Target] = {}
    for p in params:
        if p.options_sql:
            t = default if default is not None else found[_pair(p.connection, p.database)]
            if isinstance(t, LookupError_):
                raise ParamError(f"{p.name}: {t.message}")
            out[p.name] = t
    return out


async def _resolve_with(
    targets: Mapping[str, Target], params: list[Param], values: dict[str, str], failed: list[Param] | None = None
) -> list[dict[str, Any]]:
    """resolve on `targets`; a param whose options_sql fails is appended to `failed`."""

    async def options(p: Param, sql: str) -> list[Any]:
        t = targets[p.name]
        r = await t.driver.run_query(t.config, sql, t.database, limit=DASHBOARD_ROW_CAP, offset=0, order_by=None)
        if isinstance(r, Err):
            if failed is not None:
                failed.append(p)
            raise ParamError(r.message)
        return [row[0] if row else None for row in r.rows.data]

    return await resolve(params, values, options, {n: dialect_of(t.driver) for n, t in targets.items()})


def _params_pairs(params: list[Param]) -> list[Pair]:
    return [_pair(p.connection, p.database) for p in params if p.options_sql]


async def resolve_on(
    default: Target | None, lookup: Lookup | None, params: list[Param], values: dict[str, str]
) -> list[dict[str, Any]]:
    """Selectors resolved: each options_sql run on `default`, or with `default`
    None on its param's connection from `lookup`; each value kept only while
    its options offer it. Raises ParamError, `f"{param}: {message}"` for a
    failed lookup."""
    found = {} if default is not None else await _look_up(lookup, _params_pairs(params))
    return await _resolve_with(_param_targets(default, found, params), params, values)


def _connections(
    found: Mapping[Pair, Target | LookupError_], queries: Mapping[str, Entry]
) -> dict[Pair, dict[str, Any]]:
    """A federated reply's `connections`, by pair, with each lookup's status."""
    out: dict[Pair, dict[str, Any]] = {}
    for pair, t in found.items():
        names = [n for n, e in queries.items() if _entry_pair(e) == pair]
        if isinstance(t, Target):
            out[pair] = {"name": pair[0], "database": t.database, "status": "ok", "queries": names}
        else:
            out[pair] = {
                "name": pair[0],
                "database": pair[1],
                "status": t.status,
                "queries": names,
                "message": t.message,
            }
    return out


async def run_dashboard_on(
    default: Target | None,
    lookup: Lookup | None,
    queries: Mapping[str, Entry],
    params: object,
    values: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
) -> dict[str, Any]:
    """Resolve the selectors, then run the queries that are ready (one waiting
    on a choice is left out), `limit` rows of each at most. run_queries_on's
    reply plus "params":
    [{name, kind, options, value}] — also on a failing query, so the page keeps
    its selectors. A bad declaration or value fails with `reason`: params.

    Unfederated, `default` runs everything and `lookup` is unused. Federated
    (`default` None), every connection is looked up first; a query's failed
    lookup fails it (`reason`: query, the first in order), a param's is a
    params error, and the reply carries `connections`:
    [{name, database, status, queries, message?}] in first-use order, a
    connection whose query or options_sql failed `failed` with its message."""
    declared = parse_params(params)
    if default is not None:
        found: dict[Pair, Target | LookupError_] = {}
        connections = None
    else:
        found = await _look_up(lookup, [_entry_pair(e) for e in queries.values()] + _params_pairs(declared))
        connections = _connections(found, queries)

    def reply(r: dict[str, Any]) -> dict[str, Any]:
        return r if connections is None else {**r, "connections": list(connections.values())}

    failed_params: list[Param] = []
    try:
        resolved = await _resolve_with(_param_targets(default, found, declared), declared, values, failed_params)
    except ParamError as e:
        if connections is not None and failed_params:
            p = failed_params[0]
            connections[_pair(p.connection, p.database)].update(status="failed", message=str(e))
        return reply(_params_error(str(e)))
    targets: dict[str, Target] = {}
    for name, entry in queries.items():
        t = default if default is not None else found[_entry_pair(entry)]
        if isinstance(t, LookupError_):
            return reply({"ok": False, "reason": "query", "message": f"{name}: {t.message}", "params": resolved})
        targets[name] = t
    try:
        sqls = {n: entry_sql(e) for n, e in queries.items()}
        runnable = apply_to_queries(sqls, declared, resolved, {n: dialect_of(t.driver) for n, t in targets.items()})
    except ParamError as e:
        return reply(_params_error(str(e)))
    r, failed = await _run_queries(targets, runnable, limit, 0)
    if connections is not None and failed is not None:
        connections[_entry_pair(queries[failed])].update(status="failed", message=r["message"])
    return reply({**r, "params": resolved})


def session_lookup(sid: str) -> Lookup:
    """The app's Lookup: `connect.connection_target` on session `sid`."""

    async def lookup(name: str, database: str | None) -> Target | LookupError_:
        found = await connection_target(sid, name, database)
        if len(found) == 2:
            return LookupError_(*found)
        conn_type, config, db = found
        return Target(DRIVERS[conn_type], config, db)

    return lookup


def _federated(queries: Mapping[str, Entry], params: object) -> bool | dict[str, Any]:
    """Whether the dashboard is federated, or a mixed one's failed reply."""
    try:
        return is_federated(queries, params)
    except ValueError:
        return {"ok": False, "reason": "query", "message": MIXED}


async def run_dashboard_queries(
    sid: str,
    queries: Mapping[str, Entry],
    limit: int = DASHBOARD_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    """run_queries_on session `sid`'s connection and selected database. Not
    connected or no database selected fails first (`reason`: no-session /
    no-database). A federated dashboard runs as run_dashboard's, from row 0."""
    federated = _federated(queries, None)
    if isinstance(federated, dict):
        return federated
    if federated:
        r = await run_dashboard_on(None, session_lookup(sid), queries, [], {}, limit)
        r.pop("params", None)
        return r
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    target = Target(DRIVERS[s.type], s.config, s.database)
    return await run_queries_on(
        dict.fromkeys(queries, target), {n: entry_sql(e) for n, e in queries.items()}, limit, offset
    )


async def _no_options(p: Param, sql: str) -> list[Any]:
    return []


async def run_dashboard(
    sid: str,
    queries: Mapping[str, Entry],
    params: object,
    values: dict[str, str],
    limit: int = DASHBOARD_ROW_CAP,
    lookup: Lookup | None = None,
) -> dict[str, Any]:
    """run_dashboard_on session `sid`'s connection and selected database; a
    federated dashboard on the connections it names (`lookup`, else
    session_lookup), with no session gate."""
    federated = _federated(queries, params)
    if isinstance(federated, dict):
        return federated
    if federated:
        return await run_dashboard_on(None, lookup or session_lookup(sid), queries, params, values, limit)
    declared = parse_params(params)
    if not queries and not any(p.options_sql for p in declared):
        # Nothing touches the database: no session, runner or dialect is used,
        # so a page of static selectors still renders disconnected.
        try:
            resolved = await resolve(declared, values, _no_options, {})
        except ParamError as e:
            return _params_error(str(e))
        return {"ok": True, "results": {}, "meta": {}, "params": resolved}
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    return await run_dashboard_on(Target(DRIVERS[s.type], s.config, s.database), None, queries, params, values, limit)


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
