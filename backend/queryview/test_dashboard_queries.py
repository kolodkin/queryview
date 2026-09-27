"""Dashboard query runner: runs on the session's connection, typed and
column-oriented straight from the driver's rows (no text round-trip),
fail-fast on the first failing query."""

from __future__ import annotations

import asyncio

import queryview.connect as connect
from queryview.dashboard_queries import run_dashboard_queries
from queryview.drivers import DRIVERS
from queryview.drivers.base import Column, QueryResult, QueryRows


class _RowsDriver:
    type = "rowsfake"
    requires_database = False
    ident_quote = '"'

    def parse_config(self, body):
        return {"v": 1}, None

    def config_to_dict(self, c):
        return c

    def config_from_dict(self, d):
        return d

    async def test(self, c):
        return {"ok": True, "message": "ok"}

    async def list_databases(self, c):
        return True, []

    async def run_query(self, c, sql, database, limit, offset, order_by):
        if "fail" in sql:
            return QueryResult(False, None, "bad sql")
        return QueryResult(True, QueryRows([Column("n", "Int32"), Column("s", "String")], [[1, "a"], [2, "b"]]))


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
