"""MCP tools for the Queries page: run_script returns per-statement results to
the agent; push_script fills the browser's Queries editor."""

from __future__ import annotations

from queryview import remote, sessions
from queryview.mcp_server import push_script, run_script
from queryview.test_mcp_connections import _connected_session, _run


def test_run_script_runs_writes_and_returns_each_statement():
    sid = _connected_session("ss-duck")
    out = _run(run_script(sid, "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1), (2); SELECT a FROM t ORDER BY a"))
    assert out["ok"] is True
    create, insert, select = out["results"]
    assert create["ok"] and create["sql"] == "CREATE TABLE t (a INTEGER)"
    assert create["rows"] is None and create["columns"] is None
    assert insert["ok"]
    assert select["columns"] == ["a"] and len(select["types"]) == 1
    assert select["rows"] == [[1], [2]]
    assert select["truncated"] is False
    assert {"status", "message", "elapsed_ms"} <= select.keys()


def test_run_script_stops_at_first_error():
    sid = _connected_session("ss-err")
    out = _run(run_script(sid, "SELECT 1; SELECT * FROM no_such_table; SELECT 2"))
    assert out["ok"] is True
    assert [r["ok"] for r in out["results"]] == [True, False]
    assert out["results"][1]["message"]


def test_run_script_requires_sql():
    assert _run(run_script(_connected_session("ss-empty"), "  ")) == {"ok": False, "message": "sql required"}


def test_run_script_on_disconnected_session_fails():
    rec = _run(sessions.create_session())
    assert _run(run_script(rec.id, "SELECT 1")) == {"ok": False, "message": "not connected"}


def test_push_script_delivers_to_the_armed_session():
    sid = _connected_session("ss-push")
    rid = remote.register(sid)
    try:
        out = _run(push_script(rid, "SELECT 1; SELECT 2", run=True))
        assert out["ok"] is True and out["message"] == "delivered"
        msg = _run(remote.next_message(rid, 1.0))
        assert msg == {"type": "script", "sql": "SELECT 1; SELECT 2", "run": True}
        _run(push_script(rid, "SELECT 3"))
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None and msg["run"] is False
    finally:
        remote.unregister(rid)


def test_push_script_blocked_while_user_edits():
    rid = remote.register(_connected_session("ss-lock"))
    try:
        assert remote.acquire(rid, "human")[0]
        out = _run(push_script(rid, "SELECT 1"))
        assert out["ok"] is False and out["message"] == "blocked, user editing"
        assert _run(remote.next_message(rid, 0.1)) is None
    finally:
        remote.unregister(rid)


def test_push_script_unknown_session_fails():
    assert _run(push_script("no-such-session", "SELECT 1"))["ok"] is False


def test_push_script_on_disconnected_session_is_not_delivered():
    rid = remote.register(_run(sessions.create_session()).id)
    try:
        assert _run(push_script(rid, "SELECT 1", run=True)) == {
            "ok": False,
            "message": "not connected",
            "database": None,
        }
        assert _run(remote.next_message(rid, 0.1)) is None
    finally:
        remote.unregister(rid)
