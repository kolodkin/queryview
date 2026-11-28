"""Driver dialect helpers and the shared result contract (JSON-safe rows, CSV)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal

import pytest

from queryview.drivers.base import (
    Column,
    QueryRows,
    build_order_by,
    mask_sql,
    parse_host_port_config,
    rows_to_columns,
    select_all_sql,
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
    # Unknown direction falls back to ASC.
    assert build_order_by([{"name": "a", "dir": "x"}], "`") == "ORDER BY `a` ASC"
    assert build_order_by([{"name": "a"}], '"') == 'ORDER BY "a" ASC'
    assert build_order_by(None, "`") == ""
    assert build_order_by([{"bad": 1}], "`") == ""


def test_order_by_refuses_a_name_with_the_quote_character():
    with pytest.raises(ValueError, match="cannot sort by"):
        build_order_by([{"name": 'a"b'}, {"name": "c"}], '"')
    with pytest.raises(ValueError, match="cannot sort by"):
        build_order_by([{"name": "a`, (SELECT 1) -- "}], "`")


def test_order_by_refuses_a_backslash_only_where_the_dialect_escapes():
    with pytest.raises(ValueError, match="cannot sort by"):
        build_order_by([{"name": "a\\"}], "`", backslash_escapes=True)
    assert build_order_by([{"name": "a\\"}], '"') == 'ORDER BY "a\\" ASC'


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


def test_mask_sql_blanks_quotes_and_comments_keeping_offsets():
    sql = "SELECT 'a', \"b\" -- c\nFROM t /* d */ # e"
    assert mask_sql(sql) == "SELECT    ,     " + " " * 4 + "\nFROM t " + " " * 7 + " # e"
    assert mask_sql(sql, mysql=True).endswith("FROM t " + " " * 7 + "    ")
    # MySQL runs `/*! … */`: only its opener and version are blanked.
    assert mask_sql("SELECT /*! INTO */ 1", mysql=True) == "SELECT " + " " * 3 + " INTO */ 1"
    assert mask_sql("SELECT 1 /*!50000INTO x*/", mysql=True) == "SELECT 1 " + " " * 8 + "INTO x*/"


def test_result_classes_are_frozen_named_payloads():
    from queryview.drivers.base import (
        DatabasesResult,
        Err,
        FieldsResult,
        Result,
        RowsResult,
        TablesResult,
        TextResult,
    )

    rows = QueryRows([Column("n", "Int32")], [[1]])
    results = [
        Err("boom"),
        RowsResult(rows),
        TextResult("a,b"),
        DatabasesResult(["db1"]),
        TablesResult([{"name": "items", "rows": 1, "bytes": None}]),
        FieldsResult([{"name": "n", "type": "Int32"}]),
    ]
    assert all(isinstance(r, Result) for r in results)
    assert Err("boom").message == "boom"
    assert RowsResult(rows).rows is rows
    assert TextResult("a,b").text == "a,b"
    assert DatabasesResult(["db1"]).databases == ["db1"]
    assert TablesResult([]).tables == []
    assert FieldsResult([]).fields == []
    # isinstance against Err is the one error check every consumer uses.
    assert [isinstance(r, Err) for r in results] == [True, False, False, False, False, False]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Err("x").message = "y"  # type: ignore[misc]


def test_error_message_names_the_exception_type():
    from queryview.drivers.base import error_message

    assert error_message(ValueError("bad")) == "ValueError: bad"
    assert error_message(TimeoutError()) == "TimeoutError"


def test_parse_host_port_config_takes_an_optional_database():
    fields, err = parse_host_port_config({"host": "h", "port": "1", "database": " sales_reporting "})
    assert err is None and fields is not None and fields["database"] == "sales_reporting"
    blank, _ = parse_host_port_config({"host": "h", "port": "1"})
    assert blank is not None and blank["database"] == ""
