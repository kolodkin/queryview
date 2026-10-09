"""DuckDB-specific behavior against a real temp-file database: the :memory:
default, the empty (no-picker) database list, paginated typed queries, CSV export,
describe, and error reporting. Registry conformance, config round-trip, and
validation are covered by test_driver_contract."""

from __future__ import annotations

import asyncio

import duckdb
import pytest

from queryview.drivers.duckdb import DuckConfig, DuckDBDriver


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def duck_path(tmp_path):
    path = tmp_path / "qv.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE items (id INTEGER, name TEXT)")
    con.execute("INSERT INTO items VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
    con.close()
    return str(path)


def test_parse_config_defaults_blank_path_to_memory():
    d = DuckDBDriver()
    assert d.parse_config({"path": ""})[0] == DuckConfig(":memory:")
    assert d.parse_config({"path": "/tmp/x.duckdb"})[0] == DuckConfig("/tmp/x.duckdb")


def test_list_databases_is_empty(duck_path):
    d = DuckDBDriver()
    assert _run(d.list_databases(DuckConfig(duck_path))) == (True, [])


def test_list_tables_names_seeded_table_with_estimates(duck_path):
    d = DuckDBDriver()
    # rows is duckdb_tables()'s estimated_size; bytes is storage blocks × block
    # size (a small positive multiple of the 256KiB block for a tiny table).
    ok, tables = _run(d.list_tables(DuckConfig(duck_path), None))
    assert ok and isinstance(tables, list) and len(tables) == 1
    t = tables[0]
    assert t["name"] == "items" and t["rows"] == 3
    assert isinstance(t["bytes"], int) and t["bytes"] > 0


def test_run_query_paginates_and_returns_typed_rows(duck_path):
    d = DuckDBDriver()
    r = _run(
        d.run_query(
            DuckConfig(duck_path),
            "SELECT id, name FROM items ORDER BY id",
            None,
            2,
            0,
            [{"name": "name", "dir": "ASC"}],
        )
    )
    assert r.ok and r.rows is not None
    assert [c.name for c in r.rows.meta] == ["id", "name"]
    assert all(isinstance(c.type, str) and c.type for c in r.rows.meta)
    assert r.rows.data == [[1, "alpha"], [2, "beta"]]


def test_export_csv_returns_csv_with_names(duck_path):
    d = DuckDBDriver()
    r = _run(d.export_csv(DuckConfig(duck_path), "SELECT id, name FROM items ORDER BY id", None, 2, 0, None))
    assert r.ok and r.value == "id,name\n1,alpha\n2,beta"


def test_describe_query_returns_columns(duck_path):
    d = DuckDBDriver()
    ok, fields = _run(d.describe_query(DuckConfig(duck_path), "SELECT id, name FROM items", None))
    assert ok and isinstance(fields, list)
    names = [f["name"] for f in fields]
    assert names == ["id", "name"]


def test_run_query_error_is_reported(duck_path):
    d = DuckDBDriver()
    r = _run(d.run_query(DuckConfig(duck_path), "SELECT * FROM no_such", None, 10, 0, None))
    assert r.ok is False and r.rows is None and "no_such" in r.message


def test_execute_script_runs_statements_in_order_on_one_connection(duck_path):
    d = DuckDBDriver()
    results = _run(
        d.execute_script(
            DuckConfig(duck_path),
            "CREATE TABLE extra (id INTEGER); INSERT INTO extra VALUES (7); SELECT id FROM extra",
            None,
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
    # The write landed in the file.
    assert duckdb.connect(duck_path, read_only=True).execute("SELECT count(*) FROM extra").fetchone() == (1,)


def test_execute_script_stops_at_the_first_failing_statement(duck_path):
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT 1; SELECT * FROM no_such; SELECT 2", None))
    assert len(results) == 2
    assert results[0].ok
    assert results[1].ok is False and "no_such" in results[1].message and results[1].sql == "SELECT * FROM no_such"


def test_execute_script_caps_rows_and_flags_truncation(duck_path):
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT * FROM range(1500)", None))
    assert results[0].ok and results[0].rows is not None
    assert len(results[0].rows.data) == 1000 and results[0].truncated is True
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT * FROM range(3)", None))
    assert results[0].truncated is False
