"""Postgres driver (asyncpg). Short-lived connections per request; the picker
lists real databases and the selected one is where queries run."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import asyncpg

from .base import (
    RUN_SQL_TIMEOUT_SECONDS,
    SCRIPT_ROW_CAP,
    SCRIPT_TIMEOUT_SECONDS,
    Column,
    DatabasesResult,
    Err,
    FieldsResult,
    QueryRows,
    RowsResult,
    StatementResult,
    TablesResult,
    TextResult,
    build_order_by,
    error_message,
    parse_host_port_config,
    run_script,
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


async def _raw_connect(c: PgConfig, database: str | None, command_timeout: float = PG_TIMEOUT_SECONDS):
    return await asyncpg.connect(
        host=c.host,
        port=c.port,
        user=c.username or None,
        password=c.password or None,
        database=database,
        timeout=PG_TIMEOUT_SECONDS,
        command_timeout=command_timeout,
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
async def _connect(c: PgConfig, database: str | None, command_timeout: float = PG_TIMEOUT_SECONDS):
    """Short-lived connection to a specific database, closed on exit."""
    conn = await _raw_connect(c, database, command_timeout)
    try:
        yield conn
    finally:
        await conn.close()


# json/jsonb and their arrays (`_json`, `_jsonb`), which asyncpg hands over as text.
_JSON_TYPES = {"json", "jsonb", "_json", "_jsonb"}


def _decode_json(v: Any) -> Any:
    """Structured like a ClickHouse JSON column; Decimal keeps every digit."""
    if isinstance(v, list):
        return [_decode_json(x) for x in v]
    return json.loads(v, parse_float=Decimal) if isinstance(v, str) else v


def _to_rows(attrs: Any, records: list[Any], decode_json: bool = True) -> QueryRows:
    """asyncpg's statement attributes and records as the shared result shape.
    CSV passes `decode_json=False` to keep json as text."""
    meta = [Column(a.name, a.type.name) for a in attrs]
    is_json = [decode_json and c.type in _JSON_TYPES for c in meta]
    return QueryRows(
        meta,
        [[to_json_value(_decode_json(v) if j else v) for v, j in zip(r, is_json, strict=True)] for r in records],
    )


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
            return {"ok": False, "message": error_message(e)}

    async def list_databases(self, config: PgConfig) -> DatabasesResult | Err:
        try:
            async with _connect_bootstrap(config) as conn:
                rows = await conn.fetch(
                    "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname"
                )
                return DatabasesResult([r["datname"] for r in rows])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def list_tables(self, config: PgConfig, database: str | None) -> TablesResult | Err:
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
                return TablesResult([{"name": r["name"], "rows": r["rows"], "bytes": r["bytes"]} for r in rows])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def _fetch_page(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
        decode_json: bool = True,
    ) -> QueryRows:
        order_clause = build_order_by(order_by, '"')
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias="_qv")
        async with _connect(config, database) as conn:
            stmt = await conn.prepare(paginated)
            return _to_rows(stmt.get_attributes(), await stmt.fetch(), decode_json)

    async def run_query(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> RowsResult | Err:
        try:
            return RowsResult(await self._fetch_page(config, sql, database, limit, offset, order_by))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def run_sql(self, config: PgConfig, sql: str, database: str | None, max_rows: int) -> RowsResult | Err:
        try:
            async with (
                _connect(config, database, RUN_SQL_TIMEOUT_SECONDS) as conn,
                conn.transaction(readonly=True),  # unwrapped SQL could otherwise write
            ):
                await conn.execute(f"SET LOCAL statement_timeout = {RUN_SQL_TIMEOUT_SECONDS * 1000}")
                stmt = await conn.prepare(sql)
                records = await (await stmt.cursor()).fetch(max_rows)
                return RowsResult(_to_rows(stmt.get_attributes(), records))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def export_csv(
        self,
        config: PgConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult | Err:
        try:
            rows = await self._fetch_page(config, sql, database, limit, offset, order_by, decode_json=False)
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))
        return TextResult(to_csv([c.name for c in rows.meta], rows.data))

    async def describe_query(self, config: PgConfig, sql: str, database: str | None) -> FieldsResult | Err:
        inner = sql.rstrip().rstrip(";")
        try:
            async with _connect(config, database) as conn:
                stmt = await conn.prepare(inner)
                return FieldsResult([{"name": a.name, "type": a.type.name} for a in stmt.get_attributes()])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def execute_script(self, config: PgConfig, sql: str, database: str | None) -> list[StatementResult]:
        try:
            async with _connect(config, database, SCRIPT_TIMEOUT_SECONDS) as conn:

                async def run_one(stmt: str) -> StatementResult:
                    try:
                        prepared = await conn.prepare(stmt)
                        attrs = prepared.get_attributes()
                        if not attrs:
                            # No result columns: the command tag (`INSERT 0 3`) says what happened.
                            await prepared.fetch()
                            return StatementResult(stmt, True, status=prepared.get_statusmsg() or "OK")
                        # Rows come through a cursor, so only the cap crosses
                        # the wire. A cursor needs a transaction: the script's
                        # own (BEGIN) if it opened one, else one around this
                        # statement.
                        if conn.is_in_transaction():
                            records = await (await prepared.cursor()).fetch(SCRIPT_ROW_CAP + 1)
                        else:
                            async with conn.transaction():
                                records = await (await prepared.cursor()).fetch(SCRIPT_ROW_CAP + 1)
                    except Exception as e:  # noqa: BLE001
                        return StatementResult(stmt, False, message=error_message(e))
                    return StatementResult(stmt, True, rows=_to_rows(attrs, records))

                return await run_script(sql, run_one)
        except Exception as e:  # noqa: BLE001
            # The connection itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=error_message(e))]
