"""ClickHouse-specific behavior: run_query builds the historical paginated SQL
(backtick-quoted, no subquery alias) and asks ClickHouse for JSONCompact. Registry conformance,
config round-trip, and validation are covered by test_driver_contract."""

from __future__ import annotations

import asyncio
import json

import pytest

from queryview.drivers.base import Column
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


def _json_compact(names, rows):
    meta = ",".join(f'{{"name":"{n}","type":"String"}}' for n in names)
    return json.dumps({"meta": json.loads(f"[{meta}]"), "data": rows, "rows": len(rows)})


def test_list_databases_reads_json_compact_rows(monkeypatch):
    d = ClickHouseDriver()
    seen = {}
    _capture(monkeypatch, seen, _json_compact(["name"], [["db1"], ["db2"]]))
    ok, dbs = asyncio.run(d.list_databases(ChConfig("h", 1, "u", "")))
    assert ok and dbs == ["db1", "db2"]
    assert seen["query"] == "SHOW DATABASES" and seen["fmt"] == "JSONCompact"


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
    ok, tables = asyncio.run(d.list_tables(ChConfig("h", 1, "u", ""), "db"))
    assert ok and tables == [
        {"name": "items", "rows": 3, "bytes": 245},
        {"name": "v_items", "rows": None, "bytes": None},
    ]
    assert "system.tables" in seen["query"]
    assert seen["database"] == "db"
    assert seen["fmt"] == "JSONCompact"


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
    ok, cols = asyncio.run(d.describe_query(ChConfig("h", 1, "u", ""), "SELECT 1", "db"))
    assert ok and cols == [
        {"name": "tags", "type": "Array(Tuple(\n    id Int32,\n    name String))"},
        {"name": "note", "type": "String"},
    ]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        _json_compact(["name"], [["only_one_column"]]),  # fewer columns than DESCRIBE selects
        _json_compact(["name", "type"], [["x"]]),  # a row shorter than meta
        _json_compact(["name", "type"], ["xy"]),  # a row that isn't a list
    ],
)
def test_describe_query_rejects_unexpected_bodies(monkeypatch, body):
    d = ClickHouseDriver()
    _capture(monkeypatch, {}, body)
    ok, err = asyncio.run(d.describe_query(ChConfig("h", 1, "u", ""), "SELECT 1", "db"))
    assert ok is False and "JSON" in err
