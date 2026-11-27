"""Dashboard param rules (docs/user_guide/dashboard.md#dashboard-parameters): parsing,
substitution per dialect, dependency order and option resolution."""

from __future__ import annotations

import asyncio

import pytest

from queryview.dashboard_params import (
    MAX_EACH,
    MAX_TEXT_PARAM,
    Dialect,
    Param,
    ParamError,
    apply_to_queries,
    missing,
    needed,
    option_text,
    parse_params,
    placeholders_in,
    resolve,
    resolve_order,
    substitute,
)

CH = Dialect(quote="`", backslash_escapes=True)
PG = Dialect(quote='"', backslash_escapes=False)


def _sub(sql, params, values):
    return substitute(sql, params, values, CH)


async def _no_run(sql: str):
    return []


def _resolve(params, values, run=_no_run, dialect=CH):
    async def runner(p, sql):
        return await run(sql)

    return asyncio.run(resolve(params, values, runner, {p.name: dialect for p in params}))


# --- parse_params ----------------------------------------------------------


def test_parses_a_static_options_param():
    assert parse_params([{"name": "region", "options": ["eu", "us"]}]) == [
        Param(name="region", kind="value", options=("eu", "us"))
    ]


def test_parses_an_options_sql_param():
    assert parse_params([{"name": "table", "kind": "identifier", "options_sql": "SELECT name FROM system.tables"}]) == [
        Param(name="table", kind="identifier", options_sql="SELECT name FROM system.tables")
    ]


def test_parses_a_dimension_param_which_needs_no_options():
    assert parse_params([{"name": "category", "kind": "dimension"}]) == [Param(name="category", kind="dimension")]


@pytest.mark.parametrize(
    "raw",
    [
        [{"name": "x", "options": ["a"], "options_sql": "SELECT 1"}],  # ambiguous
        [{"name": "x", "kind": "sql", "options": ["a"]}],  # unknown kind
        [{"options": ["a"]}],  # nameless
        {"name": "x"},  # not a list
        [{"name": "x", "kind": "text", "options": ["a"]}],  # free input has no list
        ["x", None, ["a"]],  # not mappings
    ],
)
def test_drops_what_it_cannot_read(raw):
    assert parse_params(raw) == []


def test_reads_a_connection_and_database_beside_options_sql_only():
    raw = [
        {"name": "t", "options_sql": "SELECT 1", "connection": "warehouse", "database": "sales_reporting"},
        {"name": "r", "options": ["eu"], "connection": "warehouse", "database": "sales_reporting"},
    ]
    assert parse_params(raw) == [
        Param("t", "value", options_sql="SELECT 1", connection="warehouse", database="sales_reporting"),
        Param("r", "value", options=("eu",)),
    ]


def test_each_options_sql_runs_with_its_own_param_and_dialect():
    seen = []

    async def run(p, sql):
        seen.append((p.name, sql))
        return ["x"]

    params = [
        Param("a", "value", options_sql="SELECT 1"),
        Param("b", "value", options_sql="SELECT {a} FROM {a:identifier}"),
    ]
    asyncio.run(resolve(params, {}, run, {"a": PG, "b": CH}))
    assert seen == [("a", "SELECT 1"), ("b", "SELECT 'x' FROM `x`")]


def test_static_options_drop_null_and_containers():
    assert parse_params([{"name": "r", "options": ["eu", 2, None, [1], {"a": 1}]}])[0].options == ("eu", "2")


def test_option_text_matches_the_browser():
    assert [option_text(v) for v in ["a", 1, 1.0, 1.5, True, None]] == ["a", "1", "1", "1.5", "true", "null"]


def test_default_none_starts_unselected():
    assert parse_params([{"name": "table", "kind": "identifier", "options": ["a"], "default": "none"}]) == [
        Param(name="table", kind="identifier", options=("a",), auto_select=False)
    ]
    assert parse_params([{"name": "table", "options": ["a"]}])[0].auto_select is True


# --- substitute ------------------------------------------------------------

PARAMS = parse_params(
    [
        {"name": "table", "kind": "identifier", "options_sql": "SELECT 1"},
        {"name": "field", "kind": "identifier", "options_sql": "SELECT 1"},
        {"name": "region", "options": ["eu"]},
        {"name": "category", "kind": "dimension"},
    ]
)


def test_substitutes_an_identifier_as_a_quoted_identifier():
    assert _sub("SELECT {field} FROM {table}", PARAMS, {"field": "city", "table": "events"}) == (
        "SELECT `city` FROM `events`"
    )


