"""ClickHouse driver: the HTTP-interface client and a Driver implementation."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Self, TypeVar

import httpx

from .base import (
    SCRIPT_ROW_CAP,
    SCRIPT_TIMEOUT_SECONDS,
    Column,
    DatabasesResult,
    Err,
    FieldsResult,
    QueryRows,
    Result,
    RowsResult,
    StatementResult,
    TablesResult,
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


# JSONCompact output settings: values a JS number would mangle are quoted by
# ClickHouse itself, and named tuples arrive as objects so the UI can label
# their fields.
JSON_COMPACT_SETTINGS = {
    "output_format_json_quote_64bit_integers": "1",
    "output_format_json_quote_decimals": "1",
    "output_format_json_quote_denormals": "1",
    "output_format_json_named_tuples_as_objects": "1",
}

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


class ChResult(Result):
    """A result the ClickHouse client can produce: the FORMAT clause to ask the
    server for, and how to decode the body it returns."""

    clause: ClassVar[str | None] = None  # None: the server's default (TabSeparated)
    settings: ClassVar[dict[str, str]] = {}  # output settings the decoder relies on

    @classmethod
    def from_text(cls, text: str) -> Self | Err:
        raise NotImplementedError


class ChText(TextResult, ChResult):
    @classmethod
    def from_text(cls, text: str) -> Self | Err:
        return cls(text)


class ChCsv(ChText):
    clause = "CSVWithNames"


class ChRows(RowsResult, ChResult):
    clause = "JSONCompact"
    settings = JSON_COMPACT_SETTINGS

    @classmethod
    def from_text(cls, text: str) -> Self | Err:
        """Decode a JSONCompact body: values arrive decoded (NULL as None, 64-bit
        integers as strings, a pretty-printed type keeps its newlines). Every row
        must have one cell per `meta` column, so callers can index by position."""
        try:
            doc = json.loads(text)
            meta = [Column(str(m["name"]), str(m["type"])) for m in doc["meta"]]
            data = doc["data"]
            if not isinstance(data, list) or any(not isinstance(row, list) or len(row) != len(meta) for row in data):
                raise ValueError("rows don't match meta")
        except (ValueError, KeyError, TypeError) as err:
            return Err(f"unexpected JSON from ClickHouse: {err}")
        return cls(QueryRows(meta, data))


R = TypeVar("R", bound=ChResult)


async def ch_fetch(
    c: ChConfig,
    query: str,
    clause: str | None = None,
    database: str | None = None,
    settings: dict[str, str] | None = None,
    write: bool = False,
    client: httpx.AsyncClient | None = None,
) -> str | Err:
    """Run a query against the ClickHouse HTTP interface (Basic auth, 5s timeout)
    and return the body as text. `clause` appends a `FORMAT` clause; `database`
    scopes the query; `settings` are passed as URL parameters. Queries go as a
    GET, which ClickHouse treats as read-only — that is what keeps every other
    path from writing; `write` sends the query as a POST body instead. `client`
    reuses a caller's connection across several queries."""
    url = f"http://{c.host}:{c.port}/"
    q = f"{query}\nFORMAT {clause}" if clause else query
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
        return Err("connection timed out")
    except httpx.HTTPError as err:
        return Err(str(err) or "connection failed")
    text = res.text.strip()
    if not res.is_success:
        return Err(f"ClickHouse responded {res.status_code}: {text[:200]}")
    return text


async def ch_query(
    c: ChConfig,
    query: str,
    kind: type[R],
    database: str | None = None,
    settings: dict[str, str] | None = None,
) -> R | Err:
    """Run `query` asking for `kind`'s format and decode the body into it."""
    text = await ch_fetch(c, query, kind.clause, database, {**kind.settings, **(settings or {})})
    if isinstance(text, Err):
        return text
    return kind.from_text(text)


