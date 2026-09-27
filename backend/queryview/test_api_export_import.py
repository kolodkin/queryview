"""The /api/export and /api/import surface: validation 400s, 404s for unknown
entities/workspaces, download headers, and an export -> import round trip."""

from __future__ import annotations

import asyncio

import yaml
from fastapi.testclient import TestClient

from queryview.main import app


def _run(coro):
    return asyncio.run(coro)


def test_export_validation_400():
    c = TestClient(app)
    assert c.get("/api/export").status_code == 400
    assert c.get("/api/export", params={"kind": "nope", "name": "x"}).status_code == 400
    assert c.get("/api/export", params={"kind": "dashboard"}).status_code == 400  # name required
    # queries additionally require conn_type
    assert c.get("/api/export", params={"kind": "query", "name": "x"}).status_code == 400


def test_export_unknown_entity_404():
    c = TestClient(app)
    r = c.get("/api/export", params={"kind": "dashboard", "name": "never saved"})
    assert r.status_code == 404


def test_export_unknown_workspace_404():
    c = TestClient(app)
    r = c.get("/api/export", params={"kind": "workspace", "workspace": "no such ws"})
    assert r.status_code == 404


def test_import_requires_body_and_valid_yaml():
    c = TestClient(app)
    assert c.post("/api/import", content=b"").status_code == 400
    assert c.post("/api/import", content=b"kind: nope\n").status_code == 400


def test_query_export_headers_and_round_trip(default_ws_id):
    from queryview.queries import list_predefined_queries, save_predefined_query

    c = TestClient(app)
    _run(save_predefined_query("api yio", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    r = c.get("/api/export", params={"kind": "query", "name": "api yio", "conn_type": "clickhouse"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="api yio.query.yaml"'
    assert "yaml" in r.headers["content-type"]
    doc = yaml.safe_load(r.text)
    assert doc == {"kind": "query", "type": "clickhouse", "query_name": "api yio", "query": "SELECT 1"}

    # Drift, then import the exported text back over it.
    _run(save_predefined_query("api yio", "clickhouse", "SELECT 2", workspace_id=default_ws_id))
    imp = c.post("/api/import", content=r.text.encode())
    assert imp.json() == {"ok": True, "kind": "query", "queries": 1, "dashboards": 0}
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    assert next(x for x in rows if x["query_name"] == "api yio")["query"] == "SELECT 1"


def test_workspace_export_import_between_workspaces(default_ws_id, wipe_workspace_entities):
    from queryview.dashboards import upsert_dashboard

    c = TestClient(app)
    _run(upsert_dashboard("api ws dash", "<p>v1</p>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    r = c.get("/api/export", params={"kind": "workspace"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="default.workspace.yaml"'

    assert c.post("/api/workspaces", json={"name": "api yio target"}).json() == {"ok": True}
    try:
        imp = c.post("/api/import", params={"workspace": "api yio target"}, content=r.text.encode()).json()
        assert imp["ok"] is True and imp["kind"] == "workspace" and imp["dashboards"] >= 1
        d = c.get("/api/dashboards/api ws dash", params={"workspace": "api yio target"}).json()
        assert d["queries"] == {"q": "SELECT 1"}
    finally:
        # Leave no imported entities behind: wipe the target then delete it.
        from queryview.workspaces import resolve

        wipe_workspace_entities(_run(resolve("api yio target")).id)
        assert c.delete("/api/workspaces/api yio target").json() == {"ok": True}