def test_escapes_backslashes_only_where_the_dialect_does():
    user = parse_params([{"name": "user", "options": ["CORP\\alice"]}])
    assert _sub("WHERE u = {user}", user, {"user": "CORP\\alice"}) == "WHERE u = 'CORP\\\\alice'"
    assert substitute("WHERE u = {user}", user, {"user": "CORP\\alice"}, PG) == "WHERE u = 'CORP\\alice'"


def test_rejects_a_backslash_in_an_identifier_only_where_the_dialect_escapes():
    with pytest.raises(ParamError, match=r"^invalid identifier for \{field\}: a\\$"):
        _sub("SELECT {field}", PARAMS, {"field": "a\\"})
    assert substitute("SELECT {field}", PARAMS, {"field": "a\\"}, PG) == 'SELECT "a\\"'


def test_substitutes_a_value_as_a_quoted_literal():
    assert _sub("WHERE region = {region}", PARAMS, {"region": "eu"}) == "WHERE region = 'eu'"
    assert _sub("WHERE region = {region}", PARAMS, {"region": "o'brien"}) == "WHERE region = 'o''brien'"


def test_rejects_an_identifier_containing_the_quote():
    with pytest.raises(ParamError, match="invalid identifier for {field}: a`b"):
        _sub("SELECT {field}", PARAMS, {"field": "a`b"})


def test_a_dimension_is_its_column_when_checked_and_empty_when_not():
    assert _sub("GROUP BY {category}", PARAMS, {"category": "on"}) == "GROUP BY `category`"
    assert _sub("GROUP BY {category}", PARAMS, {"category": ""}) == "GROUP BY ''"
    assert substitute("GROUP BY {category}", PARAMS, {"category": "0"}, PG) == "GROUP BY ''"


def test_casts_override_the_kind_in_one_spot():
    assert _sub("WHERE table = {table:literal} FROM {table}", PARAMS, {"table": "events"}) == (
        "WHERE table = 'events' FROM `events`"
    )
    assert _sub("SELECT {region:identifier}", PARAMS, {"region": "eu"}) == "SELECT `eu`"


def test_rejects_an_unknown_cast():
    with pytest.raises(ParamError, match="^unknown cast for {field}: sql$"):
        _sub("SELECT {field:sql}", PARAMS, {"field": "city"})


def test_leaves_an_unknown_placeholder_untouched():
    assert _sub("SELECT {nope}", PARAMS, {}) == "SELECT {nope}"


def test_raises_when_a_declared_param_has_no_value():
    with pytest.raises(ParamError, match="^no value selected for {field}$"):
        _sub("SELECT {field}", PARAMS, {})


# --- placeholders_in / resolve_order / missing -----------------------------


def test_placeholders_in():
    assert placeholders_in("SELECT name FROM system.columns WHERE table = {table} AND x = {y}") == ["table", "y"]
    assert placeholders_in("WHERE table = {table:literal} OR t = {table}") == ["table"]
    assert placeholders_in("SELECT 1") == []


def test_orders_a_dependent_param_after_its_dependency():
    params = parse_params(
        [
            {
                "name": "field",
                "kind": "identifier",
                "options_sql": "SELECT name FROM system.columns WHERE table = {table}",
            },
            {"name": "table", "kind": "identifier", "options_sql": "SELECT name FROM system.tables"},
        ]
    )
    assert [p.name for p in resolve_order(params)] == ["table", "field"]


def test_keeps_declaration_order_when_nothing_depends():
    params = parse_params([{"name": "a", "options": ["1"]}, {"name": "b", "options": ["2"]}])
    assert [p.name for p in resolve_order(params)] == ["a", "b"]


def test_raises_on_a_dependency_cycle():
    params = parse_params(
        [
            {"name": "a", "kind": "identifier", "options_sql": "SELECT {b}"},
            {"name": "b", "kind": "identifier", "options_sql": "SELECT {a}"},
        ]
    )
    with pytest.raises(ParamError, match="^params dependency cycle at a$"):
        resolve_order(params)


MISSING = parse_params(
    [
        {"name": "table", "kind": "identifier", "options": ["events"], "default": "none"},
        {"name": "field", "kind": "identifier", "options": ["city"], "default": "none"},
        {"name": "category", "kind": "dimension"},
    ]
)


def test_missing_names_what_a_query_still_needs():
    assert missing("SELECT {field} FROM {table}", MISSING, {"table": "events"}) == ["field"]
    assert missing("SELECT {field} FROM {table}", MISSING, {"table": "events", "field": "city"}) == []


def test_missing_never_reports_a_dimension_or_an_unknown_placeholder():
    assert missing("GROUP BY {category}", MISSING, {}) == []
    assert missing("SELECT {nope}", MISSING, {}) == []


