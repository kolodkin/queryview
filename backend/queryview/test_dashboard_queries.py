"""Dashboard query runner: runs on the session's connection, typed and
column-oriented straight from the driver's rows (no text round-trip),
fail-fast on the first failing query."""

from __future__ import annotations

import asyncio

import queryview.connect as connect
from queryview.dashboard_queries import clean_values, run_dashboard, run_dashboard_queries
from queryview.drivers import DRIVERS
from queryview.drivers.base import Column, DatabasesResult, Err, QueryRows, RowsResult


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


def _connected(monkeypatch, sid: str) -> _SeenDriver:
    driver = _SeenDriver()
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
