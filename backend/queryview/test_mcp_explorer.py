"""MCP open_explorer: switch the database and send the
armed browser to its Explorer page."""

from __future__ import annotations

import pytest

from queryview import connect, mcp_server, remote
from queryview.drivers.base import DatabasesResult
from queryview.mcp_server import open_explorer
from queryview.test_mcp_connections import _connected_session, _run


@pytest.fixture
def rid(monkeypatch, request):
    """An armed session on a connection with database "db" holding table "items"."""

    async def one_db(conn_type, config, limit=1000, current=None):  # DuckDB lists none; fake a picker
        return DatabasesResult(["db"]), None

    async def items(sid):
        return {"ok": True, "tables": [{"name": "items"}]}

    monkeypatch.setattr(connect, "_list_databases", one_db)
    monkeypatch.setattr(mcp_server, "list_tables", items)
    sid = remote.register(_connected_session(request.node.name))
    yield sid
    remote.unregister(sid)


def test_open_explorer_with_table_pushes_the_table(rid):
    assert _run(open_explorer(rid, "db", "items")) == {"ok": True, "message": "delivered", "database": "db"}
    assert _run(remote.next_message(rid, 1.0)) == {"type": "explorer", "table": "items"}


def test_open_explorer_with_table_refuses_a_missing_table(rid):
    out = _run(open_explorer(rid, "db", "nope"))
    assert out == {"ok": False, "message": 'no table "nope" in db', "database": "db"}
    assert _run(remote.next_message(rid, 0.1)) is None


def test_open_explorer_without_a_table(rid):
    assert _run(open_explorer(rid, "db"))["ok"] is True
    assert _run(remote.next_message(rid, 1.0)) == {"type": "explorer", "table": None}
    assert _run(open_explorer(rid, "no_such_db"))["message"] == "unknown database"


def test_open_explorer_with_table_trusts_a_truncated_list(rid, monkeypatch):
    async def truncated(sid):
        return {"ok": True, "tables": [{"name": "items"}], "truncated": True}

    monkeypatch.setattr(mcp_server, "list_tables", truncated)
    assert _run(open_explorer(rid, "db", "past_the_cap"))["ok"] is True
    assert _run(remote.next_message(rid, 1.0)) == {"type": "explorer", "table": "past_the_cap"}
