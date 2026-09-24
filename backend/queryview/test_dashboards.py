"""Tests for the dashboard store and its REST surface. These don't need a real
ClickHouse: the store is pure SQLite, and route tests exercise validation plus
the persist/push path (the runner's happy/bad ClickHouse paths live in e2e)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from queryview import remote
from queryview.dashboards import (
    _upsert_and_push,
    get_dashboard,
    list_dashboards,
    upsert_dashboard,
)
from queryview.main import app


def _run(coro):
    return asyncio.run(coro)


def test_upsert_creates_then_updates_by_name(default_ws_id):
    _run(upsert_dashboard("d1", "conn-a", "<h1>v1</h1>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    got = _run(get_dashboard("d1", default_ws_id))
    assert got is not None
    assert got["connection"] == "conn-a"
    assert got["html"] == "<h1>v1</h1>"
    assert got["queries"] == {"q": "SELECT 1"}

    _run(upsert_dashboard("d1", "conn-b", "<h1>v2</h1>", {"q": "SELECT 2"}, workspace_id=default_ws_id))
    got = _run(get_dashboard("d1", default_ws_id))
    assert got is not None
    assert got["connection"] == "conn-b"
    assert got["html"] == "<h1>v2</h1>"
    assert got["queries"] == {"q": "SELECT 2"}


def test_get_dashboard_round_trips_queries_dict(default_ws_id):
    queries = {"sales": "SELECT * FROM sales", "users": "SELECT count() FROM users"}
    _run(upsert_dashboard("multi", "c", "<div></div>", queries, workspace_id=default_ws_id))
    got = _run(get_dashboard("multi", default_ws_id))
    assert got is not None
    assert got["queries"] == queries


def test_get_missing_dashboard_is_none(default_ws_id):
    assert _run(get_dashboard("does-not-exist", default_ws_id)) is None


def test_list_dashboards_orders_by_name_and_omits_payload(default_ws_id):
    _run(upsert_dashboard("zeta", "c", "<i></i>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    _run(upsert_dashboard("alpha", "c", "<i></i>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    names = [d["name"] for d in _run(list_dashboards(default_ws_id))]
    assert names.index("alpha") < names.index("zeta")
    row = next(d for d in _run(list_dashboards(default_ws_id)) if d["name"] == "alpha")
    assert set(row) == {"name", "connection", "updated_at"}


def test_upsert_and_push_persists_without_session(default_ws_id):
    persisted, pushed, _ = _run(
        _upsert_and_push("np", "c", "<p></p>", {"q": "SELECT 1"}, None, workspace_id=default_ws_id)
    )
    assert persisted is True and pushed is False
    assert _run(get_dashboard("np", default_ws_id)) is not None


def test_upsert_and_push_delivers_to_registered_session(default_ws_id):
    rid = remote.register(uuid.uuid4().hex)
    try:
        persisted, pushed, _ = _run(
            _upsert_and_push("pushed", "c", "<p>x</p>", {"q": "SELECT 1"}, rid, workspace_id=default_ws_id)
        )
        assert persisted is True and pushed is True
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None
        assert msg["type"] == "dashboard"
        assert msg["name"] == "pushed"
        assert msg["connection"] == "c"
        assert msg["html"] == "<p>x</p>"
        assert msg["queries"] == {"q": "SELECT 1"}
    finally:
        remote.unregister(rid)


# --- REST surface ---------------------------------------------------------


def test_runqueries_requires_connection_and_queries():
    client = TestClient(app)
    assert client.post("/api/runqueries", json={"queries": {"q": "SELECT 1"}}).status_code == 400
    assert client.post("/api/runqueries", json={"connection": "c"}).status_code == 400
    assert client.post("/api/runqueries", json={"connection": "c", "queries": {}}).status_code == 400


def test_runqueries_unknown_connection_returns_404():
    client = TestClient(app)
    r = client.post(
        "/api/runqueries",
        json={"connection": "no-such-connection", "queries": {"q": "SELECT 1"}},
    )
    assert r.status_code == 404
    assert r.json()["ok"] is False
    assert "no connection" in r.json()["message"].lower()


def test_dashboards_upsert_requires_fields():
    client = TestClient(app)
    r = client.post("/api/dashboards", json={"name": "x", "connection": "c"})
    assert r.status_code == 400


def test_dashboards_upsert_persists_and_lists_and_gets():
    client = TestClient(app)
    r = client.post(
        "/api/dashboards",
        json={
            "name": "rest-dash",
            "connection": "c",
            "html": "<h1>hi</h1>",
            "queries": {"q": "SELECT 1"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["persisted"] is True and body["pushed"] is False

    listed = client.get("/api/dashboards").json()["dashboards"]
    assert any(d["name"] == "rest-dash" for d in listed)

    got = client.get("/api/dashboards/rest-dash").json()
    assert got["html"] == "<h1>hi</h1>"
    assert got["queries"] == {"q": "SELECT 1"}


def test_dashboards_get_missing_returns_404():
    client = TestClient(app)
    assert client.get("/api/dashboards/missing-one").status_code == 404


def test_dashboards_upsert_pushes_to_registered_session():
    rid = remote.register(uuid.uuid4().hex)
    try:
        client = TestClient(app)
        r = client.post(
            "/api/dashboards",
            json={
                "session_id": rid,
                "name": "live-dash",
                "connection": "c",
                "html": "<p></p>",
                "queries": {"q": "SELECT 1"},
            },
        )
        assert r.json()["pushed"] is True
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None
        assert msg["type"] == "dashboard" and msg["name"] == "live-dash"
    finally:
        remote.unregister(rid)


def test_mcp_upsert_dashboard_pushes_draft_without_persisting(default_ws_id):
    from queryview.connect import _save_active_connection
    from queryview.drivers.clickhouse import ChConfig
    from queryview.mcp_server import push_dashboard as mcp_push

    _run(_save_active_connection("c", ChConfig("h", 8123, "u", "p"), "clickhouse"))
    rid = remote.register(uuid.uuid4().hex)
    try:
        out = _run(mcp_push(rid, "draftdash", "c", "<p>d</p>", {"q": "SELECT 1"}))
        assert out["pushed"] is True
        # Draft: the agent push must NOT persist — only the user's Save does.
        assert _run(get_dashboard("draftdash", default_ws_id)) is None
        msg = _run(remote.next_message(rid, 1.0))
        assert msg is not None
        assert msg["type"] == "dashboard" and msg["name"] == "draftdash"
    finally:
        remote.unregister(rid)


def test_dashboard_names_distinct_per_workspace(default_ws_id):
    from queryview.workspaces import create_workspace, resolve

    _run(create_workspace("t4-iso"))
    other = _run(resolve("t4-iso")).id
    _run(upsert_dashboard("iso d", "prod", "<html>1</html>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    _run(upsert_dashboard("iso d", "prod", "<html>2</html>", {"q": "SELECT 2"}, workspace_id=other))

    d_default = _run(get_dashboard("iso d", default_ws_id))
    d_other = _run(get_dashboard("iso d", other))
    assert d_default is not None and d_default["html"] == "<html>1</html>"
    assert d_other is not None and d_other["html"] == "<html>2</html>"
    assert "iso d" in [d["name"] for d in _run(list_dashboards(default_ws_id))]
    assert "iso d" in [d["name"] for d in _run(list_dashboards(other))]


def test_mcp_list_dashboards_scopes_by_session_workspace(default_ws_id):
    from queryview.mcp_server import list_dashboards as mcp_list
    from queryview.workspaces import create_workspace, resolve

    _run(create_workspace("t-mcp-ld"))
    other = _run(resolve("t-mcp-ld")).id
    _run(upsert_dashboard("mcp ld", "c", "<i></i>", {}, workspace_id=other))

    # No session_id -> default workspace: the other workspace's dashboard is absent.
    names = [d["name"] for d in _run(mcp_list())["dashboards"]]
    assert "mcp ld" not in names

    # A session on the other workspace sees it. The workspace comes from the
    # session row now, not from the browser reporting it into the channel.
    from queryview import sessions

    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, workspace="t-mcp-ld"))
    remote.register(rec.id)
    try:
        names = [d["name"] for d in _run(mcp_list(session_id=rec.id))["dashboards"]]
        assert names == ["mcp ld"]
    finally:
        remote.unregister(rec.id)
