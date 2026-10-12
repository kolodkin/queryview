"""ClickHouse driver: the HTTP-interface client and a Driver implementation."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any, NamedTuple

import httpx

from .base import (
    SCRIPT_ROW_CAP,
    SCRIPT_TIMEOUT_SECONDS,
    Column,
    QueryResult,
    QueryRows,
    StatementResult,
    TextResult,
    build_order_by,
    parse_host_port_config,
    run_script,
    wrap_paginated,
)

CH_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ChConfig:
    host: str
    port: int
    username: str
    password: str


class ChResult(NamedTuple):
    ok: bool
    value: str


# JSONCompact output settings: values a JS number would mangle are quoted by
# ClickHouse itself, and named tuples arrive as objects so the UI can label
# their fields.
JSON_COMPACT_SETTINGS = {
    "output_format_json_quote_64bit_integers": "1",
    "output_format_json_quote_decimals": "1",
    "output_format_json_quote_denormals": "1",
    "output_format_json_named_tuples_as_objects": "1",
}


async def ch_query(
    c: ChConfig,
    query: str,
    database: str | None = None,
    fmt: str | None = None,
    settings: dict[str, str] | None = None,
    write: bool = False,
    client: httpx.AsyncClient | None = None,
) -> ChResult:
    """Run a query against the ClickHouse HTTP interface (Basic auth, 5s timeout).
    `database` scopes the query; `fmt` appends a ClickHouse `FORMAT` clause;
    `settings` are passed as URL parameters. Queries go as a GET, which
    ClickHouse treats as read-only — that is what keeps every other path from
    writing; `write` sends the query as a POST body instead. `client` reuses a
    caller's connection across several queries."""
    url = f"http://{c.host}:{c.port}/"
    q = f"{query}\nFORMAT {fmt}" if fmt else query
    params = dict(settings or {})
    if database:
        params["database"] = database
    auth = (c.username, c.password)

    async def send(cl: httpx.AsyncClient) -> httpx.Response:
        if write:
            return await cl.post(url, params=params, content=q.encode(), auth=auth)
        return await cl.get(url, params={"query": q, **params}, auth=auth)

    try:
        if client is not None:
            res = await send(client)
        else:
            async with httpx.AsyncClient(timeout=CH_TIMEOUT_SECONDS) as own:
                res = await send(own)
    except httpx.TimeoutException:
        return ChResult(False, "connection timed out")
    except httpx.HTTPError as err:
        return ChResult(False, str(err) or "connection failed")
    text = res.text.strip()
    if not res.is_success:
        return ChResult(False, f"ClickHouse responded {res.status_code}: {text[:200]}")
    return ChResult(True, text)


def parse_ch_config(body: Any) -> tuple[ChConfig | None, str | None]:
    """Validate a ClickHouse config from a request body. Returns (config, None) or
    (None, message)."""
    fields, err = parse_host_port_config(body)
    if err or fields is None:
        return None, err
    return ChConfig(**fields), None


async def ch_json(
    c: ChConfig,
    query: str,
    database: str | None = None,
    settings: dict[str, str] | None = None,
    cols: int = 0,
) -> QueryRows | str:
    """A query's JSONCompact result (values decoded: NULL as None, 64-bit
    integers as strings, a pretty-printed type keeps its newlines), or an error
    message. Every row has one cell per `meta` column and at least `cols` cells,
    so callers can index the columns they selected."""
    r = await ch_query(c, query, database=database, fmt="JSONCompact", settings=settings)
    if not r.ok:
        return r.value
    try:
        return _parse_json_compact(r.value, cols)
    except (ValueError, KeyError, TypeError) as err:
        return f"unexpected JSON from ClickHouse: {err}"


# Script statements: JSONCompact unless the statement names its own FORMAT, and
# the server stops filling the result past the row cap instead of failing. The
# check runs between blocks, so up to a block (max_block_size, ~65k rows) can
# still arrive; run_script trims it. Subqueries are not affected.
SCRIPT_SETTINGS = {
    **JSON_COMPACT_SETTINGS,
    "default_format": "JSONCompact",
    "max_result_rows": str(SCRIPT_ROW_CAP + 1),
    "result_overflow_mode": "break",
}


