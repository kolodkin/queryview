"""The viewer server's API (docs/system/viewer_server.md): display only. It takes names and
values, never SQL, and none of the app's routes exist."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from queryview import serving
from queryview.drivers.sqlite import SqliteDriver
from queryview.gitsync import GitSyncError, dashboard_reldir
from queryview.server.config import ServerConfig, load_config
from queryview.server.main import create_app
from queryview.server.repo import Repo

SALES = {
    "name": "sales",
    "html": '<qv-select-view query="rows"></qv-select-view>',
    "queries": {
        "total": "SELECT sum(amount) AS t FROM orders WHERE region = {region}",
        "rows": "SELECT * FROM orders ORDER BY {col}",
    },
    "params": [
        {"name": "region", "options_sql": "SELECT DISTINCT region FROM orders ORDER BY 1"},
        {"name": "col", "kind": "identifier", "options": ["amount", "region"]},
    ],
}
ON_SALES = {"connection": "local", "dashboard": "sales"}


def _config(tmp_path, dash_repo) -> ServerConfig:
    db = tmp_path / "local.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE orders (region TEXT, amount INTEGER)")
        con.executemany("INSERT INTO orders VALUES (?, ?)", [("eu", 10), ("us", 20)])
    gone = tmp_path / "gone.sqlite"
    sqlite3.connect(gone).close()
    path = tmp_path / "server.yaml"
    path.write_text(
        f"git: {{remote: {dash_repo.remote}}}\n"
        "connections:\n"
        f"  - {{name: local, type: sqlite, path: {db}}}\n"
        f"  - {{name: gone, type: sqlite, path: {gone}}}\n"
    )
    return load_config(path)


@pytest.fixture
def client(tmp_path, dash_repo):
    dash_repo.commit([SALES])
    with TestClient(create_app(_config(tmp_path, dash_repo))) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


# req: architecture/viewer_server_api/names-not-sql
def test_connections_list_names_and_types_only(client):
    assert client.get("/api/connections").json() == [
        {"name": "local", "type": "sqlite"},
        {"name": "gone", "type": "sqlite"},
    ]


def test_dashboards_list_names(client):
    assert client.get("/api/dashboards").json() == [{"name": "sales"}]


# req: architecture/viewer_server_api/names-not-sql
def test_a_dashboard_carries_no_sql(client):
    r = client.get("/api/dashboards/sales")
    assert r.json() == {"name": "sales", "html": SALES["html"], "queries": ["total", "rows"]}
    assert "SELECT" not in r.text and "options_sql" not in r.text


def test_run_resolves_and_runs(client):
    r = client.post("/api/run", json={**ON_SALES, "values": {}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["results"]["total"] == {"t": [10]}
    assert body["params"] == [
        {"name": "region", "kind": "value", "options": ["eu", "us"], "value": "eu"},
        {"name": "col", "kind": "identifier", "options": ["amount", "region"], "value": "amount"},
    ]
    assert "SELECT" not in r.text


def test_run_takes_a_chosen_value(client):
    r = client.post("/api/run", json={**ON_SALES, "values": {"region": "us"}})
    assert r.json()["results"]["total"] == {"t": [20]}


def test_run_only_the_named_queries(client):
    r = client.post("/api/run", json={**ON_SALES, "queries": ["total"]})
    assert set(r.json()["results"]) == {"total"}
    r = client.post("/api/run", json={**ON_SALES, "queries": []})
    assert r.json()["results"] == {} and len(r.json()["params"]) == 2


# req: architecture/viewer_server_api/values-checked
def test_a_value_outside_the_options_never_reaches_the_sql(client):
    hostile = {"col": 'amount" FROM orders; --', "region": "' OR 1=1 --"}
    r = client.post("/api/query", json={**ON_SALES, "query": "rows", "values": hostile})
    assert r.status_code == 200, r.text
    assert r.json()["data"] == [["eu", 10], ["us", 20]]  # sorted by the default option, amount
    r = client.post("/api/run", json={**ON_SALES, "queries": ["total"], "values": hostile})
    assert r.json()["results"]["total"] == {"t": [10]}  # the default region, eu


def test_query_pages_and_sorts(client):
    body = {**ON_SALES, "query": "rows", "limit": 1, "order_by": [{"name": "amount", "dir": "DESC"}]}
    r = client.post("/api/query", json=body)
    assert r.json() == {"ok": True, "meta": r.json()["meta"], "data": [["us", 20]]}
    assert [m["name"] for m in r.json()["meta"]] == ["region", "amount"]
    assert client.post("/api/query", json={**body, "offset": 1}).json()["data"] == [["eu", 10]]


def test_a_hostile_order_by_name_is_refused(client):
    body = {**ON_SALES, "query": "rows", "order_by": [{"name": 'amount" DESC, (SELECT 1) -- ', "dir": "ASC"}]}
    r = client.post("/api/query", json=body)
    assert r.status_code == 400 and "cannot sort by" in r.json()["message"]


def test_query_csv(client):
    r = client.post("/api/query", json={**ON_SALES, "query": "rows", "format": "csv"})
    assert r.json()["output"].splitlines() == ["region,amount", "eu,10", "us,20"]


def test_describe(client):
    r = client.post("/api/describe", json={**ON_SALES, "query": "rows"})
    assert r.status_code == 200 and [f["name"] for f in r.json()["fields"]] == ["region", "amount"]


# req: architecture/viewer_server_api/names-not-sql
@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/run", {**ON_SALES, "connection": "nope"}),
        ("/api/run", {**ON_SALES, "dashboard": "nope"}),
        ("/api/run", {**ON_SALES, "queries": ["nope"]}),
        ("/api/query", {**ON_SALES, "query": "nope"}),
        ("/api/query", {**ON_SALES, "connection": "nope", "query": "rows"}),
        ("/api/describe", {**ON_SALES, "query": "nope"}),
        ("/api/describe", {**ON_SALES, "dashboard": "nope", "query": "rows"}),
    ],
)
def test_unknown_names_are_404(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 404 and r.json()["ok"] is False


def test_an_unknown_dashboard_is_404(client):
    assert client.get("/api/dashboards/nope").status_code == 404


@pytest.mark.parametrize("values", [None, [1], "x", {"region": 5}, {"region": None}, {"region": ["eu"]}, {5: "x"}])
@pytest.mark.parametrize("path", ["/api/run", "/api/query", "/api/describe"])
def test_hostile_values_are_not_a_500(client, path, values):
    r = client.post(path, json={**ON_SALES, "query": "total", "values": values})
    assert r.status_code == 200, r.text  # dropped: the defaults run


@pytest.mark.parametrize(
    "body",
    [
        {**ON_SALES, "queries": "total"},
        {**ON_SALES, "queries": [1]},
        {**ON_SALES, "queries": [["total"]]},
        {"connection": ["local"], "dashboard": "sales"},
        {"connection": "local", "dashboard": {"a": 1}},
        [1],
        "x",
    ],
)
def test_a_malformed_body_is_a_4xx(client, body):
    assert client.post("/api/run", json=body).status_code in (400, 404)


@pytest.mark.parametrize("path", ["/api/run", "/api/query", "/api/describe"])
def test_a_non_json_body_is_a_400(client, path):
    r = client.post(path, content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False


@pytest.mark.parametrize("limit, offset", [("x", "y"), (-1, -1), (10**9, 0), (None, None), ([1], {})])
def test_odd_paging_is_clamped(client, limit, offset):
    r = client.post("/api/query", json={**ON_SALES, "query": "rows", "limit": limit, "offset": offset})
    assert r.status_code == 200 and len(r.json()["data"]) >= 1


def test_a_failing_query_is_a_400_with_the_drivers_message(client, dash_repo):
    dash_repo.commit([{**SALES, "queries": {"total": "SELECT nope FROM orders", "rows": "SELECT nope"}}])
    asyncio.run(client.app.state.repo.refresh())
    r = client.post("/api/run", json=ON_SALES)
    assert r.status_code == 400 and r.json()["message"].startswith("total: ") and "nope" in r.json()["message"]
    assert len(r.json()["params"]) == 2  # the page keeps its selectors
    r = client.post("/api/query", json={**ON_SALES, "query": "rows"})
    assert r.status_code == 400 and "nope" in r.json()["message"]


def test_a_query_waiting_on_a_choice(client, dash_repo):
    params = [{"name": "region", "options": ["eu", "us"], "default": "none"}, SALES["params"][1]]
    dash_repo.commit([{**SALES, "params": params}])
    asyncio.run(client.app.state.repo.refresh())
    assert client.post("/api/run", json=ON_SALES).json()["results"] == {
        "rows": client.post("/api/run", json={**ON_SALES, "queries": ["rows"]}).json()["results"]["rows"]
    }
    r = client.post("/api/query", json={**ON_SALES, "query": "total"})
    assert r.status_code == 400 and r.json()["message"] == "Waiting for a parameter choice."
    assert client.post("/api/describe", json={**ON_SALES, "query": "total"}).status_code == 400
    r = client.post("/api/query", json={**ON_SALES, "query": "total", "values": {"region": "us"}})
    assert r.json()["data"] == [[20]]


def test_a_dashboard_removed_from_the_repo_is_a_404(client, dash_repo):
    dash_repo.commit(remove=["sales"])
    asyncio.run(client.app.state.repo.refresh())
    assert client.post("/api/run", json=ON_SALES).status_code == 404
    assert client.get("/api/dashboards").json() == []


def test_a_failing_database_does_not_stop_the_server(client, tmp_path):
    (tmp_path / "gone.sqlite").unlink()
    r = client.post("/api/run", json={**ON_SALES, "connection": "gone"})
    assert r.status_code == 400 and r.json()["ok"] is False and r.json()["message"]
    assert client.post("/api/run", json=ON_SALES).status_code == 200


# req: architecture/viewer_server_api/names-not-sql
@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/api/db/query"),
        ("POST", "/api/db/execute"),
        ("POST", "/api/db/connect"),
        ("POST", "/api/runqueries"),
        ("POST", "/api/dashboards"),
        ("DELETE", "/api/dashboards/sales"),
        ("POST", "/api/git/sync"),
        ("GET", "/api/session"),
        ("GET", "/mcp/"),
        ("POST", "/mcp/"),
        ("GET", "/dashboard"),
    ],
)
def test_no_app_routes_exist(client, method, path):
    r = client.request(method, path, json={"query": "SELECT 1", "sql": "SELECT 1", "queries": {"q": "SELECT 1"}})
    assert r.status_code in (404, 405)


def test_serves_the_viewer_page_at_the_root(client, tmp_path, monkeypatch):
    (tmp_path / "viewer.html").write_text("<!doctype html><title>viewer</title>")
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / "widgets.js").write_text("// bundle")
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path))
    serving.static_root.cache_clear()
    try:
        assert "viewer" in client.get("/").text
        assert client.get("/widgets.js").text == "// bundle"
        assert client.get("/gone.js").status_code == 404
    finally:
        serving.static_root.cache_clear()


def test_startup_fails_when_the_clone_fails(tmp_path, dash_repo):
    config = _config(tmp_path, dash_repo)
    broken = ServerConfig(str(tmp_path / "missing.git"), "main", 60, config.connections)
    with pytest.raises(GitSyncError):
        with TestClient(create_app(broken)):
            pass


def test_a_new_commit_shows_within_the_sync_interval(tmp_path, dash_repo):
    dash_repo.commit([SALES])
    config = _config(tmp_path, dash_repo)
    fast = ServerConfig(config.remote, config.branch, 0.05, config.connections)
    with TestClient(create_app(fast)) as c:
        dash_repo.commit([{**SALES, "name": "ops"}])
        for _ in range(100):
            if len(c.get("/api/dashboards").json()) == 2:
                break
            time.sleep(0.05)  # the poll runs on the app's own thread
        assert c.get("/api/dashboards").json() == [{"name": "ops"}, {"name": "sales"}]


def test_a_failed_fetch_keeps_serving(tmp_path, dash_repo):
    dash_repo.commit([SALES])
    config = _config(tmp_path, dash_repo)
    fast = ServerConfig(config.remote, config.branch, 0.05, config.connections)
    with TestClient(create_app(fast)) as c:
        dash_repo.remote.rename(tmp_path / "moved.git")
        time.sleep(0.3)  # several failed fetches, on the app's own thread
        assert c.get("/api/dashboards").json() == [{"name": "sales"}]
        assert c.post("/api/run", json=ON_SALES).status_code == 200


# --- Review fixes ------------------------------------------------------------

NOTES = {
    "name": "notes",
    "html": "<p>notes</p>",
    "queries": {"echo": "SELECT {note} AS v, {region} AS g FROM orders ORDER BY amount"},
    "params": [{"name": "note", "kind": "text", "default": "hi"}, {"name": "region", "kind": "dimension"}],
}
ON_NOTES = {"connection": "local", "dashboard": "notes"}


def _show(client, dash_repo, *dashboards):
    dash_repo.commit(list(dashboards))
    asyncio.run(client.app.state.repo.refresh())


def test_text_and_dimension_params_run(client, dash_repo):
    _show(client, dash_repo, NOTES)
    r = client.post("/api/run", json=ON_NOTES)
    assert r.json()["results"]["echo"] == {"v": ["hi", "hi"], "g": ["", ""]}
    r = client.post("/api/run", json={**ON_NOTES, "values": {"note": "o'k; --", "region": "on"}})
    assert r.json()["results"]["echo"] == {"v": ["o'k; --", "o'k; --"], "g": ["eu", "us"]}


@pytest.mark.parametrize("path", ["/api/run", "/api/query", "/api/describe"])
@pytest.mark.parametrize("values", [{"note": "\ud800"}, {"region": "\udfff"}, {"note": "a\ud800b", "region": "on"}])
def test_text_that_cannot_be_encoded_is_not_a_500(client, dash_repo, path, values):
    _show(client, dash_repo, NOTES)
    # Sent as JSON's own \\ud800 escape: the client cannot encode the character itself.
    body = json.dumps({**ON_NOTES, "query": "echo", "values": values})
    r = client.post(path, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200, r.text  # dropped: the default runs


# req: architecture/viewer_server_api/values-checked
def test_a_param_declared_twice_cannot_slip_a_value_past_its_options(client, dash_repo):
    twice = [{"name": "col", "kind": "text"}, {"name": "col", "kind": "identifier", "options": ["amount"]}]
    dup = {"name": "dup", "html": "<p>dup</p>", "queries": {"q": "SELECT {col} AS v FROM orders"}, "params": twice}
    _show(client, dash_repo, dup)
    r = client.post(
        "/api/query", json={"connection": "local", "dashboard": "dup", "query": "q", "values": {"col": "region"}}
    )
    # Either the dashboard is refused, or the value stays a string: never the region column.
    assert r.status_code == 404 or r.json()["data"] == [["region"], ["region"]], r.text
    assert "eu" not in r.text


def test_an_unknown_dashboard_names_it(client):
    r = client.post("/api/run", json={**ON_SALES, "dashboard": "gone"})
    assert r.status_code == 404 and r.json()["message"] == "Dashboard “gone” not found."
    assert client.get("/api/dashboards/gone").json()["message"] == "Dashboard “gone” not found."


def test_an_unexpected_sync_error_does_not_stop_polling(tmp_path, dash_repo, monkeypatch):
    dash_repo.commit([SALES])
    config = _config(tmp_path, dash_repo)
    real, calls = Repo.refresh, {"n": 0}

    async def flaky(self):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return await real(self)

    monkeypatch.setattr(Repo, "refresh", flaky)
    with TestClient(create_app(ServerConfig(config.remote, config.branch, 0.05, config.connections))) as c:
        dash_repo.commit([{**SALES, "name": "ops"}])
        for _ in range(100):
            if len(c.get("/api/dashboards").json()) == 2:
                break
            time.sleep(0.05)  # the poll runs on the app's own thread
        assert calls["n"] > 2 and len(c.get("/api/dashboards").json()) == 2


def test_a_widget_page_runs_only_the_options_its_query_needs(client, dash_repo, monkeypatch):
    by = {"name": "by", "options_sql": "SELECT DISTINCT region FROM orders ORDER BY 1"}
    unused = {"name": "unused", "options_sql": "SELECT DISTINCT amount FROM orders ORDER BY 1"}
    queries = {"rows": "SELECT * FROM orders WHERE region = {by}", "plain": "SELECT * FROM orders"}
    wide = {"name": "wide", "html": "<p>wide</p>", "queries": queries, "params": [by, unused]}
    _show(client, dash_repo, wide)
    ran: list[str] = []
    run_query = SqliteDriver.run_query

    async def counted(self, config, sql, *args, **kwargs):
        ran.append(sql)
        return await run_query(self, config, sql, *args, **kwargs)

    monkeypatch.setattr(SqliteDriver, "run_query", counted)
    on = {"connection": "local", "dashboard": "wide"}
    r = client.post("/api/query", json={**on, "query": "rows", "values": {"by": "us", "unused": "10"}})
    assert r.json()["data"] == [["us", 20]]
    assert ran == [by["options_sql"], "SELECT * FROM orders WHERE region = 'us'"]
    ran.clear()
    assert client.post("/api/query", json={**on, "query": "plain"}).status_code == 200
    assert ran == ["SELECT * FROM orders"]


FED = {
    "name": "fed",
    "html": '<qv-select-view query="orders"></qv-select-view>',
    "queries": {
        "total": {"connection": "local", "sql": "SELECT sum(amount) AS t FROM orders"},
        "orders": {"connection": "warehouse", "sql": "SELECT sku, qty FROM stock ORDER BY sku"},
    },
    "params": [],
}


@pytest.fixture
def fed_client(tmp_path, dash_repo):
    """The `sales` config plus a `warehouse` sqlite file only it holds `stock` in."""
    dash_repo.commit([SALES, FED])
    config = _config(tmp_path, dash_repo)
    wh = tmp_path / "warehouse.sqlite"
    with sqlite3.connect(wh) as con:
        con.execute("CREATE TABLE stock (sku TEXT, qty INTEGER)")
        con.executemany("INSERT INTO stock VALUES (?, ?)", [("a", 1), ("b", 2)])
    local = config.connections["local"]
    config.connections["warehouse"] = replace(local, name="warehouse", config=replace(local.config, path=str(wh)))
    with TestClient(create_app(config)) as c:
        yield c


ON_FED = {"dashboard": "fed"}


# req: architecture/viewer_server_api/named-connection
def test_a_query_runs_on_the_connection_it_names(fed_client):
    r = fed_client.post("/api/run", json={**ON_FED, "connection": "ignored"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"]["total"] == {"t": [30]}
    assert body["results"]["orders"] == {"sku": ["a", "b"], "qty": [1, 2]}
    assert [(c["name"], c["status"], c["queries"]) for c in body["connections"]] == [
        ("local", "ok", ["total"]),
        ("warehouse", "ok", ["orders"]),
    ]


# req: architecture/viewer_server_api/named-connection
def test_a_query_naming_an_unconfigured_connection_fails_by_name(fed_client, dash_repo):
    dash_repo.commit([{**FED, "queries": {**FED["queries"], "orders": {"connection": "nope", "sql": "SELECT 1"}}}])
    asyncio.run(fed_client.app.state.repo.refresh())
    r = fed_client.post("/api/run", json=ON_FED)
    assert r.status_code == 400
    assert r.json()["message"] == 'orders: unknown connection "nope"'
    assert [(c["name"], c["status"]) for c in r.json()["connections"]] == [("local", "ok"), ("nope", "unknown")]
    r = fed_client.post("/api/query", json={**ON_FED, "query": "orders"})
    assert r.status_code == 400 and 'unknown connection "nope"' in r.json()["message"]
    r = fed_client.post("/api/describe", json={**ON_FED, "query": "orders"})
    assert r.status_code == 400 and r.json()["message"] == 'orders: unknown connection "nope"'


# req: architecture/viewer_server_api/named-connection
def test_a_widget_pages_on_its_querys_connection(fed_client):
    r = fed_client.post("/api/query", json={**ON_FED, "query": "orders", "limit": 1})
    assert r.json()["data"] == [["a", 1]]
    r = fed_client.post("/api/describe", json={**ON_FED, "query": "orders"})
    assert [f["name"] for f in r.json()["fields"]] == ["sku", "qty"]


# req: architecture/viewer_server_api/named-connection, architecture/viewer_server_api/names-not-sql
def test_the_dashboard_listing_never_carries_an_entry(fed_client):
    r = fed_client.get("/api/dashboards/fed")
    assert r.json()["queries"] == ["total", "orders"]
    assert r.json()["connections"] == ["local", "warehouse"]
    assert "sql" not in r.text and "SELECT" not in r.text


# req: architecture/viewer_server_api/named-connection
def test_the_dashboard_listing_names_its_params_connections_too(fed_client, dash_repo):
    params = [
        {"name": "s", "options_sql": "SELECT sku FROM stock", "connection": "warehouse"},
        {"name": "r", "options_sql": "SELECT 1", "connection": "archive"},
    ]
    dash_repo.commit([{**FED, "name": "picked", "params": params}])
    asyncio.run(fed_client.app.state.repo.refresh())
    assert fed_client.get("/api/dashboards/picked").json()["connections"] == ["local", "warehouse", "archive"]


# req: architecture/viewer_server_api/named-connection
def test_a_mixed_dashboard_is_not_served(fed_client, dash_repo):
    dash_repo.commit([{**FED, "name": "mixed", "queries": {**FED["queries"], "plain": "SELECT 1"}}])
    assert (dash_repo.author / dashboard_reldir("mixed")).is_dir()  # in the repo...
    assert asyncio.run(fed_client.app.state.repo.refresh())  # ...and the load ran on it
    assert fed_client.get("/api/dashboards").json() == [{"name": "fed"}, {"name": "sales"}]
    assert fed_client.get("/api/dashboards/mixed").status_code == 404
