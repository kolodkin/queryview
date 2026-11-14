"""The /api/git surface: validation 400s, unconfigured 409, and a store ->
history -> restore round trip against a local bare repo."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from queryview.main import app

# The git_env fixture (bare repo + redirected clone base) lives in conftest.py.


def _run(coro):
    return asyncio.run(coro)


def _default_ws_id() -> int:
    from queryview.workspaces import DEFAULT_WORKSPACE, resolve

    return _run(resolve(DEFAULT_WORKSPACE)).id


def test_status_reports_unconfigured():
    # Outside git_env the default workspace has no remote configured.
    c = TestClient(app)
    assert c.get("/api/git/status").json() == {"configured": False, "conflicts": []}


def test_status_reports_configured(git_env):
    c = TestClient(app)
    assert c.get("/api/git/status").json() == {"configured": True, "conflicts": []}


def test_validation_400():
    c = TestClient(app)
    assert c.post("/api/git/store", json={}).status_code == 400
    assert c.post("/api/git/store", json={"kind": "nope", "name": "x"}).status_code == 400
    assert c.post("/api/git/store", json={"kind": "dashboard"}).status_code == 400  # name required
    # The removed query kind is a bad request on every endpoint, conn_type or not.
    query = {"kind": "query", "name": "x", "conn_type": "clickhouse"}
    for r in (
        c.post("/api/git/store", json=query),
        c.post("/api/git/restore", json=query),
        c.get("/api/git/history", params=query),
    ):
        assert r.status_code == 400
        assert r.json() == {"ok": False, "message": "kind ('dashboard') and name are required"}


def test_store_history_restore_round_trip(git_env):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    c = TestClient(app)
    entity = {"kind": "dashboard", "name": "api rt"}
    _run(upsert_dashboard("api rt", "<p>v1</p>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    r1 = c.post("/api/git/store", json=entity).json()
    assert r1["ok"] is True and r1["committed"] is True
    _run(upsert_dashboard("api rt", "<p>v2</p>", {"q": "SELECT 2"}, workspace_id=_default_ws_id()))
    c.post("/api/git/store", json=entity)

    h = c.get("/api/git/history", params=entity).json()
    assert h["ok"] is True and len(h["revisions"]) == 2 and h["has_more"] is False
    oldest = h["revisions"][-1]["sha"]

    r2 = c.post("/api/git/restore", json={**entity, "ref": oldest}).json()
    assert r2["ok"] is True
    d = _run(get_dashboard("api rt", _default_ws_id()))
    assert d is not None and d["html"] == "<p>v1</p>" and d["queries"] == {"q": "SELECT 1"}


def test_restore_unknown_entity_404(git_env):
    c = TestClient(app)
    r = c.post("/api/git/restore", json={"kind": "dashboard", "name": "never stored api"})
    assert r.status_code == 404


def test_sync_merges_on_demand_and_needs_a_remote():
    c = TestClient(app)
    r = c.post("/api/git/sync", json={})
    assert r.status_code == 409  # the default workspace has no remote here
