"""The /api/db surface: unknown type is a 400; validation errors are 400;
the old /api/clickhouse paths are gone (404)."""

from __future__ import annotations

from fastapi.testclient import TestClient

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


def test_tables_without_session_is_409():
    c = TestClient(app)
    # Disconnect first: it marks this cookie disconnected, so the auto-reconnect
    # of a connection saved by an earlier test can't turn this into a 200.
    c.post("/api/db/disconnect")
    r = c.get("/api/db/tables")
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_execute_requires_sql():
    c = TestClient(app)
    r = c.post("/api/db/execute", json={"sql": "   "})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_execute_without_session_is_409():
    c = TestClient(app)
    c.post("/api/db/disconnect")
    r = c.post("/api/db/execute", json={"sql": "SELECT 1"})
    assert r.status_code == 409


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
