"""new_tab gives the agent a session of its own and its link; pushes to it
queue until the browser tab arms (docs/remote.md#tabs)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from starlette.datastructures import URL

from queryview import remote, sessions
from queryview.connect import open_saved
from queryview.test_mcp_connections import _connected_session


def _run(coro):
    return asyncio.run(coro)


def _ctx(url: str) -> Any:
    """What the tool reads off the MCP request: where the client reached us."""
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(url=URL(url))))


def test_new_tab_links_a_session_that_collects_pushes_once_it_arms():
    from queryview.mcp_server import new_tab, push_script

    assert _run(new_tab(" ", _ctx("http://localhost:5555/mcp/"))) == {"ok": False, "message": "name required"}
    r = _run(new_tab("orders", _ctx("http://localhost:5555/mcp/")))
    sid = r["session_id"]
    assert r == {"ok": True, "session_id": sid, "url": f"http://localhost:5555/?session={sid}"}
    rec = _run(sessions.get_session_rec(sid))
    assert rec is not None and sessions.display_label(rec) == "Agent › orders"
    try:
        # The agent connects the tab and pushes before the browser tab has loaded.
        _connected_session("tabs-duck")  # saves the connection
        assert _run(open_saved(sid, "tabs-duck", by="agent"))["ok"]
        pushed = _run(push_script(sid, "SELECT 1", run=True))
        assert (pushed["ok"], pushed["message"], pushed["url"]) == (True, "queued for the tab", r["url"])
        # The browser tab arms and finds the script queued.
        remote.register(sid)
        assert _run(remote.next_message(sid, 1.0)) == {"type": "script", "sql": "SELECT 1", "run": True}
        assert _run(push_script(sid, "SELECT 2"))["message"] == "delivered"
    finally:
        remote.unregister(sid)
