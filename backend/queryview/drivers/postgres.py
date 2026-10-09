"""Postgres driver (asyncpg). Short-lived connections per request; the picker
lists real databases and the selected one is where queries run."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any

import asyncpg

from .base import (
    Column,
    QueryResult,
    QueryRows,
    StatementResult,
    TextResult,
    build_order_by,
    cap_rows,
    parse_host_port_config,
    split_statements,
    to_csv,
    to_json_value,
    wrap_paginated,
)

PG_TIMEOUT_SECONDS = 5
_BOOTSTRAP_DBS = ("postgres", "template1")


@dataclass(frozen=True)
class PgConfig:
    host: str
    port: int
    username: str
    password: str


def parse_pg_config(body: Any) -> tuple[PgConfig | None, str | None]:
    fields, err = parse_host_port_config(body)
    if err or fields is None:
        return None, err
    return PgConfig(**fields), None


async def _raw_connect(c: PgConfig, database: str | None):
    return await asyncpg.connect(
        host=c.host,
        port=c.port,
        user=c.username or None,
        password=c.password or None,
        database=database,
        timeout=PG_TIMEOUT_SECONDS,
        command_timeout=PG_TIMEOUT_SECONDS,
    )


async def _raw_connect_bootstrap(c: PgConfig):
    """Connect to *some* database so we can enumerate the rest."""
    candidates = ([c.username] if c.username else []) + list(_BOOTSTRAP_DBS)
    last: Exception | None = None
    for db in candidates:
        try:
            return await _raw_connect(c, db)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last if last is not None else RuntimeError("could not connect")


@asynccontextmanager
async def _connect(c: PgConfig, database: str | None):
    """Short-lived connection to a specific database, closed on exit."""
    conn = await _raw_connect(c, database)
    try:
        yield conn
    finally:
        await conn.close()


@asynccontextmanager
async def _connect_bootstrap(c: PgConfig):
    """Short-lived connection to a maintenance database, closed on exit."""
    conn = await _raw_connect_bootstrap(c)
    try:
        yield conn
    finally:
        await conn.close()


class PostgresDriver:
    type: str = "postgres"
    requires_database: bool = True
    ident_quote: str = '"'

    def parse_config(self, body: Any) -> tuple[PgConfig | None, str | None]:
        return parse_pg_config(body)

    def config_to_dict(self, config: PgConfig) -> dict[str, Any]:
        return asdict(config)

    def config_from_dict(self, data: dict[str, Any]) -> PgConfig:
        return PgConfig(**data)

    async def test(self, config: PgConfig) -> dict[str, Any]:
        try:
            async with _connect_bootstrap(config) as conn:
                val = await conn.fetchval("SELECT 1")
                return {"ok": True, "message": f"Connected — SELECT 1 returned {val}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e) or "connection failed"}

    async def list_databases(self, config: PgConfig) -> tuple[bool, list[str] | str]:
        try:
            async with _connect_bootstrap(config) as conn:
                rows = await conn.fetch(
                    "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname"
                )
                return True, [r["datname"] for r in rows]
        except Exception as e:  # noqa: BLE001
            return False, str(e) or "connection failed"

    async def list_tables(self, config: PgConfig, database: str | None) -> tuple[bool, list[dict[str, Any]] | str]:
        # Tables and views of the public schema — what an unqualified name in
        # the explorer's generated SELECT resolves to under the default
        # search_path. Other schemas need explicit SQL on the query page.
        # Row counts are the planner's reltuples estimate (-1 = never analyzed
        # -> NULL, e.g. a freshly created table); size is on-disk relation size.
        try:
            async with _connect(config, database) as conn:
                rows = await conn.fetch(
                    "SELECT c.relname AS name, "
                    "CASE WHEN c.reltuples < 0 THEN NULL "
                    "ELSE c.reltuples::bigint END AS rows, "
                    "pg_total_relation_size(c.oid) AS bytes "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm') "
                    "ORDER BY c.relname"
                )
                return True, [{"name": r["name"], "rows": r["rows"], "bytes": r["bytes"]} for r in rows]
        except Exception as e:  # noqa: BLE001
            return False, str(e) or "connection failed"

    async def _fetch_page(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryRows:
        order_clause = build_order_by(order_by, '"')
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias="_qv")
        async with _connect(config, database) as conn:
            stmt = await conn.prepare(paginated)
            meta = [Column(a.name, a.type.name) for a in stmt.get_attributes()]
            records = await stmt.fetch()
            return QueryRows(meta, [[to_json_value(v) for v in r] for r in records])

    async def run_query(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryResult:
        try:
            return QueryResult(True, await self._fetch_page(config, sql, database, limit, offset, order_by))
        except Exception as e:  # noqa: BLE001
            return QueryResult(False, None, str(e) or "connection failed")

    async def export_csv(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult:
        try:
            rows = await self._fetch_page(config, sql, database, limit, offset, order_by)
        except Exception as e:  # noqa: BLE001
            return TextResult(False, str(e) or "connection failed")
        return TextResult(True, to_csv([c.name for c in rows.meta], rows.data))

    async def describe_query(
        self, config: PgConfig, sql: str, database: str | None
    ) -> tuple[bool, list[dict[str, str]] | str]:
        inner = sql.rstrip().rstrip(";")
        try:
            async with _connect(config, database) as conn:
                stmt = await conn.prepare(inner)
                return True, [{"name": a.name, "type": a.type.name} for a in stmt.get_attributes()]
        except Exception as e:  # noqa: BLE001
            return False, str(e) or "connection failed"

    async def execute_script(self, config: PgConfig, sql: str, database: str | None) -> list[StatementResult]:
        results: list[StatementResult] = []
        try:
            async with _connect(config, database) as conn:
                for stmt in split_statements(sql):
                    started = time.monotonic()
                    try:
                        prepared = await conn.prepare(stmt)
                        records = await prepared.fetch()
                        attrs = prepared.get_attributes()
                    except Exception as e:  # noqa: BLE001
                        results.append(StatementResult(stmt, False, message=str(e), elapsed_ms=_ms(started)))
                        break
                    if not attrs:
                        # No result columns: Postgres's command tag (`INSERT 0 3`) says what happened.
                        status = prepared.get_statusmsg() or "OK"
                        results.append(StatementResult(stmt, True, status=status, elapsed_ms=_ms(started)))
                        continue
                    meta = [Column(a.name, a.type.name) for a in attrs]
                    data, truncated = cap_rows([[to_json_value(v) for v in r] for r in records])
                    results.append(
                        StatementResult(
                            stmt, True, rows=QueryRows(meta, data), truncated=truncated, elapsed_ms=_ms(started)
                        )
                    )
        except Exception as e:  # noqa: BLE001
            # The connection itself failed: report it against the whole script.
            results.append(StatementResult(sql, False, message=str(e) or "connection failed"))
        return results


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
