"""list_connections exposes only {name, type, database} (never hosts or
credentials), and an unknown connection name fails listing the valid ones."""

from __future__ import annotations

import asyncio
import json
import uuid

from queryview import remote, sessions
from queryview.connect import _save_active_connection, _save_selected_database
from queryview.drivers.clickhouse import ChConfig


def _run(coro):
    return asyncio.run(coro)


def _save(name: str, database: str | None = None) -> None:
    _run(
        _save_active_connection(
            name, ChConfig("secret-host.example.internal", 8123, "alice", "TOPSECRET"), "clickhouse"
        )
    )
    if database:
        _run(_save_selected_database(name, database))


def test_list_connections_returns_names_types_databases_without_secrets():
    from queryview.mcp_server import list_connections

    _save("lc-local", "sales_reporting")
    out = _run(list_connections())
    assert set(out) == {"connections"}
    by_name = {c["name"]: c for c in out["connections"]}
    assert by_name["lc-local"] == {"name": "lc-local", "type": "clickhouse", "database": "sales_reporting"}
    assert all(set(c) == {"name", "type", "database"} for c in out["connections"])
    dumped = json.dumps(out)
    for secret in ("secret-host.example.internal", "alice", "TOPSECRET", "8123"):
        assert secret not in dumped


def test_list_connections_scoped_to_session():
    """A session on another workspace still sees the (global) connections, plus
    the connection it is on."""
    from queryview.mcp_server import list_connections
    from queryview.workspaces import create_workspace

    _save("lc-sess")
    _run(create_workspace("t-lc-ws"))
    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, workspace="t-lc-ws"))
    _run(sessions.set_connection(rec.id, "lc-sess"))
    rid = remote.register(rec.id)
    try:
        out = _run(list_connections(session_id=rid))
        assert "lc-sess" in [c["name"] for c in out["connections"]]
        assert out["session_connection"] == "lc-sess"
        assert "TOPSECRET" not in json.dumps(out)
    finally:
        remote.unregister(rid)


def test_list_connections_survives_deleted_session_workspace():
    """Connections are global, so a session whose workspace is gone still lists them."""
    from queryview.mcp_server import list_connections
    from queryview.workspaces import create_workspace, delete_workspace

    _save("lc-gone")
    _run(create_workspace("t-lc-gone"))
    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, workspace="t-lc-gone"))
    _run(delete_workspace("t-lc-gone"))
    out = _run(list_connections(session_id=rec.id))
    assert "lc-gone" in [c["name"] for c in out["connections"]]


def test_list_connections_is_registered():
    from queryview.mcp_server import mcp

    assert "list_connections" in {t.name for t in _run(mcp.list_tools())}


def test_run_query_unknown_connection_lists_available_names():
    from queryview.mcp_server import run_query

    _save("lc-avail-a")
    _save("lc-avail-b")
    out = _run(run_query("SELECT 1", connection="lc-missing"))
    assert out["ok"] is False
    msg = out["message"]
    assert msg.startswith('no connection named "lc-missing"; available: ')
    assert "lc-avail-a" in msg and "lc-avail-b" in msg


def test_push_dashboard_unknown_connection_fails_without_pushing():
    from queryview.mcp_server import push_dashboard

    _save("lc-dash")
    rid = remote.register(uuid.uuid4().hex)
    try:
        out = _run(push_dashboard(rid, "d", "lc-nope", "<p></p>", {"q": "SELECT 1"}))
        assert out["ok"] is False and out["pushed"] is False
        assert 'no connection named "lc-nope"; available: ' in out["message"]
        assert "lc-dash" in out["message"]
        assert _run(remote.next_message(rid, 0.1)) is None
    finally:
        remote.unregister(rid)


def test_open_saved_unknown_connection_lists_available_names():
    from queryview.connect import open_saved

    _save("lc-open")
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
