"""Behavior shared by the file drivers (SQLite, DuckDB), run against a real temp
file seeded with the same `items` table. Engine quirks stay in each driver's
own module; Postgres and ClickHouse need a server, so their equivalents are
wire-level checks in their modules plus the e2e suite."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any

import duckdb
import pytest

from queryview.drivers.base import DatabasesResult, Driver, Err, FieldsResult, RowsResult, TextResult
from queryview.drivers.duckdb import DuckConfig, DuckDBDriver
from queryview.drivers.sqlite import SqliteConfig, SqliteDriver


def _run(coro):
    return asyncio.run(coro)


@dataclass
class FileDb:
    driver: Driver
    config: Any
    path: str
    connect: Any  # opens the file directly, bypassing the driver

    def count(self, table: str) -> int:
        con = self.connect(self.path)
        try:
            return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        finally:
            con.close()


@pytest.fixture(params=["sqlite", "duckdb"])
def db(request, tmp_path) -> FileDb:
    path = str(tmp_path / f"qv.{request.param}")
    if request.param == "sqlite":
        fdb = FileDb(SqliteDriver(), SqliteConfig(path), path, sqlite3.connect)
    else:
        fdb = FileDb(DuckDBDriver(), DuckConfig(path), path, duckdb.connect)
    con = fdb.connect(path)
    con.execute("CREATE TABLE items (id INTEGER, name TEXT)")
    con.execute("INSERT INTO items VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
    con.commit()
    con.close()
    return fdb


def test_list_databases_is_empty(db):
    assert _run(db.driver.list_databases(db.config)) == DatabasesResult([])


def test_run_query_paginates_and_returns_typed_rows(db):
    r = _run(
        db.driver.run_query(
            db.config, "SELECT id, name FROM items ORDER BY id;", None, 2, 0, [{"name": "name", "dir": "ASC"}]
        )
    )
    assert isinstance(r, RowsResult)
    assert [c.name for c in r.rows.meta] == ["id", "name"]
    assert all(isinstance(c.type, str) and c.type for c in r.rows.meta)
    assert r.rows.data == [[1, "alpha"], [2, "beta"]]


def test_export_csv_returns_csv_with_names(db):
    r = _run(db.driver.export_csv(db.config, "SELECT id, name FROM items ORDER BY id", None, 2, 0, None))
    assert isinstance(r, TextResult) and r.text == "id,name\n1,alpha\n2,beta"


def test_describe_query_returns_columns(db):
    r = _run(db.driver.describe_query(db.config, "SELECT id, name FROM items", None))
    assert isinstance(r, FieldsResult) and [f["name"] for f in r.fields] == ["id", "name"]


def test_query_errors_become_err(db):
    d, cfg = db.driver, db.config
    for r in (
        _run(d.run_query(cfg, "SELECT * FROM no_such", None, 10, 0, None)),
        _run(d.describe_query(cfg, "SELECT * FROM no_such", None)),
        _run(d.export_csv(cfg, "SELECT * FROM no_such", None, 10, 0, None)),
    ):
        assert isinstance(r, Err) and "no_such" in r.message


def test_execute_script_runs_statements_in_order_and_persists(db):
    results = _run(
        db.driver.execute_script(
            db.config, "CREATE TABLE extra (id INTEGER); INSERT INTO extra VALUES (7); SELECT id FROM extra", None
        )
    )
    assert [r.ok for r in results] == [True, True, True]
    assert [r.sql for r in results] == [
        "CREATE TABLE extra (id INTEGER)",
        "INSERT INTO extra VALUES (7)",
        "SELECT id FROM extra",
    ]
    # Statements without a result set report a status; row-returning ones carry rows.
    assert results[0].rows is None and results[0].status == "OK"
    assert results[2].rows is not None and results[2].rows.data == [[7]]
    assert [c.name for c in results[2].rows.meta] == ["id"]
    assert all(r.elapsed_ms >= 0 for r in results)
    assert db.count("extra") == 1  # the write landed in the file


def test_execute_script_stops_at_the_first_failing_statement(db):
    results = _run(db.driver.execute_script(db.config, "SELECT 1; SELECT * FROM no_such; SELECT 2", None))
    assert [r.ok for r in results] == [True, False]
    assert "no_such" in results[1].message and results[1].sql == "SELECT * FROM no_such"


def test_execute_script_caps_rows_and_flags_truncation(db):
    many = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 150) SELECT x FROM n"
    results = _run(db.driver.execute_script(db.config, many, None))
    assert results[0].ok and results[0].rows is not None
    assert len(results[0].rows.data) == 100 and results[0].truncated is True
    results = _run(db.driver.execute_script(db.config, "SELECT id FROM items", None))
    assert results[0].truncated is False
