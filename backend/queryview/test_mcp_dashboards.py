"""The run_dashboard MCP tool: a draft's queries run for the agent, its
params resolved and substituted as the page's own run does."""

from __future__ import annotations

import duckdb

from queryview import mcp_server, sessions
from queryview.connect import _save_active_connection, open_saved
from queryview.drivers.duckdb import DuckConfig
from queryview.mcp_server import mcp, run_dashboard
from queryview.test_mcp_connections import _connected_session, _run

REGION = [{"name": "region", "options": ["eu", "us"]}]
Q = {"q": "SELECT {region} AS v"}


def test_substitutes_the_given_value():
    out = _run(run_dashboard(_connected_session("rd-value"), Q, REGION, {"region": "us"}))
    assert out["ok"] is True and out["results"] == {"q": {"v": ["us"]}}
    assert out["meta"]["q"][0]["name"] == "v"
    assert out["params"][0]["value"] == "us" and "database" in out


def test_a_param_left_out_or_not_offered_takes_its_default():
    sid = _connected_session("rd-default")
    for values in (None, {"region": "mars"}, {"region": 3}):
        assert _run(run_dashboard(sid, Q, REGION, values))["results"] == {"q": {"v": ["eu"]}}


def test_a_query_waiting_on_a_choice_is_left_out():
    params = [{**REGION[0], "default": "none"}]
    out = _run(run_dashboard(_connected_session("rd-wait"), Q, params))
    assert out["ok"] is True and out["results"] == {}


def test_each_runs_once_per_option():
    params = [{"name": "region", "kind": "each", "options": ["eu", "us"]}]
    out = _run(run_dashboard(_connected_session("rd-each"), Q, params))
    assert out["results"] == {"q": {"v": ["eu", "us"]}}


def test_limit_cuts_rows_and_is_clamped():
    sid = _connected_session("rd-limit")
    q = {"q": "SELECT * FROM range(5) AS t(i)"}
    assert _run(run_dashboard(sid, q, limit=2))["results"]["q"]["i"] == [0, 1]
    assert _run(run_dashboard(sid, q, limit=0))["results"]["q"]["i"] == [0]
    assert len(_run(run_dashboard(sid, q, limit=99999))["results"]["q"]["i"]) == 5


def test_reads_a_folder(tmp_path):
    (tmp_path / "dashboard.html").write_text("<p></p>")
    (tmp_path / "queries.yaml").write_text("q: SELECT {region} AS v\n")
    (tmp_path / "meta.yaml").write_text("params:\n  - name: region\n    options: [eu, us]\n")
    sid = _connected_session("rd-dir")
    assert _run(run_dashboard(sid, dir=str(tmp_path)))["results"] == {"q": {"v": ["eu"]}}
    both = _run(run_dashboard(sid, Q, dir=str(tmp_path)))
    assert both == {"ok": False, "message": "pass either `queries`, or `dir`"}


def test_refusals():
    sid = _connected_session("rd-refuse")
    assert _run(run_dashboard(sid)) == {"ok": False, "message": "pass `queries`, or `dir`"}
    assert "exactly one" in _run(run_dashboard(sid, Q, [{"name": "region"}]))["message"]
    rec = _run(sessions.create_session())
    assert _run(run_dashboard(rec.id, Q, REGION)) == {"ok": False, "message": "not connected"}


def test_a_failing_query_names_itself_and_keeps_the_params():
    sid = _connected_session("rd-fail")
    out = _run(run_dashboard(sid, {"q": "SELECT {region} FROM no_such_table"}, REGION))
    assert out["ok"] is False and out["message"].startswith("q:") and out["params"][0]["value"] == "eu"


def test_a_drop_as_a_query_fails_and_leaves_the_table(tmp_path):
    path = str(tmp_path / "sales_reporting.duckdb")
    with duckdb.connect(path) as con:
        con.execute("CREATE TABLE kept (a INTEGER)")
    _run(_save_active_connection("rd-file", DuckConfig(path), "duckdb"))
    sid = _run(sessions.create_session()).id
    assert _run(open_saved(sid, "rd-file"))["ok"]
    assert _run(run_dashboard(sid, {"q": "DROP TABLE kept"}))["ok"] is False
    assert _run(run_dashboard(sid, {"q": "SELECT count(*) AS n FROM kept"}))["results"] == {"q": {"n": [0]}}


def test_a_non_string_value_is_dropped_over_mcp_too():
    args = {"session_id": _connected_session("rd-wire"), "queries": Q, "params": REGION, "values": {"region": 3}}
    assert '"eu"' in str(_run(mcp.call_tool("run_dashboard", args)))


def test_a_run_past_the_deadline_times_out(monkeypatch):
    monkeypatch.setattr(mcp_server, "RUN_DASHBOARD_TIMEOUT_SECONDS", 0.2)
    slow = {"q": "SELECT count(*) AS n FROM range(100000000000) a, range(1000) b"}
    out = _run(run_dashboard(_connected_session("rd-slow"), slow))
    assert out == {"ok": False, "message": "dashboard run timed out after 0.2s"}


def test_a_folder_needs_no_html(tmp_path):
    (tmp_path / "queries.yaml").write_text("q: SELECT 7 AS n\n")
    out = _run(run_dashboard(_connected_session("rd-nohtml"), dir=str(tmp_path)))
    assert out["results"] == {"q": {"n": [7]}}


def test_a_blank_query_is_skipped():
    out = _run(run_dashboard(_connected_session("rd-blank"), {"q": "SELECT 7 AS n", "empty": "   "}))
    assert out["results"] == {"q": {"n": [7]}}
