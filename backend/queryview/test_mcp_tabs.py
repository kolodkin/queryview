"""A push with `tab` lands in a tab session under the session pushed to: the
first time parked while the parent's browser opens the tab, after that
straight to the tab's own channel (docs/remote.md#tabs)."""

from __future__ import annotations

import asyncio

from queryview import remote, sessions
from queryview.connect import _save_active_connection, add_session_connection, list_connections_for, open_saved
from queryview.drivers.duckdb import DuckConfig


def _run(coro):
    return asyncio.run(coro)


def _session_on(name: str) -> str:
    """A new session on a saved in-memory DuckDB connection named `name`."""
    _run(_save_active_connection(name, DuckConfig(":memory:"), "duckdb"))
    rec = _run(sessions.create_session())
    assert _run(open_saved(rec.id, name))["ok"]
    return rec.id


def test_a_push_with_a_tab_opens_it_once_then_reaches_it_directly():
    from queryview.mcp_server import push_query, push_script

    sid = _session_on("tabs-duck")
    # Arming the parent is the consent for its tabs.
    assert _run(push_script(sid, "SELECT 1", tab="orders"))["message"] == "unknown or inactive session"
    remote.register(sid)
    child = ""
    try:
        r = _run(push_script(sid, "SELECT 1", run=True, tab="orders"))
        assert (r["ok"], r["message"]) == (True, "opening a tab")
        child = r["tab_session"]
        rec = _run(sessions.get_session_rec(child))
        assert rec is not None
        assert (rec.parent, rec.connection_name, rec.connection_by) == (sid, "tabs-duck", "agent")
        assert sessions.display_label(rec).endswith(" › orders")
        # The parent's browser is told to open the tab...
        assert _run(remote.next_message(sid, 1.0)) == {
            "type": "tab",
            "session": child,
            "label": "orders",
            "url": f"/?session={child}&armed=1",
        }
        # ...which arms and collects the parked script.
        remote.register(child)
        assert _run(remote.next_message(child, 1.0)) == {"type": "script", "sql": "SELECT 1", "run": True}
        # A later push to the name reaches the open tab; the parent hears nothing.
        r2 = _run(push_query(sid, "SELECT 2", tab="orders"))
        assert (r2["ok"], r2["message"], r2["tab_session"]) == (True, "delivered", child)
        pushed = _run(remote.next_message(child, 1.0))
        assert pushed is not None and pushed["query"] == "SELECT 2"
        assert _run(remote.next_message(sid, 0.1)) is None
        # A tab can't have tabs.
        assert _run(push_script(child, "SELECT 3", tab="deeper"))["message"] == "a tab can't have tabs"
    finally:
        remote.unregister(sid)
        remote.unregister(child)


def test_a_tab_follows_the_parents_connection_and_sees_its_session_connections():
    from queryview.mcp_server import push_script

    sid = _session_on("tabs-first")
    remote.register(sid)
    try:
        child = _run(push_script(sid, "SELECT 1", tab="orders"))["tab_session"]
        # The agent adds a connection to the parent and moves it there: the tab follows.
        state, _ = _run(add_session_connection(sid, "tabs-added", DuckConfig(":memory:"), "duckdb", "agent"))
        assert state is not None
        assert _run(open_saved(sid, "tabs-added", by="agent"))["ok"]
        assert _run(push_script(sid, "SELECT 2", tab="orders"))["tab_session"] == child
        rec = _run(sessions.get_session_rec(child))
        assert rec is not None and rec.connection_name == "tabs-added"
        assert "tabs-added" in [c["name"] for c in _run(list_connections_for(child))]
    finally:
        remote.unregister(sid)


def test_a_parked_push_is_checked_like_a_delivered_one():
    from queryview.mcp_server import push_query

    sid = _session_on("tabs-check")
    remote.register(sid)
    try:
        r = _run(push_query(sid, "SELECT 1", order_by=[{"bad": 1}], tab="orders"))
        assert r["ok"] is False and "order_by" in r["message"]
        assert _run(remote.next_message(sid, 0.1)) is None  # no tab opened for it
    finally:
        remote.unregister(sid)