# --- resolve ---------------------------------------------------------------

DEPENDENT = parse_params(
    [
        {"name": "table", "kind": "identifier", "default": "none", "options_sql": "SELECT name FROM system.tables"},
        {
            "name": "field",
            "kind": "identifier",
            "default": "none",
            "options_sql": "SELECT name FROM system.columns WHERE table = {table:literal}",
        },
    ]
)


async def _tables_run(sql: str):
    return ["events"] if "system.tables" in sql else ["city", "ts"]


def test_leaves_a_dependent_param_unresolved_while_its_dependency_is_unset():
    assert _resolve(DEPENDENT, {}, _tables_run) == [
        {"name": "table", "kind": "identifier", "options": ["events"], "value": ""},
        {"name": "field", "kind": "identifier", "options": [], "value": ""},
    ]


def test_resolves_the_dependent_options_once_the_dependency_has_a_value():
    assert _resolve(DEPENDENT, {"table": "events"}, _tables_run)[1] == {
        "name": "field",
        "kind": "identifier",
        "options": ["city", "ts"],
        "value": "",
    }


def test_keeps_a_chosen_value_only_while_it_is_still_offered():
    assert _resolve(DEPENDENT, {"table": "events", "field": "city"}, _tables_run)[1]["value"] == "city"
    assert _resolve(DEPENDENT, {"table": "events", "field": "gone"}, _tables_run)[1]["value"] == ""


def test_auto_selects_the_first_option_unless_the_param_opts_out():
    auto = parse_params([{"name": "table", "kind": "identifier", "options_sql": "SELECT name FROM system.tables"}])
    assert _resolve(auto, {}, _tables_run)[0]["value"] == "events"


def test_options_from_sql_read_as_the_browser_showed_them():
    async def run(sql: str):
        return [1, 2.0, None]

    assert _resolve(parse_params([{"name": "n", "options_sql": "SELECT n"}]), {}, run)[0]["options"] == [
        "1",
        "2",
        "null",
    ]


def test_an_unchecked_dimension_stays_unchecked():
    params = parse_params([{"name": "by_city", "kind": "dimension"}])
    for v in ("", "0"):
        assert _resolve(params, {"by_city": v}, dialect=PG)[0]["value"] == ""
    assert _resolve(params, {"by_city": "on"}, dialect=PG)[0]["value"] == "on"


def test_apply_to_queries_holds_back_a_query_waiting_on_a_selector():
    params = [Param(name="table", kind="identifier", options=("t",), auto_select=False)]
    resolved = [{"name": "table", "kind": "identifier", "options": ["t"], "value": ""}]
    assert apply_to_queries({"a": "SELECT 1", "b": "SELECT * FROM {table}"}, params, resolved, {"a": PG, "b": PG}) == {
        "a": "SELECT 1"
    }
    chosen = [{**resolved[0], "value": "t"}]
    assert apply_to_queries({"b": "SELECT * FROM {table}"}, params, chosen, {"b": PG}) == {"b": 'SELECT * FROM "t"'}


# --- text params -----------------------------------------------------------

TEXT = parse_params(
    [
        {"name": "note", "kind": "text"},
        {"name": "seeded", "kind": "text", "default": "abc"},
        {"name": "scope", "options_sql": "SELECT if({note} = '', 'latest', {note})"},
    ]
)


async def _text_run(sql: str):
    return ["latest" if "if('' = ''" in sql else "typed"]


def test_text_parses_with_an_optional_default():
    assert [(p.name, p.kind, p.text) for p in TEXT] == [
        ("note", "text", ""),
        ("seeded", "text", "abc"),
        ("scope", "value", None),
    ]
    # `default: none` opens it empty, as for every kind.
    assert parse_params([{"name": "q", "kind": "text", "default": "none"}])[0].text == ""


def test_text_takes_what_was_sent_and_the_default_until_something_is():
    assert [p["value"] for p in _resolve(TEXT, {}, _text_run)] == ["", "abc", "latest"]
    typed = _resolve(TEXT, {"note": "o'k\\d", "seeded": ""}, _text_run)
    assert [p["value"] for p in typed] == ["o'k\\d", "", "typed"]


def test_a_text_is_capped():
    out = _resolve(parse_params([{"name": "n", "kind": "text"}]), {"n": "x" * 20_000}, dialect=PG)
    assert len(out[0]["value"]) == MAX_TEXT_PARAM


