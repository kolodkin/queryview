"""MySQL driver (aiomysql). Short-lived connections per request; the
picker lists the server's databases and the selected one is where queries run."""

from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any

import aiomysql
from pymysql.constants import COMMAND, FIELD_TYPE
from pymysql.converters import conversions
from pymysql.err import MySQLError

from .base import (
    DEFAULT_LIST_LIMIT,
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
    parse_json_text,
    query_timeout,
    run_script,
    to_csv,
    to_json_value,
    wrap_paginated,
)


@dataclass(frozen=True)
class MySqlConfig:
    host: str
    port: int
    username: str
    password: str
    database: str = ""  # the only database listed and opened; blank lists them all


def parse_mysql_config(body: Any) -> tuple[MySqlConfig | None, str | None]:
    fields, err = parse_host_port_config(body)
    if err or fields is None:
        return None, err
    return MySqlConfig(**fields), None


# The protocol's type codes as SQL type names; the wire doesn't tell e.g. TEXT from BLOB.
_TYPE_NAMES = {
    FIELD_TYPE.DECIMAL: "decimal",
    FIELD_TYPE.NEWDECIMAL: "decimal",
    FIELD_TYPE.TINY: "tinyint",
    FIELD_TYPE.SHORT: "smallint",
    FIELD_TYPE.INT24: "mediumint",
    FIELD_TYPE.LONG: "int",
    FIELD_TYPE.LONGLONG: "bigint",
    FIELD_TYPE.FLOAT: "float",
    FIELD_TYPE.DOUBLE: "double",
    FIELD_TYPE.NULL: "null",
    FIELD_TYPE.TIMESTAMP: "timestamp",
    FIELD_TYPE.DATE: "date",
    FIELD_TYPE.NEWDATE: "date",
    FIELD_TYPE.TIME: "time",
    FIELD_TYPE.DATETIME: "datetime",
    FIELD_TYPE.YEAR: "year",
    FIELD_TYPE.BIT: "bit",
    FIELD_TYPE.JSON: "json",
    FIELD_TYPE.ENUM: "enum",
    FIELD_TYPE.SET: "set",
    FIELD_TYPE.TINY_BLOB: "blob",
    FIELD_TYPE.MEDIUM_BLOB: "blob",
    FIELD_TYPE.LONG_BLOB: "blob",
    FIELD_TYPE.BLOB: "blob",
    FIELD_TYPE.VARCHAR: "varchar",
    FIELD_TYPE.VAR_STRING: "varchar",
    FIELD_TYPE.STRING: "char",
    FIELD_TYPE.GEOMETRY: "geometry",
}


def _columns(description: Any) -> list[Column]:
    return [Column(d[0], _TYPE_NAMES.get(d[1], str(d[1]))) for d in description]


def _to_rows(description: Any, records: Any, decode_json: bool = True) -> QueryRows:
    """Cursor description and rows as the shared result shape. JSON columns are
    decoded like Postgres json, unless CSV asks to keep the text."""
    meta = _columns(description)
    is_json = [decode_json and c.type == "json" for c in meta]
    return QueryRows(
        meta,
        [[to_json_value(parse_json_text(v) if j else v) for v, j in zip(r, is_json, strict=True)] for r in records],
    )


# TIME as the server's text (`25:00:00`), not a timedelta; BIT as its integer value.
_CONV = {**conversions, FIELD_TYPE.TIME: str, FIELD_TYPE.BIT: lambda b: int.from_bytes(b, "big")}
_MULTI_STATEMENTS_OFF = struct.pack("<H", 1)


async def _raw_connect(c: MySqlConfig, database: str | None):
    conn = await aiomysql.connect(
        host=c.host,
        port=c.port,
        user=c.username or None,
        password=c.password,
        db=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=query_timeout.get(),
        conv=_CONV,
    )
    # aiomysql always negotiates multi-statements; one call must run one statement,
    # or `SET SESSION TRANSACTION READ WRITE; DELETE ...` escapes run_sql's read-only session.
    try:
        await conn._execute_command(COMMAND.COM_SET_OPTION, _MULTI_STATEMENTS_OFF)
        await conn._read_packet()
    except BaseException:
        conn.close()
        raise
    return conn


@asynccontextmanager
async def _connect(c: MySqlConfig, database: str | None):
    """Short-lived connection, closed on exit. close() drops the socket rather
    than draining an unread result."""
    conn = await _raw_connect(c, database)
    try:
        yield conn
    finally:
        conn.close()


async def _fetch(
    conn: Any, sql: str, max_rows: int | None, timeout: float, drain: bool = False
) -> tuple[Any, list[Any], int]:
    """Run `sql` and fetch up to `max_rows` rows (all when None) within `timeout`:
    (description or None, rows, affected row count). `drain` reads past the
    unfetched rest so the connection can run another statement."""

    async def go():
        # Unbuffered when capped, so only the rows fetched cross the wire.
        cur = await conn.cursor(aiomysql.Cursor if max_rows is None else aiomysql.SSCursor)
        await cur.execute(sql)
        if cur.description is None:
            return None, [], cur.rowcount
        rows = await (cur.fetchall() if max_rows is None else cur.fetchmany(max_rows))
        if drain:
            # shortcut: reads the unfetched rest of a big result; KILL QUERY from a second
            # connection if scripts' capped SELECTs on large tables get slow.
            await cur.close()
        return cur.description, list(rows), cur.rowcount

    # shortcut: a timeout only abandons the statement client-side (the connection
    # is closed); use max_statement_time / max_execution_time if servers keep running them.
    return await asyncio.wait_for(go(), timeout)


