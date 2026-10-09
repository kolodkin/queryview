"""ClickHouse-specific behavior: run_query builds the historical paginated SQL
(backtick-quoted, no subquery alias) and asks ClickHouse for JSONCompact. Registry conformance,
config round-trip, and validation are covered by test_driver_contract."""

from __future__ import annotations

import asyncio

from queryview.drivers.base import SCRIPT_TIMEOUT_SECONDS, Column
from queryview.drivers.clickhouse import ChConfig, ClickHouseDriver

JSON_COMPACT = (
    '{"meta":[{"name":"id","type":"UInt64"},{"name":"tags","type":"Array(String)"}],"data":[["1",["a","b"]]],"rows":1}'
)


def _capture(monkeypatch, seen, text):
    async def fake_ch_query(c, query, database=None, fmt=None, settings=None):
        from queryview.drivers.clickhouse import ChResult

        seen.update(query=query, fmt=fmt, database=database, settings=settings)
        return ChResult(True, text)

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)


def test_run_query_builds_clickhouse_sql_and_parses_json_compact(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, JSON_COMPACT)
    r = asyncio.run(d.run_query(ChConfig("h", 1, "u", ""), "SELECT 1;", "db", 100, 0, [{"name": "a", "dir": "DESC"}]))
    assert r.ok and r.rows is not None
    assert r.rows.meta == [Column("id", "UInt64"), Column("tags", "Array(String)")]
    assert r.rows.data == [["1", ["a", "b"]]]
    assert seen["query"] == "SELECT * FROM (\nSELECT 1\n) ORDER BY `a` DESC LIMIT 100 OFFSET 0"
    assert seen["fmt"] == "JSONCompact"
    assert seen["database"] == "db"
    # Values a JS number would mangle are quoted by ClickHouse itself; named
    # tuples arrive as objects so the UI can label their fields.
    assert seen["settings"] == {
        "output_format_json_quote_64bit_integers": "1",
        "output_format_json_quote_decimals": "1",
        "output_format_json_quote_denormals": "1",
        "output_format_json_named_tuples_as_objects": "1",
    }


def test_run_query_reports_driver_error(monkeypatch):
    d = ClickHouseDriver()

    async def fake_ch_query(c, query, database=None, fmt=None, settings=None):
        from queryview.drivers.clickhouse import ChResult

        return ChResult(False, "ClickHouse responded 400: boom")

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)
    r = asyncio.run(d.run_query(ChConfig("h", 1, "u", ""), "SELECT 1", None, 10, 0, None))
    assert r.ok is False and r.rows is None and "boom" in r.message


def test_run_query_rejects_unparseable_body(monkeypatch):
    d = ClickHouseDriver()
    _capture(monkeypatch, {}, "not json")
    r = asyncio.run(d.run_query(ChConfig("h", 1, "u", ""), "SELECT 1", None, 10, 0, None))
    assert r.ok is False and "JSON" in r.message


def test_export_csv_requests_csv_with_names(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, "id,name\n1,a")
    r = asyncio.run(d.export_csv(ChConfig("h", 1, "u", ""), "SELECT 1", "db", 5, 0, None))
    assert r.ok and r.value == "id,name\n1,a"
    assert seen["fmt"] == "CSVWithNames"
    assert seen["query"] == "SELECT * FROM (\nSELECT 1\n) LIMIT 5 OFFSET 0"


def test_list_tables_parses_rows_and_bytes_with_nulls(monkeypatch):
    d = ClickHouseDriver()
    seen = {}

    async def fake_ch_query(c, query, database=None, fmt=None):
        from queryview.drivers.clickhouse import ChResult

        seen["query"] = query
        seen["database"] = database
        # A MergeTree table with stats and a view (\N for both counters).
        return ChResult(True, "items\t3\t245\nv_items\t\\N\t\\N")

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)
    ok, tables = asyncio.run(d.list_tables(ChConfig("h", 1, "u", ""), "db"))
    assert ok and tables == [
        {"name": "items", "rows": 3, "bytes": 245},
        {"name": "v_items", "rows": None, "bytes": None},
    ]
    assert "system.tables" in seen["query"]
    assert seen["database"] == "db"


def test_execute_script_posts_each_statement_as_written(monkeypatch):
    """The Queries page: no pagination wrapper, a write (HTTP POST — a GET is
    read-only in ClickHouse), JSONCompact via default_format so a statement
    with no result set simply comes back empty, one client for the script."""
    d = ClickHouseDriver()
    calls = []

    async def fake_ch_query(c, query, database=None, fmt=None, settings=None, write=False, client=None):
        from queryview.drivers.clickhouse import ChResult

        calls.append(
            {"query": query, "database": database, "fmt": fmt, "settings": settings, "write": write, "client": client}
        )
        return ChResult(True, "" if query.startswith("INSERT") else JSON_COMPACT)

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)
    results = asyncio.run(
        d.execute_script(ChConfig("h", 1, "u", ""), "INSERT INTO t VALUES (1); SELECT id, tags FROM t;", "db")
    )
    assert [c["query"] for c in calls] == ["INSERT INTO t VALUES (1)", "SELECT id, tags FROM t"]
    assert all(c["write"] and c["fmt"] is None and c["database"] == "db" for c in calls)
    assert calls[0]["client"] is not None and calls[0]["client"] is calls[1]["client"]
    # Statements share one server session (SET, temporary tables), and a
    # statement may run far longer than a read-only probe.
    sid = calls[0]["settings"]["session_id"]
    assert sid and calls[1]["settings"]["session_id"] == sid
    assert calls[0]["client"].timeout.read == SCRIPT_TIMEOUT_SECONDS
    assert calls[0]["settings"]["default_format"] == "JSONCompact"
    assert calls[0]["settings"]["output_format_json_quote_64bit_integers"] == "1"
    assert [r.ok for r in results] == [True, True]
    assert results[0].rows is None and results[0].status == "OK"
    assert results[1].rows is not None and results[1].rows.meta[0] == Column("id", "UInt64")
    assert results[1].rows.data == [["1", ["a", "b"]]]


def test_execute_script_stops_at_the_first_error(monkeypatch):
    d = ClickHouseDriver()
    calls = []

    async def fake_ch_query(c, query, database=None, fmt=None, settings=None, write=False, client=None):
        from queryview.drivers.clickhouse import ChResult

        calls.append(query)
        return ChResult(False, "ClickHouse responded 404: no table") if "missing" in query else ChResult(True, "")

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)
    results = asyncio.run(
        d.execute_script(ChConfig("h", 1, "u", ""), "SELECT 1; SELECT * FROM missing; SELECT 2", None)
    )
    assert calls == ["SELECT 1", "SELECT * FROM missing"]
    assert [r.ok for r in results] == [True, False]
    assert "no table" in results[1].message


def test_execute_script_shows_non_json_output_as_status(monkeypatch):
    """A statement with its own FORMAT clause bypasses default_format; its text
    is shown rather than failing on the JSON parse."""
    d = ClickHouseDriver()

    async def fake_ch_query(c, query, database=None, fmt=None, settings=None, write=False, client=None):
        from queryview.drivers.clickhouse import ChResult

        return ChResult(True, "1,a\n2,b")

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_query", fake_ch_query)
    results = asyncio.run(d.execute_script(ChConfig("h", 1, "u", ""), "SELECT 1 FORMAT CSV", None))
    assert results[0].ok and results[0].rows is None and results[0].status == "1,a\n2,b"