def _parse_json_compact(text: str, cols: int = 0) -> QueryRows:
    """Decode a JSONCompact body. Every row must have one cell per `meta`
    column and there must be at least `cols` columns; raises ValueError,
    KeyError or TypeError otherwise."""
    doc = json.loads(text)
    meta = [Column(str(m["name"]), str(m["type"])) for m in doc["meta"]]
    data = [list(row) for row in doc["data"] if isinstance(row, list)]
    if len(data) != len(doc["data"]) or len(meta) < cols or any(len(row) != len(meta) for row in data):
        raise ValueError("rows don't match meta")
    return QueryRows(meta, data)


class ClickHouseDriver:
    type: str = "clickhouse"
    requires_database: bool = True
    ident_quote: str = "`"

    def parse_config(self, body: Any) -> tuple[ChConfig | None, str | None]:
        return parse_ch_config(body)

    def config_to_dict(self, config: ChConfig) -> dict[str, Any]:
        return asdict(config)

    def config_from_dict(self, data: dict[str, Any]) -> ChConfig:
        return ChConfig(**data)

    async def test(self, config: ChConfig) -> dict[str, Any]:
        r = await ch_query(config, "SELECT 1")
        if r.ok:
            return {"ok": True, "message": f"Connected — SELECT 1 returned {r.value}"}
        return {"ok": False, "message": r.value}

    async def list_databases(self, config: ChConfig) -> tuple[bool, list[str] | str]:
        res = await ch_json(config, "SHOW DATABASES", cols=1)
        if isinstance(res, str):
            return False, res
        return True, [row[0] for row in res.data]

    async def list_tables(self, config: ChConfig, database: str | None) -> tuple[bool, list[dict[str, Any]] | str]:
        # Same set SHOW TABLES yields, plus the engine's stored row/byte counts
        # (NULL for views and engines that don't track them).
        res = await ch_json(
            config,
            "SELECT name, total_rows, total_bytes FROM system.tables WHERE database = currentDatabase() ORDER BY name",
            database=database,
            cols=3,
        )
        if isinstance(res, str):
            return False, res
        return True, [
            {
                "name": row[0],
                "rows": None if row[1] is None else int(row[1]),
                "bytes": None if row[2] is None else int(row[2]),
            }
            for row in res.data
        ]

    async def run_query(
        self,
        config: ChConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryResult:
        order_clause = build_order_by(order_by, "`")
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias=None)
        res = await ch_json(config, paginated, database=database, settings=JSON_COMPACT_SETTINGS)
        if isinstance(res, str):
            return QueryResult(False, None, res)
        return QueryResult(True, res)

    async def export_csv(
        self,
        config: ChConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult:
        order_clause = build_order_by(order_by, "`")
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias=None)
        r = await ch_query(config, paginated, database=database, fmt="CSVWithNames")
        return TextResult(r.ok, r.value)

    async def describe_query(
        self, config: ChConfig, sql: str, database: str | None
    ) -> tuple[bool, list[dict[str, str]] | str]:
        inner = sql.rstrip().rstrip(";")
        res = await ch_json(config, f"DESCRIBE (\n{inner}\n)", database=database, cols=2)
        if isinstance(res, str):
            return False, res
        return True, [{"name": row[0], "type": row[1]} for row in res.data]

    async def execute_script(self, config: ChConfig, sql: str, database: str | None) -> list[StatementResult]:
        # One HTTP client for the script, and one server session so SET and
        # temporary tables carry from statement to statement; a statement may
        # run far longer than a read-only probe before it is given up on.
        settings = {**SCRIPT_SETTINGS, "session_id": uuid.uuid4().hex, "session_timeout": str(SCRIPT_TIMEOUT_SECONDS)}
        timeout = httpx.Timeout(CH_TIMEOUT_SECONDS, read=SCRIPT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:

            async def run_one(stmt: str) -> StatementResult:
                r = await ch_query(config, stmt, database=database, settings=settings, write=True, client=client)
                if not r.ok:
                    return StatementResult(stmt, False, message=r.value)
                if not r.value:  # DDL/DML: nothing comes back
                    return StatementResult(stmt, True, status="OK")
                try:
                    return StatementResult(stmt, True, rows=_parse_json_compact(r.value))
                except (ValueError, KeyError, TypeError):
                    # The statement chose its own FORMAT: show its text as-is.
                    return StatementResult(stmt, True, status=r.value)

            return await run_script(sql, run_one)
