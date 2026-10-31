"""SQLite driver (aiosqlite). Short-lived connections per request, like
Postgres; the config is a file path and there is no database picker."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any

import aiosqlite

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
    run_script,
    to_csv,
    to_json_value,
    wrap_paginated,
)


@dataclass(frozen=True)
class SqliteConfig:
    path: str


def parse_sqlite_config(body: Any) -> tuple[SqliteConfig | None, str | None]:
    b = body if isinstance(body, dict) else {}
    raw = b.get("path")
    path = raw.strip() if isinstance(raw, str) else ""
    if not path:
        return None, "path required"
    return SqliteConfig(path=path), None


SQLITE_TIMEOUT_SECONDS = 5  # as Postgres's per-request timeout


class _NoAttach(sqlite3.Connection):
    """Refuses ATTACH and VACUUM INTO, which write files even under mode=ro."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)


@asynccontextmanager
async def _connect(c: SqliteConfig, timeout: float = SQLITE_TIMEOUT_SECONDS, read_only: bool = True):
    """Short-lived autocommit connection (a script's own BEGIN/COMMIT work),
    closed on exit. It never creates the file: reads open it read-only, the
    script run read-write. Work still running `timeout` seconds after the open
    is aborted: the progress handler is SQLite's only statement timeout."""
    path = c.path.replace("%", "%25").replace("?", "%3f").replace("#", "%23")
    uri = f"file:{path}?mode={'ro' if read_only else 'rw'}"
    factory = _NoAttach if read_only else sqlite3.Connection
    conn = await aiosqlite.connect(uri, uri=True, isolation_level=None, factory=factory)
    try:
        deadline = time.monotonic() + timeout
        await conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
        yield conn
    finally:
        await conn.close()


# SQLite reports no column types for a query, only storage classes per value:
# name each column by its first non-null value's class.
# shortcut: an empty or all-NULL column gets no type; read declared types
# (PRAGMA table_info) if a caller comes to need them.
_CLASS_OF = {int: "INTEGER", float: "REAL", str: "TEXT", bytes: "BLOB"}


def _to_rows(cur: aiosqlite.Cursor, fetched: Iterable[Any]) -> QueryRows:
    records = list(fetched)
    names = [d[0] for d in cur.description or ()]
    meta = []
    for i, name in enumerate(names):
        first = next((r[i] for r in records if r[i] is not None), None)
        meta.append(Column(name, _CLASS_OF.get(type(first), "")))
    return QueryRows(meta, [[to_json_value(v) for v in r] for r in records])


class SqliteDriver:
    type: str = "sqlite"
    requires_database: bool = False
    ident_quote: str = '"'

    def parse_config(self, body: Any) -> tuple[SqliteConfig | None, str | None]:
        return parse_sqlite_config(body)

    def config_to_dict(self, config: SqliteConfig) -> dict[str, Any]:
        return asdict(config)

    def config_from_dict(self, data: dict[str, Any]) -> SqliteConfig:
        return SqliteConfig(**data)

    async def test(self, config: SqliteConfig) -> dict[str, Any]:
        try:
            # Reading the catalog, unlike SELECT 1, fails on a file that isn't SQLite.
            async with _connect(config) as conn, conn.execute("SELECT count(*) FROM sqlite_master") as cur:
                row = await cur.fetchone()
                return {"ok": True, "message": f"Connected — {row[0] if row else 0} schema objects"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": error_message(e)}

    async def list_databases(self, config: SqliteConfig) -> DatabasesResult | Err:
        # No picker: queries run directly against the file.
        return DatabasesResult([])

    async def list_tables(self, config: SqliteConfig, database: str | None) -> TablesResult | Err:
        # Tables and views from the catalog; SQLite keeps no row or size estimates.
        try:
            async with (
                _connect(config) as conn,
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                    "AND substr(name, 1, 7) <> 'sqlite_' ORDER BY name"
                ) as cur,
            ):
                return TablesResult([{"name": r[0], "rows": None, "bytes": None} for r in await cur.fetchall()])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def _fetch_page(
        self,
        config: SqliteConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryRows:
        order_clause = build_order_by(order_by, '"')
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias="_qv")
        async with _connect(config) as conn, conn.execute(paginated) as cur:
            return _to_rows(cur, await cur.fetchall())

    async def run_query(
        self,
        config: SqliteConfig,
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

    async def run_sql(self, config: SqliteConfig, sql: str, database: str | None, max_rows: int) -> RowsResult | Err:
        # The read-only, no-ATTACH open is what keeps unwrapped SQL from writing.
        try:
            async with _connect(config, RUN_SQL_TIMEOUT_SECONDS) as conn, conn.execute(sql) as cur:
                return RowsResult(_to_rows(cur, await cur.fetchmany(max_rows)))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def export_csv(
        self,
        config: SqliteConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult | Err:
        try:
            rows = await self._fetch_page(config, sql, database, limit, offset, order_by)
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))
        return TextResult(to_csv([c.name for c in rows.meta], rows.data))

    async def describe_query(self, config: SqliteConfig, sql: str, database: str | None) -> FieldsResult | Err:
        # One row is enough to name each column's storage class.
        try:
            rows = await self._fetch_page(config, sql, database, 1, 0, None)
            return FieldsResult([{"name": c.name, "type": c.type} for c in rows.meta])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def execute_script(self, config: SqliteConfig, sql: str, database: str | None) -> list[StatementResult]:
        try:
            async with _connect(config, SCRIPT_TIMEOUT_SECONDS, read_only=False) as conn:

                async def run_one(stmt: str) -> StatementResult:
                    try:
                        async with conn.execute(stmt) as cur:
                            if cur.description is None:
                                return StatementResult(stmt, True, status="OK")
                            return StatementResult(
                                stmt, True, rows=_to_rows(cur, await cur.fetchmany(SCRIPT_ROW_CAP + 1))
                            )
                    except Exception as e:  # noqa: BLE001
                        return StatementResult(stmt, False, message=error_message(e))

                return await run_script(sql, run_one)
        except Exception as e:  # noqa: BLE001
            # The open itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=error_message(e))]
