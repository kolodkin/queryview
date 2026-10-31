"""SQLite-specific behavior against a real temp file: required path, read-only
opens, declared types and its guards. Shared file-driver behavior is in
test_file_drivers; registry conformance and config round-trip in test_contract."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from queryview.drivers import sqlite
from queryview.drivers.base import Err, FieldsResult, RowsResult, TablesResult
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
    assert d.parse_config({"path": ":memory:"})[0] is None
    assert d.parse_config({"path": " /tmp/x.sqlite "})[0] == SqliteConfig("/tmp/x.sqlite")


def test_test_reports_a_missing_file(tmp_path, db_path):
    d = SqliteDriver()
    assert _run(d.test(SqliteConfig(db_path)))["ok"] is True
    r = _run(d.test(SqliteConfig(str(tmp_path / "missing.sqlite"))))
    assert r["ok"] is False and "unable to open" in r["message"]
    assert not (tmp_path / "missing.sqlite").exists()  # a read-only open never creates


def test_list_tables_names_tables_and_views_without_estimates(db_path):
    sqlite3.connect(db_path).execute("CREATE VIEW v AS SELECT id FROM items").close()
    r = _run(SqliteDriver().list_tables(SqliteConfig(db_path), None))
    assert r == TablesResult(
        [{"name": "items", "rows": None, "bytes": None}, {"name": "v", "rows": None, "bytes": None}]
    )


def test_run_sql_is_read_only_and_capped(db_path):
    d = SqliteDriver()
    r = _run(d.run_sql(SqliteConfig(db_path), "SELECT id FROM items ORDER BY id", None, 2))
    assert isinstance(r, RowsResult) and r.rows.data == [[1], [2]]
    r = _run(d.run_sql(SqliteConfig(db_path), "DELETE FROM items", None, 10))
    assert isinstance(r, Err) and "readonly" in r.message
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM items").fetchone() == (3,)


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


def test_declared_types_name_columns_even_without_rows(db_path):
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE prices (id INTEGER, amount NUMERIC, at DATETIME)")
    con.execute("INSERT INTO prices VALUES ('not-an-int', NULL, NULL)")  # values needn't match the declaration
    con.commit()
    con.close()
    d = SqliteDriver()
    sql = "SELECT p.id, p.amount, p.at, i.id, i.id + 1 AS next FROM prices p JOIN items i ON 1"
    r = _run(d.describe_query(SqliteConfig(db_path), sql + " WHERE 0", None))
    assert isinstance(r, FieldsResult)
    assert [f["type"] for f in r.fields] == ["INTEGER", "NUMERIC", "DATETIME", "INTEGER", ""]
    r = _run(d.run_query(SqliteConfig(db_path), sql, None, 1, 0, None))
    assert isinstance(r, RowsResult)
    assert [c.type for c in r.rows.meta] == [
        "INTEGER",
        "NUMERIC",
        "DATETIME",
        "INTEGER",
        "INTEGER",
    ]  # expression: value class


def test_a_table_named_like_the_type_view_still_reads(db_path):
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE _qv_types (id INTEGER)")
    con.execute("INSERT INTO _qv_types VALUES (5)")
    con.commit()
    con.close()
    r = _run(SqliteDriver().run_query(SqliteConfig(db_path), "SELECT * FROM _qv_types", None, 10, 0, None))
    assert isinstance(r, RowsResult) and r.rows.data == [[5]] and r.rows.meta[0].type == "INTEGER"


def test_a_path_with_a_doubled_leading_slash_opens(db_path):
    r = _run(SqliteDriver().test(SqliteConfig("/" + db_path)))
    assert r["ok"] is True, r
