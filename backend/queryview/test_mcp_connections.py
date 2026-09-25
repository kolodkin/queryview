"""MCP tools take the connection from the session; the agent never names one."""

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


def test_push_dashboard_runs_on_the_session_connection():
    from queryview.mcp_server import push_dashboard

    sid = _connected_session("sc-dash")
    rid = remote.register(sid)
    try:
        out = _run(push_dashboard(rid, "d", "<p></p>", {"q": "SELECT 1"}))
        assert out["ok"] is True and out["pushed"] is True
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None and msg["connection"] == "sc-dash"
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


def test_no_list_connections_tool():
    from queryview.mcp_server import mcp

    assert "list_connections" not in {t.name for t in _run(mcp.list_tools())}


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
