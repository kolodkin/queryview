"""ClickHouse driver: the HTTP-interface client and a Driver implementation."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, NamedTuple

import httpx

from .base import (
    SCRIPT_ROW_CAP,
    Column,
    QueryResult,
    QueryRows,
    StatementResult,
    TextResult,
    build_order_by,
    cap_rows,
    parse_host_port_config,
    split_statements,
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
    post: bool = False,
) -> ChResult:
    """Run a query against the ClickHouse HTTP interface (Basic auth, 5s timeout).
    `database` scopes the query; `fmt` appends a ClickHouse `FORMAT` clause;
    `settings` are passed as URL parameters. A GET is read-only in ClickHouse,
    so `post` sends the query as the request body for statements that write."""
    url = f"http://{c.host}:{c.port}/"
    q = f"{query}\nFORMAT {fmt}" if fmt else query
    params = {**(settings or {})}
    if database:
        params["database"] = database
    try:
        async with httpx.AsyncClient(timeout=CH_TIMEOUT_SECONDS) as client:
            if post:
                res = await client.post(url, params=params, content=q.encode(), auth=(c.username, c.password))
            else:
                res = await client.get(url, params={"query": q, **params}, auth=(c.username, c.password))
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


def _tsv_rows(text: str, min_cols: int):
    """Rows of a TabSeparated result: blank lines and rows with fewer than
    `min_cols` columns are skipped."""
    for line in text.split("\n"):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) >= min_cols:
            yield cols


# Script statements: JSONCompact unless the statement names its own FORMAT, and
# the result stops filling past the row cap instead of failing (break may
# overshoot by a block; cap_rows trims it).
SCRIPT_SETTINGS = {
    **JSON_COMPACT_SETTINGS,
    "default_format": "JSONCompact",
    "max_result_rows": str(SCRIPT_ROW_CAP + 1),
    "result_overflow_mode": "break",
}


def _parse_json_compact(text: str) -> QueryRows:
    doc = json.loads(text)
    meta = [Column(str(m["name"]), str(m["type"])) for m in doc["meta"]]
    return QueryRows(meta, [list(row) for row in doc["data"]])


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
        r = await ch_query(config, "SHOW DATABASES")
        if not r.ok:
            return False, r.value
        return True, [s.strip() for s in r.value.split("\n") if s.strip()]

    async def list_tables(self, config: ChConfig, database: str | None) -> tuple[bool, list[dict[str, Any]] | str]:
        # Same set SHOW TABLES yields, plus the engine's stored row/byte counts
        # (NULL — serialized as \N — for views and engines that don't track them).
        r = await ch_query(
            config,
            "SELECT name, total_rows, total_bytes FROM system.tables WHERE database = currentDatabase() ORDER BY name",
            database=database,
            fmt="TabSeparated",
        )
        if not r.ok:
            return False, r.value
        return True, [
            {
                "name": cols[0],
                "rows": None if cols[1] == "\\N" else int(cols[1]),
                "bytes": None if cols[2] == "\\N" else int(cols[2]),
            }
            for cols in _tsv_rows(r.value, 3)
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
        r = await ch_query(config, paginated, database=database, fmt="JSONCompact", settings=JSON_COMPACT_SETTINGS)
        if not r.ok:
            return QueryResult(False, None, r.value)
        try:
            rows = _parse_json_compact(r.value)
        except (ValueError, KeyError, TypeError) as err:
            return QueryResult(False, None, f"unexpected JSON from ClickHouse: {err}")
        return QueryResult(True, rows)

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
        r = await ch_query(config, f"DESCRIBE (\n{inner}\n)", database=database, fmt="TabSeparated")
        if not r.ok:
            return False, r.value
        return True, [{"name": cols[0], "type": cols[1]} for cols in _tsv_rows(r.value, 2)]

    async def execute_script(self, config: ChConfig, sql: str, database: str | None) -> list[StatementResult]:
        results: list[StatementResult] = []
        for stmt in split_statements(sql):
            started = time.monotonic()
            r = await ch_query(config, stmt, database=database, settings=SCRIPT_SETTINGS, post=True)
            elapsed = int((time.monotonic() - started) * 1000)
            if not r.ok:
                results.append(StatementResult(stmt, False, message=r.value, elapsed_ms=elapsed))
                break
            if not r.value:
                # DDL/DML: nothing comes back.
                results.append(StatementResult(stmt, True, status="OK", elapsed_ms=elapsed))
                continue
            try:
                rows = _parse_json_compact(r.value)
            except (ValueError, KeyError, TypeError):
                # The statement chose its own FORMAT: show its text as-is.
                results.append(StatementResult(stmt, True, status=r.value, elapsed_ms=elapsed))
                continue
            data, truncated = cap_rows(rows.data)
            results.append(
                StatementResult(stmt, True, rows=QueryRows(rows.meta, data), truncated=truncated, elapsed_ms=elapsed)
            )
        return results
