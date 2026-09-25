"""Tests for the predefined-queries store: cell_view round-trips through
save/list, and workspace scoping."""

from __future__ import annotations

import asyncio

from queryview.queries import (
    get_predefined_query,
    list_predefined_queries,
    save_predefined_query,
)


def _run(coro):
    return asyncio.run(coro)


def test_save_and_list_round_trips_cell_view(default_ws_id):
    _run(
        save_predefined_query(
            "cves",
            "clickhouse",
            "SELECT cve_id FROM t",
            cell_view="cve_id:\n  type: link\n  value: https://nvd.nist.gov/vuln/detail/{cell}\n",
            workspace_id=default_ws_id,
        )
    )
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "cves")
    assert row["query"] == "SELECT cve_id FROM t"
    cell_view = row["cell_view"]
    assert cell_view is not None
    assert "nvd.nist.gov" in cell_view
    assert "{cell}" in cell_view


def test_save_without_cell_view_lists_as_none(default_ws_id):
    _run(save_predefined_query("plain", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "plain")
    assert row["cell_view"] is None


def test_upsert_overwrites_cell_view(default_ws_id):
    _run(
        save_predefined_query(
            "u",
            "clickhouse",
            "SELECT 1",
            cell_view="a: {type: link, value: x}",
            workspace_id=default_ws_id,
        )
    )
    _run(
        save_predefined_query(
            "u",
            "clickhouse",
            "SELECT 1",
            cell_view="b: {type: link, value: y}",
            workspace_id=default_ws_id,
        )
    )
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "u")
    cell_view = row["cell_view"]
    assert cell_view is not None
    assert "b:" in cell_view
    assert "a:" not in cell_view


def test_clearing_cell_view_persists_null(default_ws_id):
    _run(
        save_predefined_query(
            "c",
            "clickhouse",
            "SELECT 1",
            cell_view="x: {type: link, value: y}",
            workspace_id=default_ws_id,
        )
    )
    _run(save_predefined_query("c", "clickhouse", "SELECT 1", cell_view=None, workspace_id=default_ws_id))
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "c")
    assert row["cell_view"] is None


def test_order_by_and_fields_round_trip(default_ws_id):
    _run(
        save_predefined_query(
            "q1",
            "clickhouse",
            "SELECT 1",
            cell_view=None,
            order_by='[{"name":"id","dir":"DESC"}]',
            fields='["id","name"]',
            workspace_id=default_ws_id,
        )
    )
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "q1")
    assert row["order_by"] == '[{"name":"id","dir":"DESC"}]'
    assert row["fields"] == '["id","name"]'


def test_null_presentation_is_preserved(default_ws_id):
    _run(save_predefined_query("q2", "clickhouse", "SELECT 2", workspace_id=default_ws_id))
    rows = _run(list_predefined_queries("clickhouse", default_ws_id))
    row = next(r for r in rows if r["query_name"] == "q2")
    assert row["order_by"] is None and row["fields"] is None


def test_same_name_is_distinct_per_workspace(default_ws_id):
    from queryview.workspaces import create_workspace, resolve

    _run(create_workspace("t3-iso"))
    other = _run(resolve("t3-iso")).id
    _run(save_predefined_query("iso q", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    _run(save_predefined_query("iso q", "clickhouse", "SELECT 2", workspace_id=other))

    q_default = _run(get_predefined_query("clickhouse", "iso q", default_ws_id))
    q_other = _run(get_predefined_query("clickhouse", "iso q", other))
    assert q_default is not None and q_default["query"] == "SELECT 1"
    assert q_other is not None and q_other["query"] == "SELECT 2"
    names_default = [r["query_name"] for r in _run(list_predefined_queries("clickhouse", default_ws_id))]
    names_other = [r["query_name"] for r in _run(list_predefined_queries("clickhouse", other))]
    assert "iso q" in names_default and "iso q" in names_other


def test_api_unknown_workspace_is_404():
    from fastapi.testclient import TestClient

    from queryview.main import app

    c = TestClient(app)
    r = c.get("/api/predefined-queries", params={"workspace": "nope-t3"})
    assert r.status_code == 404


def test_mcp_list_queries_parses_presentation(default_ws_id):
    from queryview.mcp_server import list_queries

    _run(
        save_predefined_query(
            "lq",
            "clickhouse",
            "SELECT 1",
            order_by='[{"name":"id","dir":"ASC"}]',
            fields='["id"]',
            workspace_id=default_ws_id,
        )
    )
    out = _run(list_queries("clickhouse"))
    row = next(r for r in out["queries"] if r["query_name"] == "lq")
    assert row["order_by"] == [{"name": "id", "dir": "ASC"}]
    assert row["fields"] == ["id"]
    assert row["query"] == "SELECT 1"
