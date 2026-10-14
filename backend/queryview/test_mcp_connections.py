"""MCP tools run on the session's connection; the agent switches only to
session connections it added itself."""

from __future__ import annotations

import asyncio

from queryview import remote, sessions
from queryview.connect import _save_active_connection, open_saved
from queryview.drivers.clickhouse import ChConfig
from queryview.drivers.duckdb import DuckConfig


def _run(coro):
    return asyncio.run(coro)


def _connected_session(name: str) -> str:
    """A new session on a saved in-memory DuckDB connection named `name`."""
    _run(_save_active_connection(name, DuckConfig(":memory:"), "duckdb"))
    rec = _run(sessions.create_session())
    assert _run(open_saved(rec.id, name))["ok"]
    return rec.id


def test_run_query_uses_the_session_connection():
    from queryview.mcp_server import run_query

    sid = _connected_session("sc-duck")
    out = _run(run_query(sid, "SELECT 42 AS answer, 'x' AS label", limit=10))
    assert out["ok"] is True
    assert out["columns"] == ["answer", "label"]
    assert out["rows"] == [[42, "x"]]
    assert len(out["types"]) == 2
    assert "connection" not in out


def test_run_query_on_disconnected_session_fails():
    from queryview.mcp_server import run_query

    rec = _run(sessions.create_session())
    out = _run(run_query(rec.id, "SELECT 1"))
    assert out == {"ok": False, "message": "not connected"}


def test_run_query_unknown_session_fails():
    from queryview.mcp_server import run_query

    out = _run(run_query("no-such-session", "SELECT 1"))
    assert out["ok"] is False


def test_push_dashboard_names_no_connection():
    """The draft carries no connection: it runs on whichever session views it."""
    from queryview.mcp_server import push_dashboard

    sid = _connected_session("sc-dash")
    rid = remote.register(sid)
    try:
        out = _run(push_dashboard(rid, "d", "<p></p>", {"q": "SELECT 1"}))
        assert out["ok"] is True and out["pushed"] is True
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None and msg["type"] == "dashboard" and "connection" not in msg
    finally:
        remote.unregister(rid)


def test_push_dashboard_on_disconnected_session_fails_without_pushing():
    from queryview.mcp_server import push_dashboard

    rec = _run(sessions.create_session())
    rid = remote.register(rec.id)
    try:
        out = _run(push_dashboard(rid, "d", "<p></p>", {"q": "SELECT 1"}))
        assert out["ok"] is False and out["pushed"] is False
        assert out["message"] == "not connected"
        assert _run(remote.next_message(rid, 0.1)) is None
    finally:
        remote.unregister(rid)


def _agent_add(sid: str, name: str) -> dict:
    """add_connection, then the user confirming its dialog."""
    from queryview import connect
    from queryview.mcp_server import add_connection

    rid = remote.register(sid)
    try:
        assert _run(add_connection(sid, name, "duckdb", {"path": ":memory:"}))["ok"]
        msg = _run(remote.next_message(rid, 1.0)) or {}
    finally:
        remote.unregister(rid)
    assert msg["action"] == "add" and msg["details"] == {"path": ":memory:"}
    assert name not in connect._session_conns.get(sid, {})  # nothing until confirmed
    return _run(connect.confirm_add(sid, msg["id"]))


def test_add_connection_dialog_hides_the_password_and_needs_an_armed_session():
    from queryview import connect
    from queryview.mcp_server import add_connection

    sid = _run(sessions.create_session()).id
    cfg = {"host": "db.example.internal", "port": 8123, "username": "u", "password": "secret"}
    assert _run(add_connection(sid, "ag-ch", "clickhouse", cfg))["message"] == "unknown or inactive session"
    assert not connect._pending_adds.get(sid)
    rid = remote.register(sid)
    try:
        assert _run(add_connection(sid, "ag-ch", "clickhouse", cfg))["ok"]
        msg = _run(remote.next_message(rid, 1.0)) or {}
    finally:
        remote.unregister(rid)
    assert "password" not in msg["details"] and msg["details"]["host"] == "db.example.internal"
    assert connect.add_ask(sid) == msg  # a reloaded tab reopens the same dialog
    assert _run(connect.confirm_add(sid, "bogus"))["ok"] is False
    connect.drop_add(sid, msg["id"])  # the user cancelled
    assert _run(connect.confirm_add(sid, msg["id"]))["message"] == "no such request"


