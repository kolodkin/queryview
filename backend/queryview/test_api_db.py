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
    # Reopening goes back to the folder last visited in this session.
    r = c.post("/api/db/open", json={"name": "folder-duck"}).json()
    assert r["database"] == "sub" and r["root"] == root
    # A rebuilt session whose remembered folder vanished falls back to the root.
    assert c.post("/api/db/database", json={"database": "sub"}).json()["ok"]
    shutil.rmtree(tmp_path / "sub")
    connect._sessions.clear()
    assert c.get("/api/session").json()["database"] == "."
    # ...and the row agrees, or the tab would switch back to the vanished folder.
    assert asyncio.run(sessions.get_session_rec(sid)).database == "."


def test_folder_lists_are_cut_at_the_explorer_max_entries(tmp_path):
    for i in range(1, 13):
        (tmp_path / f"f{i:02d}.csv").write_text("id\n1\n")
        (tmp_path / f"d{i:02d}").mkdir()
    sid = asyncio.run(sessions.create_session()).id
    asyncio.run(sessions.patch_session(sid, ui={"explorer": {"maxEntries": 10}}))
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": "duckdb", "name": "cap-duck", "path": str(tmp_path), "session": True}
    r = c.post("/api/db/connect", json=body).json()
    assert r["databases"] == [".", *(f"d{i:02d}" for i in range(1, 11))] and r["databases_truncated"] is True
    assert c.get("/api/session").json()["databases_truncated"] is True
    t = c.get("/api/db/tables").json()
    assert [x["name"] for x in t["tables"]] == [*(f"f{i:02d}.csv" for i in range(1, 11)), "*.csv"]
    assert t["truncated"] is True
    # A value the tab could not have meant falls back to the default 1000.
    asyncio.run(sessions.patch_session(sid, ui={"explorer": {"maxEntries": True}}))
    r = c.get("/api/db/databases").json()
    assert len(r["databases"]) == 13 and r.get("databases_truncated") is None


def test_a_restart_with_the_folder_gone_disconnects_instead_of_creating_a_file(tmp_path):
    root = tmp_path / "exports"
    root.mkdir()
    sid = asyncio.run(sessions.create_session()).id
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": "duckdb", "name": "gone-duck", "path": str(root), "session": True}
    assert c.post("/api/db/connect", json=body).json()["database"] == "."
    shutil.rmtree(root)
    connect._sessions.clear()
    # The row still says ".", but the path is no longer a folder: file mode
    # would create a database file there, so the session reads disconnected.
    assert c.get("/api/session").json()["connected"] is False
    assert c.post("/api/db/execute", json={"sql": "SELECT 1"}).status_code == 409
    assert not root.exists()


def test_folders_past_the_limit_stay_reachable_by_path(tmp_path):
    root = tmp_path / "root"
    for i in range(1, 13):
        (root / f"d{i:02d}").mkdir(parents=True)
    (root / "d12" / "deep").mkdir()
    (root / "d12" / "deep" / "a.csv").write_text("id\n1\n")
    (tmp_path / "outside").mkdir()
    (root / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    sid = asyncio.run(sessions.create_session()).id
    asyncio.run(sessions.patch_session(sid, ui={"explorer": {"maxEntries": 10}}))
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": "duckdb", "name": "keep-duck", "path": str(root), "session": True}
    r = c.post("/api/db/connect", json=body).json()
    assert "d12" not in r["databases"] and r["databases_truncated"] is True

    # A saved query or link can still select d12/deep: it is checked by path.
    r = c.post("/api/db/database", json={"database": "d12/deep"}).json()
    assert r["ok"] and r["databases"] == [".", "d12", "d12/deep"]
    assert [t["name"] for t in c.get("/api/db/tables").json()["tables"]] == ["a.csv"]
    for bad in ("../outside", "link", "d12/../../outside", "d99"):
        assert c.post("/api/db/database", json={"database": bad}).status_code == 400, bad

    # Opening the connection on it works too (an agent's use_connection).
    r = asyncio.run(connect.open_saved(sid, "keep-duck", "d12/deep", by="agent"))
    assert r["ok"] and r["database"] == "d12/deep" and "d12/deep" in r["databases"]
    assert asyncio.run(connect.open_saved(sid, "keep-duck", "d99", by="agent"))["ok"] is False
    assert c.get("/api/session").json()["database"] == "d12/deep"

    # A restart keeps it; one that finds it gone stops at its nearest parent.
    connect._sessions.clear()
    assert c.get("/api/session").json()["database"] == "d12/deep"
    shutil.rmtree(root / "d12" / "deep")
    connect._sessions.clear()
    assert c.get("/api/session").json()["database"] == "d12"
    assert asyncio.run(sessions.get_session_rec(sid)).database == "d12"


def test_reopening_a_folder_connection_goes_back_to_its_last_folder_and_file(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.csv").write_text("id\n1\n")
    sid = asyncio.run(sessions.create_session()).id
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": "duckdb", "name": "lv-folder", "path": str(tmp_path), "session": True}
    assert c.post("/api/db/connect", json=body).json()["ok"]
    assert c.post("/api/db/database", json={"database": "sub"}).json()["ok"]
    assert c.patch(f"/api/sessions/{sid}", json={"table": "c.csv"}).json()["ok"]
    other = {"type": "duckdb", "name": "lv-other", "path": ":memory:", "session": True}
    assert c.post("/api/db/connect", json=other).json()["ok"]
    r = c.post("/api/db/open", json={"name": "lv-folder"}).json()
    assert r["database"] == "sub" and r["table"] == "c.csv"
