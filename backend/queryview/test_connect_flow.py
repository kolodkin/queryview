"""Flow dispatch: connect_new persists with the given type; run_query routes to
the driver; the database gate is skipped when the driver exposes no databases."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import queryview.connect as connect
from queryview import sessions
from queryview.drivers import DRIVERS
from queryview.drivers.base import (
    Column,
    DatabasesResult,
    Err,
    FieldsResult,
    QueryRows,
    RowsResult,
    TablesResult,
    TextResult,
)


def _row(sid: str) -> sessions.SessionRec:
    """The session's stored record, which these tests require to exist."""
    rec = _run(sessions.get_session_rec(sid))
    assert rec is not None
    return rec


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

    async def list_databases(self, c, limit=1000, current=None):
        return DatabasesResult([])  # no picker

    async def run_query(self, c, sql, database, limit, offset, order_by):
        return RowsResult(QueryRows([Column("q", "String")], [[f"ran:{sql}:db={database}"]]))

    async def export_csv(self, c, sql, database, limit, offset, order_by):
        return TextResult(f"q\nran:{sql}:db={database}")

    async def describe_query(self, c, sql, database):
        return FieldsResult([{"name": "x", "type": "int"}])

    async def list_tables(self, c, database, union=False, limit=1000):
        return TablesResult([{"name": f"t-of-{database}", "rows": 1, "bytes": None}])


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


def test_list_connections_carries_card_metadata(monkeypatch):
    monkeypatch.setitem(DRIVERS, "fake", _FakeDriver())
    _run(connect.connect_new("s-c", "gamma", {"secret": "x"}, "fake"))
    cards = _run(connect.list_connections())
    card = next(c for c in cards if c["name"] == "gamma")
    # Type, remembered database and recency; never the (encrypted) config.
    assert card["type"] == "fake"
    assert card["database"] is None
    assert isinstance(card["last_active_at"], int)
    assert "config" not in card
    assert cards[0]["name"] == "gamma"


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

        async def list_databases(self, c, limit=1000, current=None):
            return DatabasesResult(["a", "b"])

    monkeypatch.setitem(DRIVERS, "fakedb", _WithDbs())
    sid = "s-fakedb"
    _run(connect.connect_new(sid, "g", {"v": 1}, "fakedb"))
    out = _run(connect.run_query(sid, "SELECT 1", 10, 0, None))
    assert out["ok"] is False and out["reason"] == "no-database"


def test_list_tables_requires_database_when_picker_present(monkeypatch):
    class _WithDbs(_FakeDriver):
        type = "fakedb2"
        requires_database = True

        async def list_databases(self, c, limit=1000, current=None):
            return DatabasesResult(["a", "b"])

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


def test_build_session_err_keeps_localhost_hint(monkeypatch):
    class _Down(_FakeDriver):
        type = "down"

        async def list_databases(self, c, limit=1000, current=None):
            return Err("connection refused")

    # connect_new takes the driver's parsed config object; the hint reads its host.
    monkeypatch.setitem(DRIVERS, "down", _Down())
    monkeypatch.setattr(connect, "_in_container", lambda: True)
    out = _run(connect.connect_new("s-down", "d", SimpleNamespace(host="localhost"), "down"))
    assert out["ok"] is False
    assert out["message"].startswith("connection refused")
    assert "host.docker.internal" in out["message"]


class _GrowingDriver(_FakeDriver):
    """A picker driver whose database list changes under a live session."""

    def __init__(self):
        self.databases = ["alpha", "beta"]
        self.fail = False

    async def list_databases(self, c, limit=1000, current=None):
        if self.fail:
            return Err("listing failed")
        return DatabasesResult(list(self.databases))


