"""The run_dashboard MCP tool: a draft's queries run for the agent, its
params resolved and substituted as the page's own run does."""

from __future__ import annotations

import duckdb

from queryview import mcp_server, sessions
from queryview.connect import _save_active_connection, open_saved
from queryview.dashboard_entries import MIXED
from queryview.drivers.duckdb import DuckConfig
from queryview.mcp_server import _AGENT_DRIVERS, mcp, push_dashboard, run_dashboard
from queryview.test_mcp_connections import _agent_add, _connected_session, _run

REGION = [{"name": "region", "options": ["eu", "us"]}]
Q = {"q": "SELECT {region} AS v"}


# req: architecture/mcp/run-dashboard
def test_substitutes_the_given_value():
    out = _run(run_dashboard(_connected_session("rd-value"), Q, REGION, {"region": "us"}))
    assert out["ok"] is True and out["results"] == {"q": {"v": ["us"]}}
    assert out["meta"]["q"][0]["name"] == "v"
    assert out["params"][0]["value"] == "us" and "database" in out


# req: architecture/mcp/run-dashboard
def test_a_param_left_out_or_not_offered_takes_its_default():
    sid = _connected_session("rd-default")
    for values in (None, {"region": "mars"}, {"region": 3}):
        assert _run(run_dashboard(sid, Q, REGION, values))["results"] == {"q": {"v": ["eu"]}}


# req: architecture/mcp/run-dashboard
def test_a_query_waiting_on_a_choice_is_left_out():
    params = [{**REGION[0], "default": "none"}]
    out = _run(run_dashboard(_connected_session("rd-wait"), Q, params))
    assert out["ok"] is True and out["results"] == {}


# req: architecture/mcp/run-dashboard
def test_each_runs_once_per_option():
    params = [{"name": "region", "kind": "each", "options": ["eu", "us"]}]
    out = _run(run_dashboard(_connected_session("rd-each"), Q, params))
    assert out["results"] == {"q": {"v": ["eu", "us"]}}


# req: architecture/mcp/run-dashboard
def test_limit_cuts_rows_and_is_clamped():
    sid = _connected_session("rd-limit")
    q = {"q": "SELECT * FROM range(5) AS t(i)"}
    assert _run(run_dashboard(sid, q, limit=2))["results"]["q"]["i"] == [0, 1]
    assert _run(run_dashboard(sid, q, limit=0))["results"]["q"]["i"] == [0]
    assert len(_run(run_dashboard(sid, q, limit=99999))["results"]["q"]["i"]) == 5


# req: architecture/mcp/run-dashboard
def test_reads_a_folder(tmp_path):
    (tmp_path / "dashboard.html").write_text("<p></p>")
    (tmp_path / "queries.yaml").write_text("q: SELECT {region} AS v\n")
    (tmp_path / "meta.yaml").write_text("params:\n  - name: region\n    options: [eu, us]\n")
    sid = _connected_session("rd-dir")
    assert _run(run_dashboard(sid, dir=str(tmp_path)))["results"] == {"q": {"v": ["eu"]}}
    both = _run(run_dashboard(sid, Q, dir=str(tmp_path)))
    assert both == {"ok": False, "message": "pass either `queries`, or `dir`"}
    (tmp_path / "queries.yaml").write_text("q: ''\n")
    assert _run(run_dashboard(sid, dir=str(tmp_path))) == {"ok": False, "message": "no runnable query in `dir`"}


# req: architecture/mcp/run-dashboard
def test_refusals():
    sid = _connected_session("rd-refuse")
    assert _run(run_dashboard(sid)) == {"ok": False, "message": "pass `queries`, or `dir`"}
    assert "exactly one" in _run(run_dashboard(sid, Q, [{"name": "region"}]))["message"]
    rec = _run(sessions.create_session())
    assert _run(run_dashboard(rec.id, Q, REGION)) == {"ok": False, "message": "not connected"}


# req: architecture/mcp/run-dashboard
def test_a_failing_query_names_itself_and_keeps_the_params():
    sid = _connected_session("rd-fail")
    out = _run(run_dashboard(sid, {"q": "SELECT {region} FROM no_such_table"}, REGION))
    assert out["ok"] is False and out["message"].startswith("q:") and out["params"][0]["value"] == "eu"


# req: architecture/mcp/run-dashboard
def test_a_drop_as_a_query_fails_and_leaves_the_table(tmp_path):
    path = str(tmp_path / "sales_reporting.duckdb")
    with duckdb.connect(path) as con:
        con.execute("CREATE TABLE kept (a INTEGER)")
    _run(_save_active_connection("rd-file", DuckConfig(path), "duckdb"))
    sid = _run(sessions.create_session()).id
    assert _run(open_saved(sid, "rd-file"))["ok"]
    assert _run(run_dashboard(sid, {"q": "DROP TABLE kept"}))["ok"] is False
    assert _run(run_dashboard(sid, {"q": "SELECT count(*) AS n FROM kept"}))["results"] == {"q": {"n": [0]}}


