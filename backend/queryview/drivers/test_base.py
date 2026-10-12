"""Driver dialect helpers and the shared result contract (JSON-safe rows, CSV)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from queryview.drivers.base import (
    Column,
    QueryRows,
    build_order_by,
    rows_to_columns,
    select_all_sql,
    split_statements,
    to_csv,
    to_json_value,
    wrap_paginated,
)


def test_select_all_sql_quotes_and_doubles_embedded_quotes():
    assert select_all_sql("items", '"') == 'SELECT * FROM "items"'
    assert select_all_sql('we"ird', '"') == 'SELECT * FROM "we""ird"'
    assert select_all_sql("a`b", "`") == "SELECT * FROM `a``b`"


def test_build_order_by_quotes_and_whitelists_direction():
    assert build_order_by([{"name": "a", "dir": "desc"}], "`") == "ORDER BY `a` DESC"
    # Unknown direction falls back to ASC; quote chars in the name are doubled.
    assert build_order_by([{"name": "a`b", "dir": "x"}], "`") == "ORDER BY `a``b` ASC"
    assert build_order_by([{"name": "a"}], '"') == 'ORDER BY "a" ASC'
    assert build_order_by(None, "`") == ""
    assert build_order_by([{"bad": 1}], "`") == ""


def test_wrap_paginated_matches_clickhouse_shape_without_alias():
    out = wrap_paginated("SELECT 1;", "", 100, 0, alias=None)
    assert out == "SELECT * FROM (\nSELECT 1\n) LIMIT 100 OFFSET 0"


def test_wrap_paginated_adds_alias_and_order():
    out = wrap_paginated("SELECT 1", 'ORDER BY "a" ASC', 10, 5, alias="_qv")
    assert out == 'SELECT * FROM (\nSELECT 1\n) AS _qv ORDER BY "a" ASC LIMIT 10 OFFSET 5'


def test_to_json_value_keeps_json_scalars():
    assert [to_json_value(v) for v in (None, True, 1, 1.5, "s")] == [None, True, 1, 1.5, "s"]


def test_to_json_value_stringifies_values_json_would_mangle():
    # Beyond 2^53 a JS number rounds; Decimal has no JSON type; NaN/Inf aren't JSON.
    assert to_json_value(2**53) == "9007199254740992"
    assert to_json_value(-(2**53)) == "-9007199254740992"
    assert to_json_value(2**53 - 1) == 2**53 - 1
    assert to_json_value(Decimal("1.10")) == "1.10"
    assert to_json_value(float("nan")) == "nan"
    assert to_json_value(float("-inf")) == "-inf"


def test_to_json_value_formats_temporals_and_ids_as_strings():
    assert to_json_value(dt.datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"
    assert to_json_value(dt.date(2024, 1, 2)) == "2024-01-02"
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert to_json_value(u) == str(u)
    assert to_json_value(b"\x00hi") == "\x00hi"


def test_to_json_value_recurses_containers():
    assert to_json_value((1, [Decimal("2"), None], {"k": (3,)})) == [1, ["2", None], {"k": [3]}]
    assert to_json_value({1: "a"}) == {"1": "a"}


def test_to_csv_quotes_and_uses_lf():
    assert to_csv(["a", "b"], [["x,y", "z"]]) == 'a,b\n"x,y",z'


def test_to_csv_nulls_are_empty_fields_and_empty_is_just_header():
    assert to_csv(["id", "name"], [[1, None]]) == "id,name\n1,"
    assert to_csv(["a"], []) == "a"


def test_rows_to_columns_is_column_oriented_and_ordered():
    rows = QueryRows([Column("a", "Int32"), Column("b", "String")], [[1, "x"], [2, "y"]])
    assert rows_to_columns(rows) == {"a": [1, 2], "b": ["x", "y"]}
    assert rows_to_columns(QueryRows([Column("a", "Int32")], [])) == {"a": []}


def test_split_statements_splits_on_semicolons_and_drops_blanks():
    assert split_statements("SELECT 1; SELECT 2;\n\n;  ") == ["SELECT 1", "SELECT 2"]
    assert split_statements("SELECT 1") == ["SELECT 1"]
    assert split_statements("  ;; \n") == []


def test_split_statements_ignores_semicolons_inside_quotes_and_comments():
    sql = (
        "INSERT INTO t VALUES ('a;b', \"c;d\", `e;f`); -- trailing; comment\n"
        "/* block; comment */ SELECT 'it''s; here';\n"
        "SELECT $$dollar; quoted$$"
    )
    assert split_statements(sql) == [
        "INSERT INTO t VALUES ('a;b', \"c;d\", `e;f`)",
        "-- trailing; comment\n/* block; comment */ SELECT 'it''s; here'",
        "SELECT $$dollar; quoted$$",
    ]


def test_split_statements_keeps_an_unterminated_quote_in_one_statement():
    # A broken statement reaches the database whole, so its own parser reports it.
    assert split_statements("SELECT 'open; SELECT 2") == ["SELECT 'open; SELECT 2"]


def test_split_statements_handles_tagged_dollar_quotes_and_backslash_escapes():
    fn = "CREATE FUNCTION f() RETURNS int AS $body$ BEGIN RETURN 1; END $body$ LANGUAGE plpgsql"
    assert split_statements(f"{fn}; SELECT f()") == [fn, "SELECT f()"]
    # A backslash escapes the next character inside a single-quoted string
    # (ClickHouse strings, Postgres E'' strings).
    assert split_statements("SELECT E'it\\'s; here'; SELECT 'a\\'b;c'; SELECT 2") == [
        "SELECT E'it\\'s; here'",
        "SELECT 'a\\'b;c'",
        "SELECT 2",
    ]