def _names(out):
    return {c["name"]: c for c in out["connections"]}


def test_agent_session_connection_lifecycle():
    """Added in memory only, usable and removable by the agent, never saved."""
    from queryview import connect
    from queryview.mcp_server import list_connections, remove_connection, run_query, use_connection

    sid = _run(sessions.create_session()).id
    other = _run(sessions.create_session()).id
    out = _agent_add(sid, "ag-mem")
    assert out["ok"] is True
    assert "ag-mem" not in _run(connect.list_connection_names())
    assert "ag-mem" not in _names(_run(list_connections(other)))

    entry = _names(_run(list_connections(sid)))["ag-mem"]
    assert entry["scope"] == "session" and entry["created_by"] == "agent" and entry["active"] is False

    assert _run(use_connection(sid, "ag-mem"))["ok"] is True
    assert _names(_run(list_connections(sid)))["ag-mem"]["active"] is True
    assert _run(run_query(sid, "SELECT 1 AS one"))["rows"] == [[1]]
    assert any(r["id"] == sid and r["connection"] == "ag-mem" for r in _run(sessions.list_sessions()))

    # A bad database fails before the session switches.
    assert _agent_add(sid, "ag-mem2")["ok"]
    assert _run(use_connection(sid, "ag-mem2", "nope"))["message"] == "unknown database"
    assert _names(_run(list_connections(sid)))["ag-mem"]["active"] is True

    assert _run(remove_connection(sid, "ag-mem"))["ok"] is True
    assert "ag-mem" not in _names(_run(list_connections(sid)))
    assert _run(run_query(sid, "SELECT 1")) == {"ok": False, "message": "not connected"}


def test_add_connection_refuses_a_taken_name_and_bad_input():
    from queryview.mcp_server import add_connection

    _run(_save_active_connection("ag-taken", DuckConfig(":memory:"), "duckdb"))
    sid = _run(sessions.create_session()).id
    assert "already exists" in _run(add_connection(sid, "ag-taken", "duckdb", {"path": ":memory:"}))["message"]
    assert _run(add_connection(sid, "x", "nope", {}))["ok"] is False
    assert _run(add_connection(sid, "x", "clickhouse", {"host": "h", "port": 0}))["ok"] is False


def test_agent_cannot_use_or_remove_saved_or_user_connections():
    from queryview.connect import add_session_connection
    from queryview.mcp_server import remove_connection, use_connection

    sid = _connected_session("ag-saved")
    _run(add_session_connection(sid, "ag-user", DuckConfig(":memory:"), "duckdb", "user"))
    for name in ("ag-saved", "ag-user"):
        for tool in (use_connection, remove_connection):
            out = _run(tool(sid, name))
            assert out["ok"] is False and "pick_connection" in out["message"]


def test_select_database_direct_on_own_connection_else_a_dialog():
    from queryview import connect
    from queryview.mcp_server import select_database, use_connection

    sid = _connected_session("ag-seldb")
    connect._sessions[sid].databases = ["memory"]  # DuckDB lists none; fake a picker
    assert _run(select_database(sid, "nope"))["message"] == "unknown database"
    rid = remote.register(sid)
    try:
        out = _run(select_database(sid, "memory"))
        assert out["ok"] is True and out["message"] == "waiting for the user to confirm"
        assert _run(remote.next_message(rid, 1.0)) == {
            "type": "connection",
            "name": "ag-seldb",
            "action": "pick",
            "database": "memory",
        }
    finally:
        remote.unregister(rid)

    assert _agent_add(sid, "ag-seldb-own")["ok"]
    assert _run(use_connection(sid, "ag-seldb-own"))["ok"]
    connect._sessions[sid].databases = ["memory"]
    assert _run(select_database(sid, "memory"))["ok"] is True
    assert _run(sessions.database_of(sid)) == "memory"
    rec = _run(sessions.create_session())
    assert _run(select_database(rec.id, "memory"))["message"] == "not connected"


