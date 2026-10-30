"""DuckDB driver: file-based, no network, no picker. The synchronous duckdb
library is driven in a worker thread so the event loop is never blocked."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from .base import (
    RUN_SQL_TIMEOUT_SECONDS,
    SCRIPT_ROW_CAP,
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
class DuckConfig:
    path: str


def parse_duck_config(body: Any) -> tuple[DuckConfig | None, str | None]:
    b = body if isinstance(body, dict) else {}
    raw = b.get("path")
    path = raw.strip() if isinstance(raw, str) else ""
    return DuckConfig(path=path or ":memory:"), None


# How many folder levels below the root list_databases walks.
# shortcut: depth capped, upgrade to lazy per-folder listing if roots get deep
FOLDER_DEPTH = 4


def _is_folder(path: str) -> bool:
    """Folder mode: `path` is a directory of data files rather than a .duckdb file."""
    return path != ":memory:" and os.path.isdir(path)


def _list_folders(root: str) -> list[str]:
    """The root (".") and its subfolders as sorted relative POSIX paths, down to
    FOLDER_DEPTH levels; hidden names and symlinks are skipped."""
    folders: list[str] = []
    for dirpath, dirs, _files in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        folders.append(rel)
        depth = 0 if rel == "." else rel.count("/") + 1
        dirs[:] = (
            []
            if depth >= FOLDER_DEPTH
            else sorted(n for n in dirs if not n.startswith(".") and not os.path.islink(os.path.join(dirpath, n)))
        )
    return [folders[0], *sorted(folders[1:])]


def _open(path: str, read_only: bool = True):
    # read_only avoids lock contention between concurrent describe/query opens;
    # :memory: cannot be read_only, so open it read-write.
    return duckdb.connect(path, read_only=(read_only and path != ":memory:"))


_READ_STATEMENTS = {duckdb.StatementType.SELECT, duckdb.StatementType.EXPLAIN}


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
            if _is_folder(config.path) and not os.access(config.path, os.R_OK):
                raise PermissionError(f"cannot read {config.path}")
            con = _open(":memory:" if _is_folder(config.path) else config.path)
            try:
                return _scalar(con, "SELECT 1")
            finally:
                con.close()

        try:
            val = await asyncio.to_thread(_work)
            return {"ok": True, "message": f"Connected — SELECT 1 returned {val}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": error_message(e)}

    async def list_databases(self, config: DuckConfig) -> DatabasesResult | Err:
        # Folder mode lists folders as the "databases"; a file has no picker:
        # queries run directly against it (schema-qualify in SQL).
        if not _is_folder(config.path):
            return DatabasesResult([])
        try:
            root = os.path.abspath(config.path)
            return DatabasesResult(await asyncio.to_thread(_list_folders, root), root=root)
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def list_tables(self, config: DuckConfig, database: str | None) -> TablesResult | Err:
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
            return TablesResult(await asyncio.to_thread(_work))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

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
    ) -> RowsResult | Err:
        try:
            return RowsResult(await self._fetch_page(config, sql, database, limit, offset, order_by))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def run_sql(self, config: DuckConfig, sql: str, database: str | None, max_rows: int) -> RowsResult | Err:
        def _work() -> QueryRows:
            con = _open(config.path)
            timer = threading.Timer(RUN_SQL_TIMEOUT_SECONDS, con.interrupt)  # DuckDB has no server-side limit
            timer.start()
            try:
                # read_only still lets COPY ... TO, ATTACH or INSTALL write, so
                # only a single query-shaped statement runs (DESCRIBE/SHOW parse as SELECT).
                stmts = con.extract_statements(sql)
                if len(stmts) != 1 or stmts[0].type not in _READ_STATEMENTS:
                    raise ValueError("run_sql runs one read-only query (SELECT, DESCRIBE, SHOW, EXPLAIN...)")
                rel = con.sql(sql)
                return QueryRows([], []) if rel is None else _rel_rows(rel.limit(max_rows))
            finally:
                timer.cancel()
                con.close()

        try:
            return RowsResult(await asyncio.to_thread(_work))
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def export_csv(
        self,
        config: DuckConfig,
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

    async def describe_query(self, config: DuckConfig, sql: str, database: str | None) -> FieldsResult | Err:
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
            return FieldsResult([{"name": r[0], "type": r[1]} for r in rows])
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

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
                return StatementResult(stmt, False, message=error_message(e))

        try:
            con = await asyncio.to_thread(_open, config.path, False)
        except Exception as e:  # noqa: BLE001
            # The open itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=error_message(e))]
        try:
            return await run_script(sql, lambda stmt: asyncio.to_thread(run_one_sync, con, stmt))
        finally:
            con.close()
