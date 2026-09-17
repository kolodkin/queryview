"""Flow dispatch: connect_new persists with the given type; run_query routes to
the driver; the database gate is skipped when the driver exposes no databases."""

from __future__ import annotations

import asyncio

import queryview.connect as connect
from queryview import sessions
from queryview.drivers import DRIVERS
from queryview.drivers.base import Column, QueryResult, QueryRows, TextResult


def _run(coro):
    return asyncio.run(coro)


class _FakeDriver:
    type = "fake"
    requires_database = False  # no picker
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
        return True, []  # no picker

    async def run_query(self, c, sql, database, limit, offset, order_by):
        return QueryResult(True, QueryRows([Column("q", "String")], [[f"ran:{sql}:db={database}"]]))

    async def export_csv(self, c, sql, database, limit, offset, order_by):
        return TextResult(True, f"q\nran:{sql}:db={database}")

    async def describe_query(self, c, sql, database):
        return True, [{"name": "x", "type": "int"}]

    async def list_tables(self, c, database):
        return True, [{"name": f"t-of-{database}", "rows": 1, "bytes": None}]


def test_run_query_skips_db_gate_when_no_databases(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    sid = "s-fake"
    _run(connect.connect_new(sid, "f", {"v": 1}, "fake"))
    out = _run(connect.run_query(sid, "SELECT 1", 10, 0, None))
    assert out["ok"]
    assert out["meta"] == [{"name": "q", "type": "String"}]
    assert out["data"] == [["ran:SELECT 1:db=None"]]


def test_export_csv_routes_to_driver(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    sid = "s-fake-csv"
    _run(connect.connect_new(sid, "f", {"v": 1}, "fake"))
    out = _run(connect.export_csv(sid, "SELECT 1", 10, 0, None))
    assert out["ok"] and out["output"] == "q\nran:SELECT 1:db=None"


def test_disconnect_clears_session_and_suppresses_reconnect(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    sid = "s-disc"
    _run(connect.connect_new(sid, "f", {"v": 1}, "fake"))
    assert _run(connect.get_session(sid))["connected"] is True
    # Disconnect drops the active session...
    assert _run(connect.disconnect(sid)) == {"ok": True}
    # ...and stays disconnected even though a saved active connection exists,
    # i.e. get_session must not silently auto-reconnect it.
    assert _run(connect.get_session(sid))["connected"] is False
    # Connecting again clears the suppression.
    _run(connect.connect_new(sid, "f", {"v": 1}, "fake"))
    assert _run(connect.get_session(sid))["connected"] is True


def test_list_connection_names_orders_by_recency(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    _run(connect.connect_new("s-a", "alpha", {"v": 1}, "fake"))
    _run(connect.connect_new("s-b", "beta", {"v": 1}, "fake"))
    names = _run(connect.list_connection_names())
    # Most-recently-activated first; both saved connections are present.
    assert names[:2] == ["beta", "alpha"]


def test_list_tables_routes_to_driver_and_skips_db_gate(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    sid = "s-tables"
    _run(connect.connect_new(sid, "f", {"v": 1}, "fake"))
    out = _run(connect.list_tables(sid))
    # The browse SELECT is attached here, quoted with the driver's ident_quote.
    assert out["ok"] and out["tables"] == [
        {"name": "t-of-None", "rows": 1, "bytes": None, "query": 'SELECT * FROM "t-of-None"'},
    ]


def test_run_query_requires_database_when_picker_present(monkeypatch):
    class _WithDbs(_FakeDriver):
        type = "fakedb"
        requires_database = True

        async def list_databases(self, c):
            return True, ["a", "b"]

    monkeypatch.setitem(DRIVERS, "fakedb", _WithDbs())
    sid = "s-fakedb"
    _run(connect.connect_new(sid, "g", {"v": 1}, "fakedb"))
    out = _run(connect.run_query(sid, "SELECT 1", 10, 0, None))
    assert out["ok"] is False and out["reason"] == "no-database"


def test_list_tables_requires_database_when_picker_present(monkeypatch):
    class _WithDbs(_FakeDriver):
        type = "fakedb2"
        requires_database = True

        async def list_databases(self, c):
            return True, ["a", "b"]

    monkeypatch.setitem(DRIVERS, "fakedb2", _WithDbs())
    sid = "s-fakedb2"
    _run(connect.connect_new(sid, "g2", {"v": 1}, "fakedb2"))
    out = _run(connect.list_tables(sid))
    assert out["ok"] is False and out["reason"] == "no-database"
    # Selecting a database opens the gate; the driver sees the selection.
    _run(connect.select_database(sid, "a"))
    out = _run(connect.list_tables(sid))
    assert out["ok"] and out["tables"] == [
        {"name": "t-of-a", "rows": 1, "bytes": None, "query": 'SELECT * FROM "t-of-a"'},
    ]


def test_connect_writes_through_to_the_session_row(monkeypatch):
    """The session row, not the in-memory map, is what survives a restart."""
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    assert again.connection_name == "reporting"


def test_session_state_rebuilds_from_the_row_after_the_cache_is_dropped(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    connect._sessions.clear()  # as a backend restart would
    out = _run(connect.get_session(rec.id))
    assert out["connected"] is True
    assert out["name"] == "reporting"


def test_disconnect_clears_the_connection_durably(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "fake"))
    _run(connect.disconnect(rec.id))
    connect._sessions.clear()
    assert _run(connect.get_session(rec.id)) == {"connected": False}


def test_two_sessions_keep_their_own_connections(monkeypatch):
    """The old store reconnected whichever connection was globally latest, so
    two sessions could not differ. Each session now resolves its own row."""
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    a = _run(sessions.create_session())
    b = _run(sessions.create_session())
    _run(connect.connect_new(a.id, "reporting", {"v": 1}, "fake"))
    _run(connect.connect_new(b.id, "warehouse", {"v": 1}, "fake"))
    connect._sessions.clear()

    assert _run(connect.get_session(a.id))["name"] == "reporting"
    assert _run(connect.get_session(b.id))["name"] == "warehouse"