def test_pick_and_promote_push_a_dialog_and_promote_saves():
    from queryview import connect
    from queryview.mcp_server import pick_connection, promote_connection

    sid = _connected_session("ag-pick")
    assert _agent_add(sid, "ag-promo")["ok"]
    assert _run(pick_connection(sid, "ag-pick"))["message"] == "unknown or inactive session"
    rid = remote.register(sid)
    try:
        assert _run(pick_connection(sid, "ag-pick", "main"))["ok"] is True
        assert _run(remote.next_message(rid, 1.0)) == {
            "type": "connection",
            "name": "ag-pick",
            "action": "pick",
            "database": "main",
        }
        assert _run(pick_connection(sid, "ag-absent"))["ok"] is False
        assert _run(promote_connection(sid, "ag-pick"))["ok"] is False  # saved already
        assert _run(promote_connection(sid, "ag-promo"))["ok"] is True
        assert (_run(remote.next_message(rid, 1.0)) or {}).get("action") == "promote"
    finally:
        remote.unregister(rid)
    # Nothing is saved until the user confirms (the browser calls promote).
    assert "ag-promo" not in _run(connect.list_connection_names())
    assert _run(connect.promote_connection(sid, "ag-promo"))["ok"] is True
    assert "ag-promo" in _run(connect.list_connection_names())


def test_open_saved_unknown_connection_lists_available_names():
    _run(_save_active_connection("lc-open", ChConfig("h.example.internal", 8123, "u", "p"), "clickhouse"))
    out = _run(open_saved("lc-open-sid", "lc-absent"))
    assert out["not_found"] is True
    assert "available: " in out["message"] and "lc-open" in out["message"]


def test_localhost_hint_only_inside_container(monkeypatch):
    import queryview.connect as connect

    cfg = ChConfig("localhost", 8123, "u", "p")
    monkeypatch.setattr(connect, "_in_container", lambda: False)
    assert connect._with_localhost_hint("refused", cfg) == "refused"
    monkeypatch.setattr(connect, "_in_container", lambda: True)
    assert "host.docker.internal" in connect._with_localhost_hint("refused", cfg)
    other = ChConfig("db.example.internal", 8123, "u", "p")
    assert connect._with_localhost_hint("refused", other) == "refused"


def test_session_info_describes_the_session(tmp_path):
    import duckdb

    from queryview.mcp_server import session_info

    path = str(tmp_path / "info.duckdb")
    duckdb.connect(path).execute("CREATE TABLE info_items (id INTEGER)").close()
    _run(_save_active_connection("sc-info", DuckConfig(path), "duckdb"))
    sid = _run(sessions.create_session()).id
    assert _run(open_saved(sid, "sc-info"))["ok"]

    out = _run(session_info(sid))
    assert out["ok"] is True and out["connected"] is True
    assert out["connection"] == "sc-info" and out["type"] == "duckdb"
    assert out["workspace"]
    assert "info_items" in [t["name"] for t in out["tables"]]
    assert all("query" not in t for t in out["tables"])


def test_session_info_on_a_disconnected_or_unknown_session():
    from queryview.mcp_server import session_info

    rec = _run(sessions.create_session())
    out = _run(session_info(rec.id))
    assert out["ok"] is True and out["connected"] is False and "tables" not in out
    assert _run(session_info("no-such-session"))["ok"] is False


def test_saved_connect_refuses_a_session_connection_name():
    from queryview.connect import add_session_connection, connect_new

    sid = _run(sessions.create_session()).id
    _run(add_session_connection(sid, "ag-clash", DuckConfig(":memory:"), "duckdb", "user"))
    out = _run(connect_new(sid, "ag-clash", DuckConfig(":memory:"), "duckdb"))
    assert out["ok"] is False and "already exists" in out["message"]
