"""DuckDB driver: file-based, no network, no picker. The synchronous duckdb
library is driven in a worker thread so the event loop is never blocked."""

from __future__ import annotations

import asyncio
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from .base import (
    DEFAULT_LIST_LIMIT,
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


def _is_folder(path: str) -> bool:
    """Folder mode: `path` is a directory of data files rather than a .duckdb file."""
    return path != ":memory:" and os.path.isdir(path)


def _folder_error(path: str) -> str | None:
    """Why a folder-mode root cannot be used, or None. Shared by Test and
    connect so the two never disagree."""
    if "," in os.path.abspath(path):  # file_search_path reads a comma as a list separator
        return "a DuckDB folder path cannot contain a comma"
    if not os.access(path, os.R_OK | os.X_OK):
        return f"cannot read {path}"
    return None


def _list_folders(root: str, limit: int) -> tuple[list[str], bool]:
    """The root (".") and up to `limit` subfolders as sorted relative POSIX
    paths, and whether more exist. Scanned breadth-first, so a cut keeps the
    shallow folders the picker shows first; hidden names, symlinks and
    unreadable folders are skipped."""
    found: list[str] = []
    queue = deque(["."])
    truncated = False
    while queue and not truncated:
        rel = queue.popleft()
        try:
            with os.scandir(os.path.join(root, rel)) as entries:
                names = sorted(
                    e.name for e in entries if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
                )
        except OSError:
            continue
        for n in names:
            if len(found) == limit:
                truncated = True
                break
            child = n if rel == "." else f"{rel}/{n}"
            found.append(child)
            queue.append(child)
    return [".", *sorted(found)], truncated


def _sql_str(value: str) -> str:
    """`value` as a single-quoted SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _open(path: str, database: str | None, read_only: bool = True):
    # Folder mode has no database file: an in-memory connection whose
    # file_search_path is the root, so `read_csv('sub/x.csv')` resolves the
    # same whichever folder is selected (and as the Explorer shows the path).
    if _is_folder(path):
        con = duckdb.connect(":memory:")
        con.execute(f"SET file_search_path = {_sql_str(path)}")
        return con
    if database is not None:  # only folder mode selects one: the folder is gone
        raise FileNotFoundError(f"folder not found: {path}")
    # read_only avoids lock contention between concurrent describe/query opens;
    # :memory: cannot be read_only, so open it read-write.
    return duckdb.connect(path, read_only=(read_only and path != ":memory:"))


# Data files a folder lists as tables: base extension -> DuckDB reader. A
# non-parquet one may also carry a .gz or .zst suffix (parquet compresses
# internally); DuckDB infers the compression from the suffix.
_READERS = {
    ".parquet": "read_parquet",
    ".csv": "read_csv",
    ".tsv": "read_csv",
    ".json": "read_json",
    ".jsonl": "read_json",
    ".ndjson": "read_json",
}
_COMPRESSIONS = (".gz", ".zst")


def _data_ext(name: str) -> tuple[str, str] | None:
    """A file name's data extension and compression suffix (`.csv`, `.gz`), or
    None when the folder lister should skip the file."""
    lower = name.lower()
    comp = next((c for c in _COMPRESSIONS if lower.endswith(c)), "")
    _stem, ext = os.path.splitext(lower[: len(lower) - len(comp)])
    if ext not in _READERS or (comp and ext == ".parquet"):
        return None
    return ext, comp


# Characters DuckDB reads as a glob pattern; a file so named is left out of the
# listing rather than silently reading a neighbour.
_GLOB_CHARS = set("*?[")


def _read_query(ext: str, comp: str, names: list[str], union: bool) -> str:
    """The browse SELECT for one file or (a glob entry) the listed files of one
    extension, relative to file_search_path. Files are named explicitly, never
    as a pattern: a pattern would follow symlinks and hidden files the listing
    skips. Compression is spelled out since DuckDB only infers a lowercase suffix."""
    reader = _READERS[ext]
    source = _sql_str(names[0]) if len(names) == 1 else "[" + ", ".join(_sql_str(n) for n in names) + "]"
    extra = ", compression = 'gzip'" if comp == ".gz" else ", compression = 'zstd'" if comp == ".zst" else ""
    extra += ", union_by_name = true" if union and len(names) > 1 else ""
    return f"SELECT * FROM {reader}({source}{extra})"


def _list_files(root: str, folder: str, union: bool, limit: int) -> TablesResult:
    """The first `limit` data files directly in `folder` (relative to `root`),
    then one `*.<ext>` glob per extension with two or more of them. Queries
    name files by their path from the root. rows is never estimated; bytes is
    the file size, stat'ed only for the files kept."""
    prefix = "" if folder == "." else folder + "/"
    with os.scandir(os.path.join(root, folder)) as it:
        matched = sorted(
            (
                (e, kind)
                for e in it
                if e.is_file(follow_symlinks=False)
                and not e.name.startswith(".")
                and not _GLOB_CHARS & set(e.name)
                and (kind := _data_ext(e.name))
            ),
            key=lambda m: m[0].name,
        )
    files = [(e.name, prefix + e.name, e.stat().st_size, kind) for e, kind in matched[:limit]]
    # `path` is the file's path from the root, for the Explorer to show; a glob has none.
    tables = [
        {"name": n, "path": p, "rows": None, "bytes": b, "query": _read_query(*kind, [p], union)}
        for n, p, b, kind in files
    ]
    globs: dict[tuple[str, str], list[tuple[str, int]]] = {}  # (ext, comp) -> its (path, size) files
    for _n, p, b, kind in files:
        globs.setdefault(kind, []).append((p, b))
    for kind, members in sorted(globs.items()):
        if len(members) >= 2:
            query = _read_query(*kind, [p for p, _ in members], union)
            name = "*" + "".join(kind)
            tables.append(
                {"name": name, "path": None, "rows": None, "bytes": sum(b for _, b in members), "query": query}
            )
    return TablesResult(tables, truncated=len(matched) > limit)


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
            if _is_folder(config.path) and (problem := _folder_error(config.path)):
                raise ValueError(problem)
            con = _open(config.path, None)
            try:
                return _scalar(con, "SELECT 1")
            finally:
                con.close()

        try:
            val = await asyncio.to_thread(_work)
            return {"ok": True, "message": f"Connected — SELECT 1 returned {val}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": error_message(e)}

    async def list_databases(self, config: DuckConfig, limit: int = DEFAULT_LIST_LIMIT) -> DatabasesResult | Err:
        # Folder mode lists folders as the "databases"; a file has no picker:
        # queries run directly against it (schema-qualify in SQL).
        if not _is_folder(config.path):
            return DatabasesResult([])
        try:
            if problem := _folder_error(config.path):
                return Err(problem)
            root = os.path.abspath(config.path)
            folders, truncated = await asyncio.to_thread(_list_folders, root, limit)
            return DatabasesResult(folders, root=root, truncated=truncated)
        except Exception as e:  # noqa: BLE001
            return Err(error_message(e))

    async def list_tables(
        self, config: DuckConfig, database: str | None, union: bool = False, limit: int = DEFAULT_LIST_LIMIT
    ) -> TablesResult | Err:
        if _is_folder(config.path):
            try:
                return await asyncio.to_thread(_list_files, config.path, database or ".", union, limit)
            except Exception as e:  # noqa: BLE001
                return Err(error_message(e))

        # SHOW TABLES for the name set, joined with duckdb_tables()'s estimated
        # row count (absent for views). Bytes are distinct storage blocks ×
        # block size from pragma_storage_info — metadata only, no data scan;
        # None for views and whenever the pragma has nothing (e.g. :memory:).
        def _work():
            con = _open(config.path, database)
            try:
                names = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                est = dict(con.execute("SELECT table_name, estimated_size FROM duckdb_tables()").fetchall())
                block_size = _scalar(con, "SELECT block_size FROM pragma_database_size()")

                def _bytes(name: str) -> int | None:
                    if name not in est:  # a view — no storage of its own
                        return None
                    try:
                        blocks = _scalar(
                            con,
                            f"SELECT count(DISTINCT block_id) FROM pragma_storage_info({_sql_str(name)}) WHERE block_id >= 0",
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
            con = _open(config.path, database)
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
            con = _open(config.path, database)
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
            con = _open(config.path, database)
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
            con = await asyncio.to_thread(_open, config.path, database, False)
        except Exception as e:  # noqa: BLE001
            # The open itself failed: report it against the whole script.
            return [StatementResult(sql, False, message=error_message(e))]
        try:
            return await run_script(sql, lambda stmt: asyncio.to_thread(run_one_sync, con, stmt))
        finally:
            con.close()
