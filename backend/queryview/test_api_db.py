"""The /api/db and /api/runqueries routes through the app: validation and the
session gate, script execution, session-only and folder connections, the
session query timeout, and parameter substitution."""

from __future__ import annotations

import asyncio
import shutil

import pytest
from fastapi.testclient import TestClient

from queryview import connect, sessions
from queryview.conftest import app


def _row(sid: str) -> sessions.SessionRec:
    """The session's stored record, which these tests require to exist."""
    rec = asyncio.run(sessions.get_session_rec(sid))
    assert rec is not None
    return rec


def test_connect_unknown_type_is_400():
    c = TestClient(app)
    r = c.post("/api/db/connect", json={"type": "nope", "name": "x", "host": "h", "port": 1})
    assert r.status_code == 400
    assert "unknown" in r.json()["message"].lower()


def test_connect_validation_error_is_400():
    c = TestClient(app)
    r = c.post("/api/db/connect", json={"type": "clickhouse", "name": "x"})  # no host
    assert r.status_code == 400


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
    # Disconnect first: it marks this session disconnected, so the auto-reconnect
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


# req: architecture/api/session-scoped-api
def test_session_only_connect_lists_for_its_session_only():
    c = TestClient(app, headers={"X-QV-Session": "session-only-test"})
    other = TestClient(app, headers={"X-QV-Session": "session-only-other"})
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": "so-duck", "path": ":memory:", "session": True})
    assert r.json()["ok"], r.text
    assert c.get("/api/session").json()["scope"] == "session"
    mine = {x["name"]: x for x in c.get("/api/db/connections").json()["connections"]}
    assert mine["so-duck"]["scope"] == "session" and mine["so-duck"]["created_by"] == "user"
    assert "so-duck" not in {x["name"] for x in other.get("/api/db/connections").json()["connections"]}


# req: architecture/api/session-scoped-api
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
    assert _row(sid).database == "."
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
    assert _row(sid).database == "."


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

    # A saved dashboard or link can still select d12/deep: it is checked by path.
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
    assert _row(sid).database == "d12"


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


@pytest.mark.parametrize("driver", ["sqlite", "duckdb"])
def test_reopening_a_picker_less_connection_goes_back_to_its_last_table(tmp_path, driver):
    # SQLite and a DuckDB file have no database: last visited holds the table only.
    import sqlite3

    import duckdb

    path = str(tmp_path / f"lv.{driver}")
    con = sqlite3.connect(path) if driver == "sqlite" else duckdb.connect(path)
    con.execute("CREATE TABLE orders (id INTEGER)")
    con.execute("CREATE TABLE refunds (id INTEGER)")
    con.commit()
    con.close()
    sid = asyncio.run(sessions.create_session()).id
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": driver, "name": f"lv-{driver}", "path": path, "session": True}
    assert c.post("/api/db/connect", json=body).json()["ok"]
    assert c.patch(f"/api/sessions/{sid}", json={"table": "refunds"}).json()["ok"]
    other = {"type": "duckdb", "name": f"lv-{driver}-other", "path": ":memory:", "session": True}
    assert c.post("/api/db/connect", json=other).json()["ok"]
    r = c.post("/api/db/open", json={"name": f"lv-{driver}"}).json()
    assert r["ok"] and r["database"] is None and r["table"] == "refunds"
    assert c.get("/api/session").json()["table"] == "refunds"


# req: architecture/api/session-scoped-api
def test_requests_run_within_the_session_query_timeout(monkeypatch, tmp_path):
    """The **Timeout** chip's value in the session's `ui` blob reaches the
    driver on the connect probe and on each query; a value the chip could not
    have written falls back to the default 30."""
    from queryview.drivers import DRIVERS
    from queryview.drivers.base import Column, DatabasesResult, QueryRows, RowsResult, query_timeout

    seen = []
    driver = DRIVERS["duckdb"]

    async def list_databases(config, limit=1000, current=None):
        seen.append(("list", query_timeout.get()))
        return DatabasesResult(databases=[])

    async def run_query(config, sql, database, limit, offset, order_by):
        seen.append(("query", query_timeout.get()))
        return RowsResult(QueryRows(meta=[Column("x", "INTEGER")], data=[[1]]))

    async def test(config):
        seen.append(("test", query_timeout.get()))
        return {"ok": True}

    monkeypatch.setattr(driver, "list_databases", list_databases)
    monkeypatch.setattr(driver, "run_query", run_query)
    monkeypatch.setattr(driver, "test", test)
    sid = asyncio.run(sessions.create_session()).id
    asyncio.run(sessions.patch_session(sid, ui={"app": {"queryTimeout": 45}}))
    c = TestClient(app, headers={"X-QV-Session": sid})
    body = {"type": "duckdb", "name": "timed-duck", "path": str(tmp_path / "t.duckdb"), "session": True}
    assert c.post("/api/db/test", json=body).json()["ok"] is True
    assert c.post("/api/db/connect", json=body).json()["ok"] is True
    assert c.post("/api/db/query", json={"query": "SELECT 1", "limit": 1, "offset": 0}).json()["ok"] is True
    for bad in (True, 0, 601, "45"):
        asyncio.run(sessions.patch_session(sid, ui={"app": {"queryTimeout": bad}}))
        assert c.post("/api/db/query", json={"query": "SELECT 1", "limit": 1, "offset": 0}).json()["ok"] is True
    assert seen == [("test", 45), ("list", 45), ("query", 45), *[("query", 30)] * 4]


