"""Dashboard query runner: runs on the session's connection, typed and
column-oriented straight from the driver's rows (no text round-trip),
fail-fast on the first failing query."""

from __future__ import annotations

import asyncio

import queryview.connect as connect
from queryview.dashboard_queries import (
    DASHBOARD_CONCURRENCY,
    clean_values,
    ready_sql,
    run_dashboard,
    run_dashboard_queries,
)
from queryview.drivers import DRIVERS
from queryview.drivers.base import Column, DatabasesResult, Err, QueryRows, RowsResult
from queryview.test_dashboard_params import PG


class _RowsDriver:
    type = "rowsfake"
    requires_database = False
    ident_quote = '"'
    backslash_escapes = False

    def parse_config(self, body):
        return {"v": 1}, None

    def config_to_dict(self, c):
        return c

    def config_from_dict(self, d):
        return d

    async def test(self, c):
        return {"ok": True, "message": "ok"}

    async def list_databases(self, c, limit=1000, current=None):
        return DatabasesResult([])

    async def run_query(self, c, sql, database, limit, offset, order_by):
        if "fail" in sql:
            return Err("bad sql")
        return RowsResult(QueryRows([Column("n", "Int32"), Column("s", "String")], [[1, "a"], [2, "b"]]))


def test_run_queries_returns_typed_columns(monkeypatch):
    monkeypatch.setitem(DRIVERS, "rowsfake", _RowsDriver())
    asyncio.run(connect.connect_new("s-dash", "dash", {"v": 1}, "rowsfake"))
    out = asyncio.run(run_dashboard_queries("s-dash", {"q": "SELECT 1"}))
    assert out["ok"]
    assert out["results"] == {"q": {"n": [1, 2], "s": ["a", "b"]}}
    assert out["meta"] == {"q": [{"name": "n", "type": "Int32"}, {"name": "s", "type": "String"}]}


def test_run_queries_fails_fast_with_query_name(monkeypatch):
    monkeypatch.setitem(DRIVERS, "rowsfake", _RowsDriver())
    asyncio.run(connect.connect_new("s-dash2", "dash2", {"v": 1}, "rowsfake"))
    out = asyncio.run(run_dashboard_queries("s-dash2", {"ok": "SELECT 1", "broken": "fail"}))
    assert out == {"ok": False, "reason": "query", "message": "broken: bad sql"}


def test_run_queries_needs_a_connected_session():
    out = asyncio.run(run_dashboard_queries("s-dash-none", {"q": "SELECT 1"}))
    assert out["ok"] is False and out["reason"] == "no-session"


# --- With params: resolved and substituted here (docs/dashboard.md#dashboard-parameters) ---


class _SeenDriver(_RowsDriver):
    def __init__(self):
        self.seen: list[str] = []

    async def run_query(self, c, sql, database, limit, offset, order_by):
        self.seen.append(sql)
        return await super().run_query(c, sql, database, limit, offset, order_by)


def _connected(monkeypatch, sid: str, driver=None):
    driver = driver or _SeenDriver()
    monkeypatch.setitem(DRIVERS, "rowsfake", driver)
    asyncio.run(connect.connect_new(sid, sid, {"v": 1}, "rowsfake"))
    return driver


def test_run_dashboard_resolves_then_substitutes(monkeypatch):
    driver = _connected(monkeypatch, "s-p1")
    params = [{"name": "pick", "options_sql": "SELECT n"}]
    out = asyncio.run(run_dashboard("s-p1", {"q": "SELECT {pick}"}, params, {}))
    assert out["ok"] and set(out["results"]) == {"q"}
    assert out["params"] == [{"name": "pick", "kind": "value", "options": ["1", "2"], "value": "1"}]
    assert driver.seen == ["SELECT n", "SELECT '1'"]


def test_run_dashboard_keeps_a_sent_value_the_options_offer(monkeypatch):
    driver = _connected(monkeypatch, "s-p1b")
    params = [{"name": "pick", "options_sql": "SELECT n"}]
    out = asyncio.run(run_dashboard("s-p1b", {"q": "SELECT {pick}"}, params, {"pick": "2"}))
    assert out["params"][0]["value"] == "2" and driver.seen[-1] == "SELECT '2'"


def test_run_dashboard_holds_back_a_query_waiting_on_a_choice(monkeypatch):
    driver = _connected(monkeypatch, "s-p2")
    params = [{"name": "r", "options": ["eu"], "default": "none"}]
    out = asyncio.run(run_dashboard("s-p2", {"q": "SELECT {r}"}, params, {}))
    assert out["ok"] and out["results"] == {} and driver.seen == []


def test_run_dashboard_reports_a_bad_value(monkeypatch):
    _connected(monkeypatch, "s-p3")
    out = asyncio.run(run_dashboard("s-p3", {"q": "SELECT {r:nope}"}, [{"name": "r", "options": ["eu"]}], {}))
    assert out == {"ok": False, "reason": "params", "message": "unknown cast for {r}: nope"}


def test_run_dashboard_reports_a_failing_options_sql(monkeypatch):
    _connected(monkeypatch, "s-p4")
    out = asyncio.run(run_dashboard("s-p4", {"q": "SELECT 1"}, [{"name": "r", "options_sql": "fail"}], {}))
    assert out == {"ok": False, "reason": "params", "message": "bad sql"}


def test_a_failing_query_still_returns_the_selectors(monkeypatch):
    _connected(monkeypatch, "s-p5")
    out = asyncio.run(run_dashboard("s-p5", {"broken": "fail {r}"}, [{"name": "r", "options": ["eu"]}], {}))
    assert out["ok"] is False and out["reason"] == "query" and out["message"] == "broken: bad sql"
    assert out["params"] == [{"name": "r", "kind": "value", "options": ["eu"], "value": "eu"}]