# req: architecture/mcp/run-dashboard
def test_a_value_not_offered_takes_the_default_over_mcp_too():
    args = {"session_id": _connected_session("rd-wire"), "queries": Q, "params": REGION, "values": {"region": 3}}
    assert '"eu"' in str(_run(mcp.call_tool("run_dashboard", args)))


# req: architecture/mcp/run-dashboard
def test_a_number_or_boolean_value_is_read_as_its_text():
    sid = _connected_session("rd-typed")
    params = [{"name": "n", "options": [1, 2]}, {"name": "b", "options": [False, True]}]
    out = _run(run_dashboard(sid, {"q": "SELECT {n} AS n, {b} AS b"}, params, {"n": 2, "b": True}))
    assert [p["value"] for p in out["params"]] == ["2", "true"]
    dim = [{"name": "region", "kind": "dimension"}]
    assert _run(run_dashboard(sid, Q, dim, {"region": False}))["results"] == {"q": {"v": [""]}}


# req: architecture/mcp/run-dashboard
def test_a_run_past_the_deadline_times_out(monkeypatch):
    monkeypatch.setattr(mcp_server, "RUN_DASHBOARD_TIMEOUT_SECONDS", 0.2)
    slow = {"q": "SELECT count(*) AS n FROM range(100000000000) a, range(1000) b"}
    out = _run(run_dashboard(_connected_session("rd-slow"), slow))
    assert out == {"ok": False, "message": "dashboard run timed out after 0.2s"}


# req: architecture/mcp/run-dashboard
def test_a_folder_needs_no_html(tmp_path):
    (tmp_path / "queries.yaml").write_text("q: SELECT 7 AS n\n")
    out = _run(run_dashboard(_connected_session("rd-nohtml"), dir=str(tmp_path)))
    assert out["results"] == {"q": {"n": [7]}}


# req: architecture/mcp/run-dashboard
def test_a_blank_query_is_skipped():
    out = _run(run_dashboard(_connected_session("rd-blank"), {"q": "SELECT 7 AS n", "empty": "   "}))
    assert out["results"] == {"q": {"n": [7]}}


def _orders(connection: str) -> dict:
    return {"orders": {"connection": connection, "sql": "SELECT 2 AS n"}}


# req: architecture/mcp/run-dashboard
def test_a_query_runs_on_the_connection_it_names():
    sid = _connected_session("rd-named-main")
    assert _agent_add(sid, "rd-named-wh")["ok"]
    out = _run(run_dashboard(sid, _orders("rd-named-wh")))
    assert out["ok"] is True and out["results"] == {"orders": {"n": [2]}}
    assert [(c["name"], c["status"], c["queries"]) for c in out["connections"]] == [("rd-named-wh", "ok", ["orders"])]


# req: architecture/mcp/run-dashboard
def test_a_disconnected_session_runs_named_queries():
    sid = _run(sessions.create_session()).id
    assert _agent_add(sid, "rd-loose-wh")["ok"]
    out = _run(run_dashboard(sid, _orders("rd-loose-wh")))
    assert out["ok"] is True and out["results"] == {"orders": {"n": [2]}} and out["database"] is None


# req: architecture/mcp/run-dashboard
def test_a_file_connection_the_agent_did_not_add_is_refused():
    _run(_save_active_connection("rd-user-duck", DuckConfig(":memory:"), "duckdb"))
    out = _run(run_dashboard(_run(sessions.create_session()).id, _orders("rd-user-duck")))
    assert out["ok"] is False
    assert out["message"] == f"orders: the agent may switch only to {', '.join(_AGENT_DRIVERS)} connections"
    assert [c["status"] for c in out["connections"]] == ["failed"]


# req: architecture/mcp/run-dashboard
def test_a_malformed_entry_is_refused():
    out = _run(run_dashboard(_connected_session("rd-malformed"), _orders("")))
    assert out == {"ok": False, "message": "query 'orders': connection must be a non-empty string"}


# req: architecture/mcp/run-dashboard
def test_a_mixed_dashboard_is_refused():
    sid = _connected_session("rd-mixed")
    assert _agent_add(sid, "rd-mixed-wh")["ok"]
    out = _run(run_dashboard(sid, {**_orders("rd-mixed-wh"), "q": "SELECT 1"}))
    assert out == {"ok": False, "message": MIXED}


# req: architecture/mcp/run-dashboard
def test_a_federated_run_on_a_made_up_session_is_refused():
    _run(_save_active_connection("rd-ghost-duck", DuckConfig(":memory:"), "duckdb"))
    assert _run(run_dashboard("no-such-session", _orders("rd-ghost-duck"))) == {
        "ok": False,
        "message": "unknown session",
    }


# req: architecture/mcp/run-dashboard
def test_a_federated_push_on_a_made_up_session_is_refused():
    out = _run(push_dashboard("no-such-session", "<p></p>", _orders("rd-ghost-duck")))
    assert out["ok"] is False and out["message"] == "not connected"
