"""ClickHouse-specific behavior: run_query builds the historical paginated SQL
(backtick-quoted, no subquery alias) and asks ClickHouse for JSONCompact. Registry conformance,
config round-trip, and validation are covered by test_driver_contract."""

from __future__ import annotations

import asyncio
import json

import pytest

from queryview.drivers.base import (
    SCRIPT_TIMEOUT_SECONDS,
    Column,
    DatabasesResult,
    Err,
    FieldsResult,
    QueryRows,
    RowsResult,
    TablesResult,
    TextResult,
)
from queryview.drivers.clickhouse import ChConfig, ChCsv, ChRows, ChText, ClickHouseDriver

JSON_COMPACT = (
    '{"meta":[{"name":"id","type":"UInt64"},{"name":"tags","type":"Array(String)"}],"data":[["1",["a","b"]]],"rows":1}'
)


def _capture(monkeypatch, seen, text):
    async def fake_ch_fetch(c, query, clause=None, database=None, settings=None, write=False, client=None):
        seen.update(query=query, clause=clause, database=database, settings=settings, write=write, client=client)
        return text

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_fetch", fake_ch_fetch)


def _fail(monkeypatch, message):
    async def fake_ch_fetch(c, query, clause=None, database=None, settings=None, write=False, client=None):
        return Err(message)

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_fetch", fake_ch_fetch)


def _json_compact(names, rows):
    meta = [{"name": n, "type": "String"} for n in names]
    return json.dumps({"meta": meta, "data": rows, "rows": len(rows)})


CFG = ChConfig("h", 1, "u", "")


def test_run_query_builds_clickhouse_sql_and_parses_json_compact(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, JSON_COMPACT)
    r = asyncio.run(d.run_query(CFG, "SELECT 1;", "db", 100, 0, [{"name": "a", "dir": "DESC"}]))
    assert isinstance(r, RowsResult)
    assert r.rows.meta == [Column("id", "UInt64"), Column("tags", "Array(String)")]
    assert r.rows.data == [["1", ["a", "b"]]]
    assert seen["query"] == "SELECT * FROM (\nSELECT 1\n) ORDER BY `a` DESC LIMIT 100 OFFSET 0"
    assert seen["clause"] == "JSONCompact"
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
    _fail(monkeypatch, "ClickHouse responded 400: boom")
    r = asyncio.run(d.run_query(CFG, "SELECT 1", None, 10, 0, None))
    assert isinstance(r, Err) and "boom" in r.message


def test_run_query_rejects_unparseable_body(monkeypatch):
    d = ClickHouseDriver()
    _capture(monkeypatch, {}, "not json")
    r = asyncio.run(d.run_query(CFG, "SELECT 1", None, 10, 0, None))
    assert isinstance(r, Err) and "JSON" in r.message


def test_export_csv_requests_csv_with_names(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, "id,name\n1,a")
    r = asyncio.run(d.export_csv(CFG, "SELECT 1", "db", 5, 0, None))
    assert isinstance(r, TextResult) and r.text == "id,name\n1,a"
    assert seen["clause"] == "CSVWithNames"
    assert seen["query"] == "SELECT * FROM (\nSELECT 1\n) LIMIT 5 OFFSET 0"


def test_test_reports_connection_outcome(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, "1")
    assert asyncio.run(d.test(CFG)) == {"ok": True, "message": "Connected — SELECT 1 returned 1"}
    assert seen["clause"] is None  # plain text, the server's default format
    _fail(monkeypatch, "connection timed out")
    assert asyncio.run(d.test(CFG)) == {"ok": False, "message": "connection timed out"}


def test_list_databases_reads_json_compact_rows(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, _json_compact(["name"], [["db1"], ["db2"]]))
    r = asyncio.run(d.list_databases(CFG))
    assert isinstance(r, DatabasesResult) and r.databases == ["db1", "db2"]
    assert seen["query"] == "SHOW DATABASES" and seen["clause"] == "JSONCompact"