async def ch_rows(c: ChConfig, query: str, min_cols: int, database: str | None = None) -> QueryRows | Err:
    """`ch_query` for a metadata query whose rows the caller indexes by position:
    the result has at least `min_cols` columns, or it is an Err."""
    r = await ch_query(c, query, ChRows, database=database)
    if isinstance(r, Err):
        return r
    if len(r.rows.meta) < min_cols:
        return Err(f"unexpected JSON from ClickHouse: expected at least {min_cols} columns, got {len(r.rows.meta)}")
    return r.rows


def parse_ch_config(body: Any) -> tuple[ChConfig | None, str | None]:
    """Validate a ClickHouse config from a request body. Returns (config, None) or
    (None, message)."""
    fields, err = parse_host_port_config(body)
    if err or fields is None:
        return None, err
    return ChConfig(**fields), None


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
        r = await ch_query(config, "SELECT 1", ChText)
        if isinstance(r, Err):
            return {"ok": False, "message": r.message}
        return {"ok": True, "message": f"Connected — SELECT 1 returned {r.text}"}

    async def list_databases(self, config: ChConfig) -> DatabasesResult | Err:
        r = await ch_rows(config, "SHOW DATABASES", 1)
        if isinstance(r, Err):
            return r
        return DatabasesResult([row[0] for row in r.data])

    async def list_tables(self, config: ChConfig, database: str | None) -> TablesResult | Err:
        # Same set SHOW TABLES yields, plus the engine's stored row/byte counts
        # (NULL for views and engines that don't track them).
        r = await ch_rows(
            config,
            "SELECT name, total_rows, total_bytes FROM system.tables WHERE database = currentDatabase() ORDER BY name",
            3,
            database=database,
        )
        if isinstance(r, Err):
            return r
        return TablesResult(
            [
                {
                    "name": row[0],
                    "rows": None if row[1] is None else int(row[1]),
                    "bytes": None if row[2] is None else int(row[2]),
                }
                for row in r.data
            ]
        )

    async def run_query(
        self,
        config: ChConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> RowsResult | Err:
        order_clause = build_order_by(order_by, "`")
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias=None)
        return await ch_query(config, paginated, ChRows, database=database)

    async def export_csv(
        self,
        config: ChConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult | Err:
        order_clause = build_order_by(order_by, "`")
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias=None)
        return await ch_query(config, paginated, ChCsv, database=database)

    async def describe_query(self, config: ChConfig, sql: str, database: str | None) -> FieldsResult | Err:
        inner = sql.rstrip().rstrip(";")
        r = await ch_rows(config, f"DESCRIBE (\n{inner}\n)", 2, database=database)
        if isinstance(r, Err):
            return r
        return FieldsResult([{"name": row[0], "type": row[1]} for row in r.data])

    async def execute_script(self, config: ChConfig, sql: str, database: str | None) -> list[StatementResult]:
        # One HTTP client for the script, and one server session so SET and
        # temporary tables carry from statement to statement; a statement may
        # run far longer than a read-only probe before it is given up on.
        settings = {**SCRIPT_SETTINGS, "session_id": uuid.uuid4().hex, "session_timeout": str(SCRIPT_TIMEOUT_SECONDS)}
        timeout = httpx.Timeout(CH_TIMEOUT_SECONDS, read=SCRIPT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:

            async def run_one(stmt: str) -> StatementResult:
                text = await ch_fetch(config, stmt, database=database, settings=settings, write=True, client=client)
                if isinstance(text, Err):
                    return StatementResult(stmt, False, message=text.message)
                if not text:  # DDL/DML: nothing comes back
                    return StatementResult(stmt, True, status="OK")
                rows = ChRows.from_text(text)
                if isinstance(rows, Err):
                    # The statement chose its own FORMAT: show its text as-is.
                    return StatementResult(stmt, True, status=text)
                return StatementResult(stmt, True, rows=rows.rows)

            return await run_script(sql, run_one)
