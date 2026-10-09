"""The driver contract (Protocol) plus dialect helpers and the shared result
contract: typed, JSON-safe rows for the UI and CSV text for download. No
backend/storage concerns here."""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, NamedTuple, Protocol, TypeAlias, runtime_checkable


class Column(NamedTuple):
    name: str
    type: str  # the dialect's own type name (ClickHouse `UInt64`, Postgres `text`, …)


class QueryRows(NamedTuple):
    """A query result in ClickHouse's JSONCompact shape: column metadata plus
    row-major values that are JSON-safe as-is (see `to_json_value`)."""

    meta: list[Column]
    data: list[list[Any]]


class QueryResult(NamedTuple):
    ok: bool
    rows: QueryRows | None = None  # set when ok
    message: str = ""  # set when not ok


class TextResult(NamedTuple):
    ok: bool
    value: str  # the text when ok; an error message otherwise


# Row results of a script are capped (docs/queries.md). A driver fetches at most
# SCRIPT_ROW_CAP + 1 rows; run_script trims to the cap and flags `truncated`.
SCRIPT_ROW_CAP = 100


class StatementResult(NamedTuple):
    """One statement of a script: its rows when it returned any, else the
    driver's status text (`OK`, Postgres's `INSERT 0 3`); `message` when it
    failed. `truncated` and `elapsed_ms` are filled in by run_script."""

    sql: str
    ok: bool
    rows: QueryRows | None = None
    truncated: bool = False
    status: str = ""
    message: str = ""
    elapsed_ms: int = 0


# A driver's own config object (ChConfig, PgConfig, DuckConfig, …). Opaque to
# everything outside the driver that produced it: the storage and session layers
# only ever round-trip it back through the same driver's methods, so they must
# NOT depend on any concrete type. Named (rather than a bare `Any`) so that
# opacity is intentional and documented at every use site. A union of the
# concrete configs would instead re-couple connect.py to every driver and defeat
# the registry indirection.
DriverConfig: TypeAlias = Any


