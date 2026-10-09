"""DuckDB driver: file-based, no network, no picker. The synchronous duckdb
library is driven in a worker thread so the event loop is never blocked."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from .base import (
    SCRIPT_ROW_CAP,
    Column,
    QueryResult,
    QueryRows,
    StatementResult,
    TextResult,
    build_order_by,
    run_script,
    to_csv,
    to_json_value,
    wrap_paginated,
)


@dataclass(frozen=True)
class DuckConfig:
    path: str


def parse_duck_config(body: Any) -> tuple[DuckConfig | None, str | None]:
    b = body if isinstance(body, dict) else {}
    raw = b.get("path")
    path = raw.strip() if isinstance(raw, str) else ""
    return DuckConfig(path=path or ":memory:"), None


def _open(path: str, read_only: bool = True):
    # read_only avoids lock contention between concurrent describe/query opens;
    # :memory: cannot be read_only, so open it read-write.
    return duckdb.connect(path, read_only=(read_only and path != ":memory:"))


def _rel_rows(rel: duckdb.DuckDBPyRelation) -> QueryRows:
    """A relation's rows as the shared result shape; it exposes DuckDB's own
    type names alongside the rows."""
    meta = [Column(name, str(t)) for name, t in zip(rel.columns, rel.types, strict=True)]
    return QueryRows(meta, [[to_json_value(v) for v in row] for row in rel.fetchall()])


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    """First column of the single-row result; raises if the query yields no row."""
    row = con.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"query returned no row: {sql}")
    return row[0]


class DuckDBDriver:
    type: str = "duckdb"
    requires_database: bool = False
    ident_quote: str = '"'

    def parse_config(self, body: Any) -> tuple[DuckConfig | None, str | None]:
        return parse_duck_config(body)

    def config_to_dict(self, config: DuckConfig) -> dict[str, Any]:
        return asdict(config)

    def config_from_dict(self, data: dict[str, Any]) -> DuckConfig:
        return DuckConfig(**data)

    async def test(self, config: DuckConfig) -> dict[str, Any]:
        def _work():
            con = _open(config.path)
            try:
                return _scalar(con, "SELECT 1")
            finally:
                con.close()

        try:
            val = await asyncio.to_thread(_work)
            return {"ok": True, "message": f"Connected — SELECT 1 returned {val}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e) or "connection failed"}

    async def list_databases(self, config: DuckConfig) -> tuple[bool, list[str] | str]:
        # No picker: queries run directly against the file (schema-qualify in SQL).
        return True, []

    async def list_tables(self, config: DuckConfig, database: str | None) -> tuple[bool, list[dict[str, Any]] | str]:
        # SHOW TABLES for the name set, joined with duckdb_tables()'s estimated
        # row count (absent for views). Bytes are distinct storage blocks ×
        # block size from pragma_storage_info — metadata only, no data scan;
        # None for views and whenever the pragma has nothing (e.g. :memory:).
        def _work():
            con = _open(config.path)
            try:
                names = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                est = dict(con.execute("SELECT table_name, estimated_size FROM duckdb_tables()").fetchall())
                block_size = _scalar(con, "SELECT block_size FROM pragma_database_size()")

                def _bytes(name: str) -> int | None:
                    if name not in est:  # a view — no storage of its own
                        return None
                    quoted = name.replace("'", "''")
                    try:
                        blocks = _scalar(
                            con,
                            f"SELECT count(DISTINCT block_id) FROM pragma_storage_info('{quoted}') WHERE block_id >= 0",
                        )
                    except Exception:  # noqa: BLE001
                        return None
                    return blocks * block_size if blocks else None

                return [{"name": n, "rows": est.get(n), "bytes": _bytes(n)} for n in names]
            finally:
                con.close()

        try:
            return True, await asyncio.to_thread(_work)
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def _fetch_page(
        self,
        config: DuckConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryRows:
        order_clause = build_order_by(order_by, '"')
        paginated = wrap_paginated(sql, order_clause, limit, offset, alias="_qv")

        def _work() -> QueryRows:
            con = _open(config.path)
            try:
                return _rel_rows(con.sql(paginated))
            finally:
                con.close()

        return await asyncio.to_thread(_work)

    async def run_query(
        self,
        config: DuckConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> QueryResult:
        try:
            return QueryResult(True, await self._fetch_page(config, sql, database, limit, offset, order_by))
        except Exception as e:  # noqa: BLE001
            return QueryResult(False, None, str(e))

    async def export_csv(
        self,
        config: DuckConfig,
        sql: str,
        database: str | None,
        limit: int,
        offset: int,
        order_by: list[dict[str, Any]] | None,
    ) -> TextResult:
        try:
            rows = await self._fetch_page(config, sql, database, limit, offset, order_by)
        except Exception as e:  # noqa: BLE001
            return TextResult(False, str(e))
        return TextResult(True, to_csv([c.name for c in rows.meta], rows.data))

    async def describe_query(
        self, config: DuckConfig, sql: str, database: str | None
    ) -> tuple[bool, list[dict[str, str]] | str]:
        inner = sql.rstrip().rstrip(";")

        def _work():
            con = _open(config.path)
            try:
                # DuckDB's DESCRIBE returns (column_name, column_type, ...).
                return con.execute(f"DESCRIBE {inner}").fetchall()
            finally:
                con.close()

        try:
            rows = await asyncio.to_thread(_work)
            return True, [{"name": r[0], "type": r[1]} for r in rows]
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def execute_script(self, config: DuckConfig, sql: str, database: str | None) -> list[StatementResult]:
        # Read-write, unlike every other open: this is the one path that writes.
        # Statements share the connection (temp tables, BEGIN/COMMIT), each run
        # in the worker thread so the event loop never blocks.
        def run_one_sync(con: duckdb.DuckDBPyConnection, stmt: str) -> StatementResult:
            try:
                # sql() yields a relation for a row-returning statement and
                # None for DDL/DML, which it has already run. The relation is
                # lazy: it runs on fetch, so that stays inside the try too.
                rel = con.sql(stmt)
                if rel is None:
                    return StatementResult(stmt, True, status="OK")
                return StatementResult(stmt, True, rows=_rel_rows(rel.limit(SCRIPT_ROW_CAP + 1)))
            except Exception as e:  # noqa: BLE001
                return StatementResult(stmt, False, message=str(e))

        try:
            con = await asyncio.to_thread(_open, config.path, False)
        except Exception as e:  # noqa: BLE001
            # The open itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=str(e))]
        try:
            return await run_script(sql, lambda stmt: asyncio.to_thread(run_one_sync, con, stmt))
        finally:
            con.close()
