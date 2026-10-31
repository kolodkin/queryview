"""SQLite-specific behavior against a real temp file: required path, the empty
(no-picker) database list, read-only opens, paginated typed queries, CSV
export, describe, scripts and error reporting. Registry conformance and config
round-trip are covered by test_contract."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from queryview.drivers import sqlite
from queryview.drivers.base import DatabasesResult, Err, FieldsResult, RowsResult, TablesResult, TextResult
from queryview.drivers.sqlite import SqliteConfig, SqliteDriver


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "qv.sqlite"
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE items (id INTEGER, name TEXT)")
    con.execute("INSERT INTO items VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
    con.commit()
    con.close()
    return str(path)


def test_parse_config_requires_a_path():
    d = SqliteDriver()
    assert d.parse_config({"path": " "}) == (None, "path required")
    assert d.parse_config({"path": " /tmp/x.sqlite "})[0] == SqliteConfig("/tmp/x.sqlite")


def test_test_reports_a_missing_file(tmp_path, db_path):
    d = SqliteDriver()
    assert _run(d.test(SqliteConfig(db_path)))["ok"] is True
    r = _run(d.test(SqliteConfig(str(tmp_path / "missing.sqlite"))))
    assert r["ok"] is False and "unable to open" in r["message"]
    assert not (tmp_path / "missing.sqlite").exists()  # a read-only open never creates


def test_list_databases_is_empty(db_path):
    assert _run(SqliteDriver().list_databases(SqliteConfig(db_path))) == DatabasesResult([])


def test_list_tables_names_tables_and_views_without_estimates(db_path):
    sqlite3.connect(db_path).execute("CREATE VIEW v AS SELECT id FROM items").close()
    r = _run(SqliteDriver().list_tables(SqliteConfig(db_path), None))
    assert r == TablesResult(
        [{"name": "items", "rows": None, "bytes": None}, {"name": "v", "rows": None, "bytes": None}]
    )


def test_run_query_paginates_and_returns_typed_rows(db_path):
    r = _run(
        SqliteDriver().run_query(
            SqliteConfig(db_path),
            "SELECT id, name FROM items ORDER BY id;",
            None,
            2,
            0,
            [{"name": "name", "dir": "ASC"}],
        )
    )
    assert isinstance(r, RowsResult)
    assert [(c.name, c.type) for c in r.rows.meta] == [("id", "INTEGER"), ("name", "TEXT")]
    assert r.rows.data == [[1, "alpha"], [2, "beta"]]


def test_export_csv_returns_csv_with_names(db_path):
    r = _run(
        SqliteDriver().export_csv(SqliteConfig(db_path), "SELECT id, name FROM items ORDER BY id", None, 2, 0, None)
    )
    assert isinstance(r, TextResult) and r.text == "id,name\n1,alpha\n2,beta"


def test_describe_query_returns_columns(db_path):
    r = _run(SqliteDriver().describe_query(SqliteConfig(db_path), "SELECT id, name FROM items", None))
    assert r == FieldsResult([{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}])


def test_run_sql_is_read_only_and_capped(db_path):
    d = SqliteDriver()
    r = _run(d.run_sql(SqliteConfig(db_path), "SELECT id FROM items ORDER BY id", None, 2))
    assert isinstance(r, RowsResult) and r.rows.data == [[1], [2]]
    r = _run(d.run_sql(SqliteConfig(db_path), "DELETE FROM items", None, 10))
    assert isinstance(r, Err) and "readonly" in r.message
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM items").fetchone() == (3,)


def test_query_errors_become_err(db_path):
    d = SqliteDriver()
    for r in (
        _run(d.run_query(SqliteConfig(db_path), "SELECT * FROM no_such", None, 10, 0, None)),
        _run(d.describe_query(SqliteConfig(db_path), "SELECT * FROM no_such", None)),
        _run(d.export_csv(SqliteConfig(db_path), "SELECT * FROM no_such", None, 10, 0, None)),
    ):
        assert isinstance(r, Err) and "no_such" in r.message


def test_execute_script_runs_statements_in_order_and_persists(db_path):
    results = _run(
        SqliteDriver().execute_script(
            SqliteConfig(db_path),
            "CREATE TABLE extra (id INTEGER); INSERT INTO extra VALUES (7); SELECT id FROM extra",
            None,
        )
    )
    assert [r.ok for r in results] == [True, True, True]
    assert results[0].rows is None and results[0].status == "OK"
    assert results[2].rows is not None and results[2].rows.data == [[7]]
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM extra").fetchone() == (1,)


def test_execute_script_stops_at_the_first_failure_and_caps_rows(db_path):
    d = SqliteDriver()
    results = _run(d.execute_script(SqliteConfig(db_path), "SELECT 1; SELECT * FROM no_such; SELECT 2", None))
    assert [r.ok for r in results] == [True, False] and "no_such" in results[1].message
    results = _run(
        d.execute_script(
            SqliteConfig(db_path),
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 150) SELECT x FROM n",
            None,
        )
    )
    assert results[0].rows is not None and len(results[0].rows.data) == 100 and results[0].truncated is True


def test_test_rejects_a_file_that_is_not_sqlite(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("not a database")
    r = _run(SqliteDriver().test(SqliteConfig(str(junk))))
    assert r["ok"] is False and "not a database" in r["message"]


def test_path_with_uri_characters_opens_that_file(tmp_path):
    path = tmp_path / "report%41 #1?.sqlite"
    sqlite3.connect(str(path)).execute("CREATE TABLE sqlitemetrics (x)").close()
    r = _run(SqliteDriver().list_tables(SqliteConfig(str(path)), None))
    assert r == TablesResult([{"name": "sqlitemetrics", "rows": None, "bytes": None}])


def test_run_sql_refuses_attach_and_vacuum_into(tmp_path, db_path):
    d = SqliteDriver()
    for sql in (f"ATTACH '{tmp_path}/new.db' AS n", f"VACUUM INTO '{tmp_path}/copy.db'"):
        assert isinstance(_run(d.run_sql(SqliteConfig(db_path), sql, None, 10)), Err)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["qv.sqlite"]


def test_execute_script_does_not_create_a_missing_file(tmp_path):
    results = _run(SqliteDriver().execute_script(SqliteConfig(str(tmp_path / "typo.sqlite")), "SELECT 1", None))
    assert results[0].ok is False and not (tmp_path / "typo.sqlite").exists()


def test_a_query_past_the_timeout_is_aborted(monkeypatch, db_path):
    monkeypatch.setattr(sqlite, "RUN_SQL_TIMEOUT_SECONDS", 0)
    endless = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT count(*) FROM n"
    r = _run(SqliteDriver().run_sql(SqliteConfig(db_path), endless, None, 10))
    assert isinstance(r, Err) and "interrupted" in r.message