def test_refresh_databases_relists_and_keeps_the_selected_database(monkeypatch):
    """Databases created after connecting show up on refresh, and the selected
    database survives the re-list."""
    driver = _GrowingDriver()
    monkeypatch.setitem(DRIVERS, "growing", driver)
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "growing"))
    _run(connect.select_database(rec.id, "beta"))
    driver.databases.append("gamma")

    out = _run(connect.refresh_databases(rec.id))
    assert out == {"ok": True, "name": "reporting", "databases": ["alpha", "beta", "gamma"]}
    state = _run(connect.get_session(rec.id))
    assert state["databases"] == ["alpha", "beta", "gamma"]
    assert state["database"] == "beta"


def test_refresh_databases_keeps_the_old_list_when_listing_fails(monkeypatch):
    driver = _GrowingDriver()
    monkeypatch.setitem(DRIVERS, "growing", driver)
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "growing"))
    driver.fail = True

    out = _run(connect.refresh_databases(rec.id))
    assert out["ok"] is False and out["message"] == "listing failed"
    assert _run(connect.get_session(rec.id))["databases"] == ["alpha", "beta"]


def test_select_database_relists_on_a_miss(monkeypatch):
    """A database created after connecting can be selected without a reconnect:
    a miss on the cached list re-lists once before failing."""
    driver = _GrowingDriver()
    monkeypatch.setitem(DRIVERS, "growing", driver)
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting", {"v": 1}, "growing"))
    driver.databases.append("gamma")

    assert _run(connect.select_database(rec.id, "gamma")) == {"ok": True}
    assert _run(connect.get_session(rec.id))["database"] == "gamma"
    out = _run(connect.select_database(rec.id, "delta"))
    assert out["ok"] is False and out["message"] == "unknown database"
    # A re-list that fails is reported as such, not as a missing database.
    driver.fail = True
    out = _run(connect.select_database(rec.id, "epsilon"))
    assert out["ok"] is False and out["message"] == "listing failed"


def test_rebuild_keeps_an_unlisted_database_on_the_row_for_picker_drivers(monkeypatch):
    # Only DuckDB folder mode falls back to its root; a ClickHouse/Postgres row
    # keeps its selection, as refresh_databases does, even if no longer listed.
    fake = _FakeDriver()

    async def listed(c, limit=1000, current=None):
        return DatabasesResult(["other"])

    monkeypatch.setattr(fake, "list_databases", listed)
    monkeypatch.setitem(DRIVERS, "fake", fake)
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "reporting-keep", {"v": 1}, "fake", session_only=True))
    _run(sessions.set_database(rec.id, "gone"))
    connect._sessions.clear()
    _run(connect.get_session(rec.id))
    assert _row(rec.id).database == "gone"


def test_reopening_a_connection_goes_back_to_its_last_database_and_table(monkeypatch):
    # A picker driver: reopening skips the picker for the database last visited
    # in this session, and offers its table back.
    fake = _FakeDriver()

    async def two(c, limit=1000, current=None):
        return DatabasesResult(["db_a", "db_b"])

    monkeypatch.setattr(fake, "list_databases", two)
    monkeypatch.setitem(DRIVERS, "fake", fake)
    rec = _run(sessions.create_session())
    _run(connect.connect_new(rec.id, "lv-a", {"v": 1}, "fake", session_only=True))
    _run(connect.connect_new(rec.id, "lv-b", {"v": 2}, "fake", session_only=True))
    _run(connect.open_saved(rec.id, "lv-a"))
    assert _run(connect.select_database(rec.id, "db_b"))["ok"]
    _run(sessions.patch_session(rec.id, table="orders"))
    _run(connect.open_saved(rec.id, "lv-b"))
    r = _run(connect.open_saved(rec.id, "lv-a"))
    assert r["database"] == "db_b" and r["table"] == "orders"
    assert _run(connect.get_session(rec.id))["table"] == "orders"
    # A database no longer listed lands on the picker, as before.
    _run(sessions.set_database(rec.id, "db_gone"))
    _run(connect.open_saved(rec.id, "lv-b"))
    r = _run(connect.open_saved(rec.id, "lv-a"))
    assert r["database"] is None and "table" not in r