def test_run_dashboard_needs_a_connected_session():
    out = asyncio.run(run_dashboard("s-p-none", {"q": "SELECT 1"}, [], {}))
    assert out["ok"] is False and out["reason"] == "no-session"


def test_clean_values_keeps_only_strings():
    assert clean_values({"a": "x", "b": 5, "c": None, "d": ["x"], 1: "y"}) == {"a": "x"}
    assert clean_values(None) == {} and clean_values(["a"]) == {}


def test_clean_values_drops_text_that_cannot_be_sent_back():
    # A lone surrogate parses from JSON but cannot be encoded into the reply.
    assert clean_values({"a": "\ud800", "b": "ok"}) == {"b": "ok"}


class _SlowDriver(_RowsDriver):
    """Counts the queries in flight; `fail` fails at once, the rest wait a tick."""

    def __init__(self):
        self.running = 0
        self.peak = 0
        self.finished: list[str] = []

    async def run_query(self, c, sql, database, limit, offset, order_by):
        if "fail" in sql:
            return Err("bad sql")
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.02)
        finally:
            self.running -= 1
        self.finished.append(sql)
        return RowsResult(QueryRows([Column("n", "Int32")], [[1]]))


def test_queries_run_together_up_to_the_limit_and_keep_their_order(monkeypatch):
    driver = _connected(monkeypatch, "s-par1", _SlowDriver())
    names = [f"q{i}" for i in range(DASHBOARD_CONCURRENCY + 3)]
    r = asyncio.run(run_dashboard_queries("s-par1", {n: f"SELECT {n}" for n in names}))
    assert r["ok"] is True
    assert driver.peak == DASHBOARD_CONCURRENCY
    assert list(r["results"]) == names and list(r["meta"]) == names


def test_a_failing_query_stops_the_ones_still_running(monkeypatch):
    driver = _connected(monkeypatch, "s-par2", _SlowDriver())
    r = asyncio.run(run_dashboard_queries("s-par2", {"bad": "fail", "slow": "SELECT 1"}))
    assert r == {"ok": False, "reason": "query", "message": "bad: bad sql"}
    assert driver.finished == [] and driver.running == 0


# --- A query run once per value of an `each` param (docs/dashboard.md) ---

EACH = [{"name": "region", "kind": "each", "options": ["eu", "us", "ap"]}]


class _RegionDriver(_RowsDriver):
    """One row per run, naming the value its SQL carries; `us` answers last."""

    async def run_query(self, c, sql, database, limit, offset, order_by):
        if "bad" in sql:
            return Err("bad sql")
        if "WHERE 0" in sql:
            return RowsResult(QueryRows([Column("region", "String")], []))
        if "us" in sql:
            await asyncio.sleep(0.01)
        cols = [Column("other" if "odd" in sql and "ap" in sql else "region", "String")]
        return RowsResult(QueryRows(cols, [[sql.split("'")[1]]] * (600 if "many" in sql else 1)))


def _each(monkeypatch, sid, queries, params=EACH):
    _connected(monkeypatch, sid, _RegionDriver())
    return asyncio.run(run_dashboard(sid, queries, params, {}))


def test_a_query_per_value_stacks_its_rows_in_the_lists_order(monkeypatch):
    out = _each(monkeypatch, "s-each", {"sales": "SELECT {region}", "one": "SELECT 'x'"})
    assert out["results"] == {"sales": {"region": ["eu", "us", "ap"]}, "one": {"region": ["x"]}}
    assert out["meta"]["sales"] == [{"name": "region", "type": "String"}]


def test_a_failing_value_is_named(monkeypatch):
    out = _each(
        monkeypatch,
        "s-each-bad",
        {"sales": "SELECT {region}"},
        [{"name": "region", "kind": "each", "options": ["eu", "bad"]}],
    )
    assert (out["ok"], out["message"]) == (False, "sales[bad]: bad sql")


def test_values_must_return_the_same_columns(monkeypatch):
    out = _each(monkeypatch, "s-each-cols", {"sales": "SELECT {region} -- odd"})
    assert (out["ok"], out["message"]) == (False, "sales: columns differ between values")


def test_no_values_is_an_empty_result(monkeypatch):
    out = _each(
        monkeypatch,
        "s-each-none",
        {"sales": "SELECT {region}"},
        [{"name": "region", "kind": "each", "options_sql": "SELECT 'none' WHERE 0"}],
    )
    assert (out["results"], out["meta"]) == ({"sales": {}}, {"sales": []})


def test_the_stacked_rows_keep_the_first_of_the_cap(monkeypatch):
    out = _each(monkeypatch, "s-each-cap", {"sales": "SELECT {region} -- many"})
    assert out["results"]["sales"] == {"region": ["eu"] * 600 + ["us"] * 400}


def test_a_widget_cannot_page_a_query_run_per_value():
    sql, why = ready_sql("SELECT {region}", EACH, {}, PG)
    assert (sql, why) == (None, "a widget cannot page a query run per value")


def test_a_query_named_like_a_runs_label_is_its_own(monkeypatch):
    out = _each(monkeypatch, "s-each-name", {"sales": "SELECT {region}", "sales[eu]": "SELECT 'x'"})
    assert out["results"] == {"sales": {"region": ["eu", "us", "ap"]}, "sales[eu]": {"region": ["x"]}}


def test_values_past_a_full_cap_are_not_waited_for(monkeypatch):
    # `ap` would fail on its columns; the cap is full before it is read.
    out = _each(
        monkeypatch,
        "s-each-full",
        {"sales": "SELECT {region} -- many odd"},
    )
    assert out["ok"] and len(out["results"]["sales"]["region"]) == 1000