_DUP_FIELDNAME = 1060


async def _fetch_wrapped(
    conn: Any, sql: str, order_by: list[dict[str, Any]] | None, limit: int, offset: int
) -> tuple[Any, list[Any]]:
    """One page of `sql` through the paginating wrapper. A derived table needs
    unique column names, so `SELECT a.id, b.id …` runs as written instead,
    fetching through the page and dropping the rows before it."""
    try:
        description, rows, _ = await _fetch(
            conn,
            wrap_paginated(sql, build_order_by(order_by, "`"), limit, offset, alias="_qv"),
            None,
            query_timeout.get(),
        )
        return description, rows
    except MySQLError as e:
        if e.args[0] != _DUP_FIELDNAME or order_by:  # a column sort needs the wrapper
            raise
    # shortcut: reads every row before the page; alias the columns for deep pages.
    description, rows, _ = await _fetch(conn, sql.rstrip().rstrip(";"), offset + limit, query_timeout.get())
    return description, rows[offset:]


class MySqlDriver:
    type: str = "mysql"
    requires_database: bool = True
    ident_quote: str = "`"
    backslash_escapes: bool = True  # MySQL reads `\` as an escape in string literals by default

    def parse_config(self, body: Any) -> tuple[MySqlConfig | None, str | None]:
        return parse_mysql_config(body)

    def config_to_dict(self, config: MySqlConfig) -> dict[str, Any]:
        return asdict(config)

    def config_from_dict(self, data: dict[str, Any]) -> MySqlConfig:
        # Keys it no longer has (a dropped option) are ignored, not an error.
        return MySqlConfig(**{k: v for k, v in data.items() if k in MySqlConfig.__dataclass_fields__})

    async def test(self, config: MySqlConfig) -> dict[str, Any]:
        try:
            async with _connect(config, config.database or None) as conn:
                _, rows, _ = await _fetch(conn, "SELECT 1", None, query_timeout.get())
                return {"ok": True, "message": f"Connected — SELECT 1 returned {rows[0][0]}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": error_message(e)}

    async def list_databases(
        self, config: MySqlConfig, limit: int = DEFAULT_LIST_LIMIT, current: str | None = None
    ) -> DatabasesResult | Err:
        try:
            if config.database:  # connecting checks it is reachable
                async with _connect(config, config.database):
                    return DatabasesResult([config.database], current=config.database)
            async with _connect(config, None) as conn:
                _, rows, _ = await _fetch(conn, "SHOW DATABASES", None, query_timeout.get())
                return DatabasesResult([r[0] for r in rows])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def list_tables(
        self, config: MySqlConfig, database: str | None, union: bool = False, limit: int = DEFAULT_LIST_LIMIT
    ) -> TablesResult | Err:
        # TABLE_ROWS is the engine's estimate (NULL for views); size is data + indexes.
        try:
            async with _connect(config, database) as conn:
                _, rows, _ = await _fetch(
                    conn,
                    "SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH + INDEX_LENGTH, TABLE_TYPE IN ('VIEW', 'SYSTEM VIEW') "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME",
                    None,
                    query_timeout.get(),
                )
                return TablesResult([{"name": n, "rows": r, "bytes": b, "view": bool(v)} for n, r, b, v in rows])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def _fetch_page(
        self,
        config: MySqlConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
        decode_json: bool = True,
    ) -> QueryRows:
        async with _connect(config, database) as conn:
            description, rows = await _fetch_wrapped(conn, sql, order_by, limit, offset)
            return _to_rows(description, rows, decode_json)

    async def run_query(
        self,
        config: MySqlConfig,
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

    async def run_sql(self, config: MySqlConfig, sql: str, database: str | None, max_rows: int) -> RowsResult | Err:
        try:
            async with _connect(config, database) as conn:
                # Unwrapped SQL could otherwise write. A session (not transaction) setting
                # also refuses DDL and survives a COMMIT.
                await _fetch(conn, "SET SESSION TRANSACTION READ ONLY", None, RUN_SQL_TIMEOUT_SECONDS)
                description, rows, _ = await _fetch(conn, sql, max_rows, RUN_SQL_TIMEOUT_SECONDS)
                return RowsResult(_to_rows(description or (), rows))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def export_csv(
        self,
        config: MySqlConfig,
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

    async def describe_query(self, config: MySqlConfig, sql: str, database: str | None) -> FieldsResult | Err:
        # No describe-only call in the protocol: a LIMIT 0 page returns just the columns.
        try:
            async with _connect(config, database) as conn:
                description, _ = await _fetch_wrapped(conn, sql, None, 0, 0)
                return FieldsResult([{"name": c.name, "type": c.type} for c in _columns(description)])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def execute_script(self, config: MySqlConfig, sql: str, database: str | None) -> list[StatementResult]:
        try:
            async with _connect(config, database) as conn:

                async def run_one(stmt: str) -> StatementResult:
                    try:
                        description, rows, affected = await _fetch(
                            conn, stmt, SCRIPT_ROW_CAP + 1, SCRIPT_TIMEOUT_SECONDS, drain=True
                        )
                        if description is None:
                            return StatementResult(stmt, True, status=f"OK, {max(affected, 0)} rows affected")
                    except Exception as e:  # noqa: BLE001
                        return StatementResult(stmt, False, message=error_message(e))
                    return StatementResult(stmt, True, rows=_to_rows(description, rows))

                return await run_script(sql, run_one)
        except Exception as e:  # noqa: BLE001
            # The connection itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=error_message(e))]