# --- Dashboard params: substituted here, not in the browser (docs/system/dashboard.md#dashboard-parameters) ---

REGION = [{"name": "r", "options": ["eu", "us"]}]


def _duck(tmp_path, sid: str) -> TestClient:
    c = TestClient(app, headers={"X-QV-Session": sid})
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": sid, "path": str(tmp_path / f"{sid}.duckdb")})
    assert r.json()["ok"], r.text
    # A query opens the file read-only, so it must exist first.
    assert c.post("/api/db/execute", json={"sql": "CREATE TABLE t (id INTEGER)"}).json()["ok"]
    return c


def test_runqueries_with_params_returns_resolved_params(tmp_path):
    c = _duck(tmp_path, "params-run")
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT {r} AS v"}, "params": REGION, "values": {"r": "us"}})
    assert r.status_code == 200, r.text
    assert r.json()["results"] == {"q": {"v": ["us"]}}
    assert r.json()["params"] == [{"name": "r", "kind": "value", "options": ["eu", "us"], "value": "us"}]


def test_runqueries_with_params_allows_no_queries(tmp_path):
    c = _duck(tmp_path, "params-empty")
    r = c.post("/api/runqueries", json={"queries": {}, "params": REGION})
    assert r.status_code == 200, r.text
    assert r.json()["results"] == {} and r.json()["params"][0]["value"] == "eu"


def test_runqueries_without_params_is_unchanged(tmp_path):
    c = _duck(tmp_path, "params-none")
    assert c.post("/api/runqueries", json={"queries": {}}).status_code == 400
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT '{r}' AS v"}})
    assert r.json()["results"] == {"q": {"v": ["{r}"]}} and "params" not in r.json()


def test_runqueries_bad_param_is_a_400_and_a_failing_query_keeps_the_selectors(tmp_path):
    c = _duck(tmp_path, "params-bad")
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT {r:nope}"}, "params": REGION})
    assert r.status_code == 400 and r.json()["message"] == "unknown cast for {r}: nope"
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT nope_col, {r}"}, "params": REGION})
    assert r.status_code == 400 and r.json()["params"][0]["value"] == "eu"


def test_runqueries_names_a_malformed_param_and_still_runs(tmp_path):
    c = _duck(tmp_path, "params-malformed")
    params = [{"name": "bad", "kind": "dropdown", "options": ["a"]}, *REGION]
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT {r} AS v"}, "params": params})
    assert r.status_code == 200, r.text
    assert r.json()["results"] == {"q": {"v": ["eu"]}}
    assert r.json()["warning"] == "invalid params[0] 'bad' kind must be one of value, identifier, dimension, text, each"
    # A failing query carries it too: the SQL error alone would not point at the param.
    r = c.post("/api/runqueries", json={"queries": {"q": "SELECT {bad}"}, "params": params})
    assert r.status_code == 400 and r.json()["warning"].startswith("invalid params[0]")
    assert "warning" not in c.post("/api/runqueries", json={"queries": {}, "params": REGION}).json()
    # Every dropped entry is named; one reading keeps is not, though saving would refuse it.
    two = [{"name": "a", "kind": "x"}, {"name": "b", "kind": "y"}, {"name": "kept", "options": ["v"], "default": "v"}]
    warning = c.post("/api/runqueries", json={"queries": {}, "params": two}).json()["warning"]
    assert "params[0] 'a'" in warning and "params[1] 'b'" in warning and "kept" not in warning


def test_db_query_substitutes_values(tmp_path):
    c = _duck(tmp_path, "params-query")
    r = c.post("/api/db/query", json={"query": "SELECT {r} AS v", "params": REGION, "values": {"r": "eu"}})
    assert r.status_code == 200 and r.json()["data"] == [["eu"]], r.text
    r = c.post(
        "/api/db/query", json={"query": "SELECT {r} AS v", "params": REGION, "values": {"r": "eu"}, "format": "csv"}
    )
    assert r.json()["output"].splitlines() == ["v", "eu"]


def test_db_query_waits_for_a_choice(tmp_path):
    c = _duck(tmp_path, "params-wait")
    r = c.post("/api/db/query", json={"query": "SELECT {r} AS v", "params": REGION, "values": {}})
    assert r.status_code == 400 and r.json() == {"ok": False, "message": "Waiting for a parameter choice."}


def test_db_describe_substitutes_values(tmp_path):
    c = _duck(tmp_path, "params-describe")
    r = c.post("/api/db/describe", json={"query": "SELECT {r} AS v", "params": REGION, "values": {"r": "eu"}})
    assert r.status_code == 200 and [f["name"] for f in r.json()["fields"]] == ["v"], r.text


def test_a_bad_value_is_a_400(tmp_path):
    c = _duck(tmp_path, "params-ident")
    body = {"query": "SELECT {r:identifier}", "params": REGION, "values": {"r": 'a"b'}}
    for path in ("/api/db/query", "/api/db/describe"):
        r = c.post(path, json=body)
        assert r.status_code == 400 and r.json()["message"] == 'invalid identifier for {r}: a"b'


def test_a_query_with_params_still_needs_a_session():
    r = TestClient(app).post("/api/db/query", json={"query": "SELECT {r}", "params": REGION, "values": {"r": "eu"}})
    assert r.status_code == 409