def test_text_substitutes_as_a_literal_and_never_as_an_identifier():
    assert _sub("SELECT {note}", TEXT, {"note": "o'k\\d"}) == "SELECT 'o''k\\\\d'"
    assert substitute("SELECT {note}", TEXT, {"note": "o'k\\d"}, PG) == "SELECT 'o''k\\d'"
    assert _sub("SELECT {note}", TEXT, {"note": ""}) == "SELECT ''"
    assert _sub("SELECT {note}", TEXT, {}) == "SELECT ''"
    with pytest.raises(ParamError, match="^{note} is text: it cannot be an identifier$"):
        _sub("SELECT {note:identifier}", TEXT, {"note": "a"})


def test_an_empty_text_is_a_value():
    assert missing("SELECT {note}", TEXT, {"note": ""}) == []


def test_a_name_declared_twice_keeps_the_first():
    # One declaration per name: a value is checked and substituted under the same one.
    twice = [{"name": "col", "kind": "text"}, {"name": "col", "kind": "identifier", "options": ["city"]}]
    assert parse_params(twice) == [Param(name="col", kind="text", text="")]
    assert _sub("SELECT {col}", parse_params(twice), {"col": "secret"}) == "SELECT 'secret'"


def test_needed_follows_options_sql_and_skips_the_rest():
    params = parse_params(
        [
            {"name": "db", "options": ["sales_reporting"]},
            {"name": "table", "kind": "identifier", "options_sql": "SELECT name FROM tables WHERE db = {db}"},
            {"name": "other", "options_sql": "SELECT 1"},
        ]
    )
    assert [p.name for p in needed("SELECT * FROM {table} WHERE x = '{nope}'", params)] == ["db", "table"]
    assert needed("SELECT 1", params) == []


# --- An `each` param: a list nobody picks from; a query naming it runs per value ---

REGION = Param("region", "each", options=("eu", "us"))


def _apply(queries, params):
    return apply_to_queries(queries, params, _resolve(params, {}), dict.fromkeys(queries, CH))


def test_an_each_param_resolves_to_its_list_and_no_value():
    assert _resolve([REGION], {"region": "us"}) == [
        {"name": "region", "kind": "each", "options": ["eu", "us"], "value": ""}
    ]


def test_a_query_naming_an_each_param_becomes_one_sql_per_option():
    out = _apply({"sales": "SELECT {region} FROM {region:identifier}", "totals": "SELECT 1"}, [REGION])
    assert out == {"sales": {"eu": "SELECT 'eu' FROM `eu`", "us": "SELECT 'us' FROM `us`"}, "totals": "SELECT 1"}


def test_a_query_naming_two_each_params_is_an_error():
    params = [REGION, Param("year", "each", options=("2025",))]
    with pytest.raises(ParamError, match="sales: one each param per query"):
        _apply({"sales": "SELECT {region}, {year}"}, params)


def test_more_than_a_hundred_values_is_an_error():
    many = Param("n", "each", options=tuple(str(i) for i in range(MAX_EACH + 1)))
    with pytest.raises(ParamError, match="n: more than 100 values"):
        _resolve([many], {})


def test_an_options_sql_cannot_use_an_each_param():
    picker = Param("city", "value", options_sql="SELECT city FROM t WHERE region = {region}")
    with pytest.raises(ParamError, match="city: options_sql cannot use the each param region"):
        _resolve([REGION, picker], {})


def test_an_each_param_lists_from_other_params():
    async def run(sql: str):
        assert sql == "SELECT region FROM t WHERE note = 'x'"
        return ["eu"]

    each = Param("region", "each", options_sql="SELECT region FROM t WHERE note = {note}")
    out = _resolve([Param("note", "text", text="x"), each], {}, run)
    assert out[1]["options"] == ["eu"]


def test_parses_an_each_param():
    assert parse_params([{"name": "region", "kind": "each", "options": ["eu", "us"]}]) == [REGION]
    assert parse_params([{"name": "region", "kind": "each"}]) == []


def test_an_empty_option_is_a_value_like_any_other():
    out = _apply({"sales": "SELECT {region}"}, [Param("region", "each", options=("", "eu"))])
    assert out == {"sales": {"": "SELECT ''", "eu": "SELECT 'eu'"}}


def test_a_repeated_option_runs_once():
    assert _resolve([Param("region", "each", options=("eu", "eu", "us"))], {})[0]["options"] == ["eu", "us"]


def test_a_query_waits_while_its_each_list_waits_on_a_choice():
    country = Param("country", "value", options=("de",), auto_select=False)
    each = Param("region", "each", options_sql="SELECT region FROM t WHERE country = {country}")
    assert _apply({"sales": "SELECT {region}", "one": "SELECT 1"}, [country, each]) == {"one": "SELECT 1"}
