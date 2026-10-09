"""Postgres-specific behavior: run_query builds double-quoted, `_qv`-aliased
paginated SQL (asyncpg is monkeypatched — no server). Registry conformance,
config round-trip, and validation are covered by test_driver_contract; live
connect/query/describe by e2e."""

from __future__ import annotations

import asyncio

from queryview.drivers.base import Column
from queryview.drivers.postgres import PgConfig, PostgresDriver


def test_run_query_builds_aliased_double_quoted_sql(monkeypatch):
    d = PostgresDriver()
    captured = {}

    class _Stmt:
        def get_attributes(self):
            class _A:
                name = "name"

                class type:  # noqa: N801
                    name = "text"

            return (_A(),)

        async def fetch(self):
            return [["alpha"]]

    class _Conn:
        async def prepare(self, sql):
            captured["sql"] = sql
            return _Stmt()

        async def close(self):
            pass

    async def fake_connect(c, database):
        captured["database"] = database
        return _Conn()

    monkeypatch.setattr("queryview.drivers.postgres._raw_connect", fake_connect)
    r = asyncio.run(
        d.run_query(
            PgConfig("h", 5432, "u", ""), "SELECT name FROM t;", "mydb", 50, 10, [{"name": "name", "dir": "ASC"}]
        )
    )
    assert r.ok and r.rows is not None
    assert r.rows.meta == [Column("name", "text")]
    assert r.rows.data == [["alpha"]]
    assert captured["database"] == "mydb"
    assert captured["sql"] == ('SELECT * FROM (\nSELECT name FROM t\n) AS _qv ORDER BY "name" ASC LIMIT 50 OFFSET 10')

    csv = asyncio.run(d.export_csv(PgConfig("h", 5432, "u", ""), "SELECT name FROM t", "mydb", 50, 10, None))
    assert csv.ok and csv.value == "name\nalpha"


def test_list_tables_queries_public_schema_with_estimates(monkeypatch):
    d = PostgresDriver()
    captured = {}

    class _Conn:
        async def fetch(self, sql):
            captured["sql"] = sql
            return [
                {"name": "items", "rows": 3, "bytes": 16384},
                {"name": "fresh", "rows": None, "bytes": 8192},  # never analyzed
            ]

        async def close(self):
            pass

    async def fake_connect(c, database):
        captured["database"] = database
        return _Conn()

    monkeypatch.setattr("queryview.drivers.postgres._raw_connect", fake_connect)
    ok, tables = asyncio.run(d.list_tables(PgConfig("h", 5432, "u", ""), "mydb"))
    assert ok and tables == [
        {"name": "items", "rows": 3, "bytes": 16384},
        {"name": "fresh", "rows": None, "bytes": 8192},
    ]
    assert captured["database"] == "mydb"
    assert "nspname = 'public'" in captured["sql"]
    assert "reltuples" in captured["sql"] and "pg_total_relation_size" in captured["sql"]


def _fake_pg(monkeypatch, captured):
    """One fake connection whose prepared statements return rows for SELECTs, a
    command tag otherwise, and raise for a `missing` table."""

    class _Stmt:
        def __init__(self, sql):
            self.sql = sql

        def get_attributes(self):
            if not self.sql.startswith("SELECT"):
                return ()

            class _A:
                name = "id"

                class type:  # noqa: N801
                    name = "int4"

            return (_A(),)

        async def fetch(self):
            if "missing" in self.sql:
                raise RuntimeError('relation "missing" does not exist')
            return [[1], [2]] if self.sql.startswith("SELECT") else []

        def get_statusmsg(self):
            return "INSERT 0 2"

    class _Conn:
        async def prepare(self, sql):
            captured.setdefault("statements", []).append(sql)
            return _Stmt(sql)

        async def close(self):
            captured["closed"] = captured.get("closed", 0) + 1

    async def fake_connect(c, database):
        captured["connects"] = captured.get("connects", 0) + 1
        captured["database"] = database
        return _Conn()

    monkeypatch.setattr("queryview.drivers.postgres._raw_connect", fake_connect)


def test_execute_script_runs_statements_on_one_connection(monkeypatch):
    d = PostgresDriver()
    captured = {}
    _fake_pg(monkeypatch, captured)
    results = asyncio.run(
        d.execute_script(PgConfig("h", 5432, "u", ""), "INSERT INTO t VALUES (1), (2); SELECT id FROM t", "mydb")
    )
    assert captured["connects"] == 1 and captured["closed"] == 1 and captured["database"] == "mydb"
    assert captured["statements"] == ["INSERT INTO t VALUES (1), (2)", "SELECT id FROM t"]
    assert [r.ok for r in results] == [True, True]
    # A statement with no result columns reports Postgres's command tag.
    assert results[0].rows is None and results[0].status == "INSERT 0 2"
    assert results[1].rows is not None
    assert results[1].rows.meta == [Column("id", "int4")] and results[1].rows.data == [[1], [2]]


def test_execute_script_stops_at_the_first_error(monkeypatch):
    d = PostgresDriver()
    captured = {}
    _fake_pg(monkeypatch, captured)
    results = asyncio.run(
        d.execute_script(PgConfig("h", 5432, "u", ""), "SELECT 1; SELECT * FROM missing; SELECT 2", "mydb")
    )
    assert captured["statements"] == ["SELECT 1", "SELECT * FROM missing"]
    assert [r.ok for r in results] == [True, False]
    assert "missing" in results[1].message and results[1].sql == "SELECT * FROM missing"
    assert captured["closed"] == 1


def test_execute_script_reports_a_failed_connect_against_the_script(monkeypatch):
    d = PostgresDriver()

    async def fake_connect(c, database):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("queryview.drivers.postgres._raw_connect", fake_connect)
    results = asyncio.run(d.execute_script(PgConfig("h", 5432, "u", ""), "SELECT 1; SELECT 2", "mydb"))
    assert len(results) == 1 and results[0].ok is False and "refused" in results[0].message