@runtime_checkable
class Driver(Protocol):
    # Stable identifier, also the registry key, the persisted `connections.type`
    # column, and the API `type` field — one word across the whole stack.
    type: str
    # Whether queries require a database to be selected first (a non-empty
    # picker). False for file-based drivers like DuckDB that have no picker.
    requires_database: bool
    # The dialect's identifier-quote character, for SQL generated server-side
    # (select_all_sql). Same convention as the build_order_by `quote` argument.
    ident_quote: str

    def parse_config(self, body: Any) -> tuple[DriverConfig | None, str | None]: ...
    def config_to_dict(self, config: DriverConfig) -> dict[str, Any]: ...
    def config_from_dict(self, data: dict[str, Any]) -> DriverConfig: ...
    async def test(self, config: DriverConfig) -> dict[str, Any]: ...
    async def list_databases(self, config: DriverConfig) -> tuple[bool, list[str] | str]: ...
    # Each table is {"name": str, "rows": int|None, "bytes": int|None} — rows and
    # bytes are cheap engine estimates (never a COUNT(*) scan), None when the
    # engine doesn't track them (e.g. views, or DuckDB's missing per-table size).
    async def list_tables(
        self,
        config: DriverConfig,
        database: str | None,
    ) -> tuple[bool, list[dict[str, Any]] | str]: ...
    async def run_query(
        self,
        config: DriverConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryResult: ...
    # The same page as run_query, as CSVWithNames text for download.
    async def export_csv(
        self,
        config: DriverConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult: ...
    async def describe_query(
        self,
        config: DriverConfig,
        sql: str,
        database: str | None,
    ) -> tuple[bool, list[dict[str, str]] | str]: ...
    # Run a `;`-separated script as written (no pagination wrapper, writes and
    # DDL included) on one connection — see run_script for the shared policy.
    async def execute_script(
        self,
        config: DriverConfig,
        sql: str,
        database: str | None,
    ) -> list[StatementResult]: ...


def _parse_port(raw: Any) -> int | None:
    """Coerce a raw port value to an int in [1, 65535], or None. Rejects bool
    (a bool is an int subclass) and out-of-range / non-numeric values."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return None
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def parse_host_port_config(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate the host/port/username/password fields shared by network drivers
    (ClickHouse, Postgres). Returns ({host,port,username,password}, None) or
    (None, message)."""
    b = body if isinstance(body, dict) else {}
    raw_host = b.get("host")
    host = raw_host.strip() if isinstance(raw_host, str) else ""
    port = _parse_port(b.get("port"))
    username = b.get("username") if isinstance(b.get("username"), str) else ""
    password = b.get("password") if isinstance(b.get("password"), str) else ""
    if not host:
        return None, "host required"
    if port is None:
        return None, "valid port required"
    return {"host": host, "port": port, "username": username, "password": password}, None


def select_all_sql(table: str, quote: str) -> str:
    """`SELECT * FROM <quoted table>` — the query the explorer browses a table
    with. The name is `quote`-quoted with embedded quotes doubled, so an odd
    table name can't escape the identifier."""
    escaped = table.replace(quote, quote + quote)
    return f"SELECT * FROM {quote}{escaped}{quote}"


def build_order_by(order_by: list[dict[str, Any]] | None, quote: str) -> str:
    """`ORDER BY` clause from `[{"name","dir"}]`. Names are `quote`-quoted (any
    embedded quote doubled) and directions whitelisted to ASC/DESC, so malformed
    input can't inject SQL. Empty/absent input yields no clause."""
    if not order_by:
        return ""
    parts: list[str] = []
    for col in order_by:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not isinstance(name, str) or not name:
            continue
        raw_dir = col.get("dir")
        direction = raw_dir.upper() if isinstance(raw_dir, str) else ""
        if direction not in ("ASC", "DESC"):
            direction = "ASC"
        escaped = name.replace(quote, quote + quote)
        parts.append(f"{quote}{escaped}{quote} {direction}")
    if not parts:
        return ""
    return "ORDER BY " + ", ".join(parts)


def wrap_paginated(
    sql: str,
    order_clause: str,
    limit: int,
    offset: int,
    alias: str | None = None,
) -> str:
    """Wrap a SELECT in a paginating subselect. `alias` (e.g. `_qv`) is required
    by Postgres/DuckDB for a derived table; ClickHouse passes alias=None to keep
    its historical SQL byte-for-byte identical."""
    inner = sql.rstrip().rstrip(";")
    head = f"SELECT * FROM (\n{inner}\n)"
    if alias:
        head += f" AS {alias}"
    clauses = [head]
    if order_clause:
        clauses.append(order_clause)
    clauses.append(f"LIMIT {int(limit)} OFFSET {int(offset)}")
    return " ".join(clauses)


def split_statements(sql: str) -> list[str]:
    """Split a script on the `;` that end statements, skipping those inside
    single/double/backtick quotes, `$$` bodies, and `--` or `/* */` comments.
    Blank statements are dropped. An unterminated quote swallows the rest, so a
    broken statement reaches the database whole and its own parser reports it."""
    out: list[str] = []
    start = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            end = sql.find(ch, i + 1)
            i = n if end < 0 else end + 1
        elif sql.startswith("$$", i):
            end = sql.find("$$", i + 2)
            i = n if end < 0 else end + 2
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif ch == ";":
            out.append(sql[start:i])
            start = i + 1
            i += 1
        else:
            i += 1
    out.append(sql[start:])
    return [s for s in (p.strip() for p in out) if s]


async def run_script(sql: str, run_one: Callable[[str], Awaitable[StatementResult]]) -> list[StatementResult]:
    """The script policy every driver shares: split, run each statement in
    order through `run_one`, time it, cap its rows, and stop at the first
    failure. `run_one` returns the statement's rows (at most SCRIPT_ROW_CAP + 1
    of them), status or error; it never raises."""
    results: list[StatementResult] = []
    for stmt in split_statements(sql):
        started = time.monotonic()
        r = await run_one(stmt)
        if r.rows is not None and len(r.rows.data) > SCRIPT_ROW_CAP:
            r = r._replace(rows=QueryRows(r.rows.meta, r.rows.data[:SCRIPT_ROW_CAP]), truncated=True)
        results.append(r._replace(elapsed_ms=int((time.monotonic() - started) * 1000)))
        if not r.ok:
            break
    return results


# The largest integer a JS number holds exactly; beyond it values travel as strings.
_JS_SAFE_INT = 2**53 - 1


def to_json_value(v: Any) -> Any:
    """A JSON-safe value that survives the browser: ints beyond 2^53, Decimals,
    NaN/Inf, datetimes, UUIDs, and bytes become strings; containers recurse;
    JSON scalars pass through. Mirrors what ClickHouse's JSONCompact emits
    with 64-bit integers and decimals quoted, so every driver looks the same."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v if -_JS_SAFE_INT <= v <= _JS_SAFE_INT else str(v)
    if isinstance(v, float):
        return str(v) if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "replace")
    if isinstance(v, (list, tuple, set, frozenset)):
        return [to_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_json_value(x) for k, x in v.items()}
    return str(v)


def to_csv(columns: list[str], rows: list[Any]) -> str:
    """CSVWithNames text as ClickHouse emits it: header row, LF line ends, None
    as an empty field, no trailing newline."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if v is None else str(v) for v in row])
    return buf.getvalue().rstrip("\n")


def rows_to_columns(rows: QueryRows) -> dict[str, list[Any]]:
    """Column-oriented, insertion-ordered `{name: [values, …]}` — the dashboard
    `window.queries` shape."""
    cols: dict[str, list[Any]] = {c.name: [] for c in rows.meta}
    names = [c.name for c in rows.meta]
    for row in rows.data:
        for i, name in enumerate(names):
            cols[name].append(row[i] if i < len(row) else None)
    return cols