def test_list_tables_parses_rows_and_bytes_with_nulls(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    # A MergeTree table with stats (UInt64 counters arrive quoted) and a view
    # (NULL for both counters).
    _capture(
        monkeypatch,
        seen,
        _json_compact(["name", "total_rows", "total_bytes"], [["items", "3", "245"], ["v_items", None, None]]),
    )
    r = asyncio.run(d.list_tables(CFG, "db"))
    assert isinstance(r, TablesResult) and r.tables == [
        {"name": "items", "rows": 3, "bytes": 245},
        {"name": "v_items", "rows": None, "bytes": None},
    ]
    assert "system.tables" in seen["query"]
    assert seen["database"] == "db"
    assert seen["clause"] == "JSONCompact"


def test_describe_query_keeps_multiline_types(monkeypatch):
    # DESCRIBE pretty-prints named tuples across lines; a type must come back
    # as ClickHouse wrote it, which JSON decoding gives for free.
    d = ClickHouseDriver()
    _capture(
        monkeypatch,
        {},
        _json_compact(
            ["name", "type", "default_type"],
            [["tags", "Array(Tuple(\n    id Int32,\n    name String))", ""], ["note", "String", ""]],
        ),
    )
    r = asyncio.run(d.describe_query(CFG, "SELECT 1", "db"))
    assert isinstance(r, FieldsResult) and r.fields == [
        {"name": "tags", "type": "Array(Tuple(\n    id Int32,\n    name String))"},
        {"name": "note", "type": "String"},
    ]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        _json_compact(["name"], [["only_one_column"]]),  # fewer columns than DESCRIBE selects
        _json_compact(["name", "type"], [["x"]]),  # a row shorter than meta
        _json_compact(["name", "type"], [["a", "b"], ["x"]]),  # one row of several mismatched
        _json_compact(["name", "type"], ["xy"]),  # a row that isn't a list
        '{"meta": [], "rows": 0}',  # no data key
    ],
)
def test_describe_query_rejects_unexpected_bodies(monkeypatch, body):
    d = ClickHouseDriver()
    _capture(monkeypatch, {}, body)
    r = asyncio.run(d.describe_query(CFG, "SELECT 1", "db"))
    assert isinstance(r, Err) and "JSON" in r.message


def test_ch_rows_from_text_decodes_and_rejects():
    ok = ChRows.from_text(_json_compact(["a", "b"], [[1, None]]))
    assert isinstance(ok, ChRows) and ok.rows == QueryRows([Column("a", "String"), Column("b", "String")], [[1, None]])
    bad = ChRows.from_text(_json_compact(["a"], [[1, 2]]))
    assert isinstance(bad, Err) and bad.message.startswith("unexpected JSON from ClickHouse")
    assert ChText.from_text("x") == ChText("x")
    assert ChCsv.clause == "CSVWithNames" and ChRows.clause == "JSONCompact" and ChText.clause is None


def test_execute_script_posts_each_statement_as_written(monkeypatch):
    """The Queries page: no pagination wrapper, a write (HTTP POST — a GET is
    read-only in ClickHouse), JSONCompact via default_format so a statement
    with no result set simply comes back empty, one client for the script."""
    d = ClickHouseDriver()
    calls = []

    async def fake_ch_fetch(c, query, clause=None, database=None, settings=None, write=False, client=None):
        calls.append(
            {
                "query": query,
                "database": database,
                "clause": clause,
                "settings": settings,
                "write": write,
                "client": client,
            }
        )
        return "" if query.startswith("INSERT") else JSON_COMPACT

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_fetch", fake_ch_fetch)
    results = asyncio.run(d.execute_script(CFG, "INSERT INTO t VALUES (1); SELECT id, tags FROM t;", "db"))
    assert [c["query"] for c in calls] == ["INSERT INTO t VALUES (1)", "SELECT id, tags FROM t"]
    assert all(c["write"] and c["clause"] is None and c["database"] == "db" for c in calls)
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

    async def fake_ch_fetch(c, query, clause=None, database=None, settings=None, write=False, client=None):
        calls.append(query)
        return Err("ClickHouse responded 404: no table") if "missing" in query else ""

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_fetch", fake_ch_fetch)
    results = asyncio.run(d.execute_script(CFG, "SELECT 1; SELECT * FROM missing; SELECT 2", None))
    assert calls == ["SELECT 1", "SELECT * FROM missing"]
    assert [r.ok for r in results] == [True, False]
    assert "no table" in results[1].message


def test_execute_script_shows_non_json_output_as_status(monkeypatch):
    """A statement with its own FORMAT clause bypasses default_format; its text
    is shown rather than failing on the JSON parse."""
    d = ClickHouseDriver()

    async def fake_ch_fetch(c, query, clause=None, database=None, settings=None, write=False, client=None):
        return "1,a\n2,b"

    monkeypatch.setattr("queryview.drivers.clickhouse.ch_fetch", fake_ch_fetch)
    results = asyncio.run(d.execute_script(CFG, "SELECT 1 FORMAT CSV", None))
    assert results[0].ok and results[0].rows is None and results[0].status == "1,a\n2,b"
