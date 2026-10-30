"""The /api/db surface: unknown type is a 400; validation errors are 400;
the old /api/clickhouse paths are gone (404)."""

from __future__ import annotations

import asyncio
import shutil

import pytest
from fastapi.testclient import TestClient

from queryview import connect, sessions
from queryview.main import app


def test_connect_unknown_type_is_400():
    c = TestClient(app)
    r = c.post("/api/db/connect", json={"type": "nope", "name": "x", "host": "h", "port": 1})
    assert r.status_code == 400
    assert "unknown" in r.json()["message"].lower()


def test_connect_validation_error_is_400():
    c = TestClient(app)
    r = c.post("/api/db/connect", json={"type": "clickhouse", "name": "x"})  # no host
    assert r.status_code == 400


def test_predefined_query_save_rejects_malformed_cell_view():
    c = TestClient(app)
    body = {"query_name": "cv bad", "type": "clickhouse", "query": "SELECT 1"}
    r = c.post("/api/predefined-queries", json={**body, "cell_view": "col: [unclosed"})
    assert r.status_code == 400 and "invalid cell_view" in r.json()["message"]
    # A non-string cell_view is rejected, not silently dropped.
    r = c.post("/api/predefined-queries", json={**body, "cell_view": {"col": {"type": "link"}}})
    assert r.status_code == 400
    # The valid shape still saves.
    ok = c.post(
        "/api/predefined-queries", json={**body, "cell_view": "col:\n  type: link\n  value: https://x/{cell}\n"}
    )
    assert ok.json() == {"ok": True}


def test_old_clickhouse_path_is_gone():
    c = TestClient(app)
    assert c.post("/api/clickhouse/connect", json={}).status_code == 404


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/db/tables", None),
        ("GET", "/api/db/databases", None),
        ("POST", "/api/db/execute", {"sql": "SELECT 1"}),
    ],
)
def test_gated_routes_without_session_are_409(method, path, body):
    c = TestClient(app)
    # Disconnect first: it marks this cookie disconnected, so the auto-reconnect
    # of a connection saved by an earlier test can't turn this into a 200.
    c.post("/api/db/disconnect")
    r = c.request(method, path, json=body)
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_execute_requires_sql():
    c = TestClient(app)
    r = c.post("/api/db/execute", json={"sql": "   "})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_execute_runs_a_script_per_statement(tmp_path):
    c = TestClient(app, headers={"X-QV-Session": "exec-script-test"})
    path = str(tmp_path / "exec.duckdb")
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": "exec-duck", "path": path})
    assert r.json()["ok"], r.text
    r = c.post(
        "/api/db/execute",
        json={
            "sql": "CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (1), (2); SELECT id FROM t ORDER BY id; SELECT nope"
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    results = body["results"]
    assert [x["ok"] for x in results] == [True, True, True, False]
    assert results[0]["status"] == "OK" and results[0]["meta"] is None
    assert results[2]["meta"] == [{"name": "id", "type": "INTEGER"}]
    assert results[2]["data"] == [[1], [2]] and results[2]["truncated"] is False
    assert "nope" in results[3]["message"]
    assert all(isinstance(x["elapsed_ms"], int) for x in results)


def test_session_only_connect_lists_for_its_session_only():
    c = TestClient(app, headers={"X-QV-Session": "session-only-test"})
    other = TestClient(app, headers={"X-QV-Session": "session-only-other"})
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": "so-duck", "path": ":memory:", "session": True})
    assert r.json()["ok"], r.text
    assert c.get("/api/session").json()["scope"] == "session"
    mine = {x["name"]: x for x in c.get("/api/db/connections").json()["connections"]}
    assert mine["so-duck"]["scope"] == "session" and mine["so-duck"]["created_by"] == "user"
    assert "so-duck" not in {x["name"] for x in other.get("/api/db/connections").json()["connections"]}


def test_folder_connection_lands_on_root_with_tables_and_union(tmp_path):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("id\n1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.csv").write_text("id\n1\n")
    root = str(tmp_path)
    # A real session row, so the rebuild at the end has something to rebuild from.
    sid = asyncio.run(sessions.create_session()).id
    c = TestClient(app, headers={"X-QV-Session": sid})
    # Session-only: a saved connection would join every later test's MCP listing.
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": "folder-duck", "path": root, "session": True}).json()
    assert r["ok"], r
    assert r["databases"] == [".", "sub"] and r["database"] == "." and r["root"] == root
    assert c.get("/api/session").json()["root"] == root
    # The default is persisted: the tab re-derives its connection from the session row.
    assert asyncio.run(sessions.get_session_rec(sid)).database == "."
    names = [t["name"] for t in c.get("/api/db/tables").json()["tables"]]
    assert names == ["a.csv", "b.csv", "*.csv"]
    glob = c.get("/api/db/tables", params={"union": "1"}).json()["tables"][-1]
    assert glob["query"] == "SELECT * FROM read_csv(['a.csv', 'b.csv'], union_by_name = true)"
    assert c.post("/api/db/database", json={"database": "sub"}).json()["ok"]
    assert [t["name"] for t in c.get("/api/db/tables").json()["tables"]] == ["c.csv"]
    # Reopening resets to the root, as opening any connection resets its database.
    r = c.post("/api/db/open", json={"name": "folder-duck"}).json()
    assert r["database"] == "." and r["root"] == root
    # A rebuilt session whose remembered folder vanished falls back to the root.
    assert c.post("/api/db/database", json={"database": "sub"}).json()["ok"]
    shutil.rmtree(tmp_path / "sub")
    connect._sessions.clear()
    assert c.get("/api/session").json()["database"] == "."
    # ...and the row agrees, or the tab would switch back to the vanished folder.
    assert asyncio.run(sessions.get_session_rec(sid)).database == "."
