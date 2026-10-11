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


def test_rename_moves_the_row_and_keeps_its_content(default_ws_id):
    from queryview.queries import rename_predefined_query

    _run(
        save_predefined_query(
            "rn old", "clickhouse", "SELECT 7", cell_view="a: {type: link, value: x}", workspace_id=default_ws_id
        )
    )
    _run(rename_predefined_query("clickhouse", "rn old", "rn new", workspace_id=default_ws_id))
    assert _run(get_predefined_query("clickhouse", "rn old", default_ws_id)) is None
    row = _run(get_predefined_query("clickhouse", "rn new", default_ws_id))
    assert row is not None and row["query"] == "SELECT 7" and row["cell_view"] == "a: {type: link, value: x}"


def test_rename_refuses_missing_and_taken_names(default_ws_id):
    import pytest

    from queryview.queries import PredefinedQueryError, rename_predefined_query, set_predefined_query_deleted

    _run(save_predefined_query("rn a", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    _run(save_predefined_query("rn b", "clickhouse", "SELECT 2", workspace_id=default_ws_id))
    _run(save_predefined_query("rn gone", "clickhouse", "SELECT 3", workspace_id=default_ws_id))
    _run(set_predefined_query_deleted("clickhouse", "rn gone", True, workspace_id=default_ws_id))
    with pytest.raises(PredefinedQueryError) as missing:
        _run(rename_predefined_query("clickhouse", "rn nope", "rn c", workspace_id=default_ws_id))
    assert missing.value.status == 404
    with pytest.raises(PredefinedQueryError) as deleted_src:
        _run(rename_predefined_query("clickhouse", "rn gone", "rn c", workspace_id=default_ws_id))
    assert deleted_src.value.status == 404
    with pytest.raises(PredefinedQueryError) as taken:
        _run(rename_predefined_query("clickhouse", "rn a", "rn b", workspace_id=default_ws_id))
    assert taken.value.status == 409
    with pytest.raises(PredefinedQueryError) as taken_by_deleted:
        _run(rename_predefined_query("clickhouse", "rn a", "rn gone", workspace_id=default_ws_id))
    assert taken_by_deleted.value.status == 409 and "deleted" in str(taken_by_deleted.value)
    b = _run(get_predefined_query("clickhouse", "rn b", default_ws_id))
    assert b is not None and b["query"] == "SELECT 2"  # untouched
    # Renaming to its own name is a no-op, not a clash.
    _run(rename_predefined_query("clickhouse", "rn a", "rn a", workspace_id=default_ws_id))


def test_delete_is_soft_and_undelete_brings_it_back(default_ws_id):
    import pytest

    from queryview.queries import PredefinedQueryError, list_all_predefined_queries, set_predefined_query_deleted
    from queryview.workspaces import create_workspace, resolve

    _run(create_workspace("del-iso"))
    other = _run(resolve("del-iso")).id
    _run(save_predefined_query("del q", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    _run(save_predefined_query("del q", "clickhouse", "SELECT 2", workspace_id=other))
    _run(set_predefined_query_deleted("clickhouse", "del q", True, workspace_id=default_ws_id))

    # Gone from every live view, kept among the deleted with its content.
    assert _run(get_predefined_query("clickhouse", "del q", default_ws_id)) is None
    assert all(r["query_name"] != "del q" for r in _run(list_predefined_queries("clickhouse", default_ws_id)))
    assert all(r["query_name"] != "del q" for r in _run(list_all_predefined_queries(default_ws_id)))
    everything = _run(list_predefined_queries("clickhouse", default_ws_id, include_deleted=True))
    row = next(r for r in everything if r["query_name"] == "del q")
    assert row["query"] == "SELECT 1" and isinstance(row["deleted_at"], int)
    assert _run(get_predefined_query("clickhouse", "del q", other)) is not None  # other workspace untouched
    with pytest.raises(PredefinedQueryError) as twice:
        _run(set_predefined_query_deleted("clickhouse", "del q", True, workspace_id=default_ws_id))
    assert twice.value.status == 404

    _run(set_predefined_query_deleted("clickhouse", "del q", False, workspace_id=default_ws_id))
    back = _run(get_predefined_query("clickhouse", "del q", default_ws_id))
    assert back is not None and back["query"] == "SELECT 1"
    with pytest.raises(PredefinedQueryError) as live:
        _run(set_predefined_query_deleted("clickhouse", "del q", False, workspace_id=default_ws_id))
    assert live.value.status == 404


def test_a_non_strict_delete_or_undelete_of_a_query_already_there_is_a_no_op(default_ws_id, monkeypatch):
    import pytest

    from queryview import queries
    from queryview.queries import PredefinedQueryError, update_predefined_query

    def mark(name: str, deleted: bool) -> None:
        _run(update_predefined_query("clickhouse", name, workspace_id=default_ws_id, deleted=deleted, strict=False))

    _run(save_predefined_query("lax q", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    mark("lax q", False)  # already live
    assert _run(get_predefined_query("clickhouse", "lax q", default_ws_id)) is not None
    monkeypatch.setattr(queries, "_now_ms", lambda: 1000)
    mark("lax q", True)
    monkeypatch.setattr(queries, "_now_ms", lambda: 2000)
    mark("lax q", True)  # already deleted: keeps its deletion time
    row = _run(get_predefined_query("clickhouse", "lax q", default_ws_id, include_deleted=True))
    assert row is not None and row["deleted_at"] == 1000
    with pytest.raises(PredefinedQueryError) as missing:
        mark("lax nope", True)
    assert missing.value.status == 404


def test_saving_over_a_deleted_query_brings_it_back(default_ws_id):
    from queryview.queries import set_predefined_query_deleted

    _run(save_predefined_query("del save", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    _run(set_predefined_query_deleted("clickhouse", "del save", True, workspace_id=default_ws_id))
    _run(save_predefined_query("del save", "clickhouse", "SELECT 2", workspace_id=default_ws_id))
    row = _run(get_predefined_query("clickhouse", "del save", default_ws_id))
    assert row is not None and row["query"] == "SELECT 2"


def test_deleted_queries_dont_keep_a_workspace_alive():
    from queryview.queries import set_predefined_query_deleted
    from queryview.workspaces import create_workspace, delete_workspace, resolve

    _run(create_workspace("del-ws"))
    ws = _run(resolve("del-ws")).id
    _run(save_predefined_query("del ws q", "clickhouse", "SELECT 1", workspace_id=ws))
    _run(set_predefined_query_deleted("clickhouse", "del ws q", True, workspace_id=ws))
    _run(delete_workspace("del-ws"))
    _run(create_workspace("del-ws"))  # a fresh workspace by that name starts empty
    fresh = _run(resolve("del-ws")).id
    assert _run(list_predefined_queries("clickhouse", fresh, include_deleted=True)) == []
    _run(delete_workspace("del-ws"))


def test_api_rename_delete_and_undelete(default_ws_id):
    from fastapi.testclient import TestClient

    from queryview.main import app

    c = TestClient(app)
    c.post("/api/predefined-queries", json={"query_name": "api rn", "type": "clickhouse", "query": "SELECT 1"})
    c.post("/api/predefined-queries", json={"query_name": "api taken", "type": "clickhouse", "query": "SELECT 2"})

    def names(deleted: bool = False) -> list[str]:
        r = c.get("/api/predefined-queries", params={"type": "clickhouse", "include_deleted": "1"})
        return [q["query_name"] for q in r.json()["queries"] if (q["deleted_at"] is not None) == deleted]

    r = c.patch("/api/predefined-queries", json={"query_name": "api rn", "type": "clickhouse"})
    assert r.status_code == 400
    r = c.patch(
        "/api/predefined-queries",
        json={"query_name": "api rn", "type": "clickhouse", "new_name": "api taken"},
    )
    assert r.status_code == 409
    r = c.patch(
        "/api/predefined-queries",
        json={"query_name": "api rn", "type": "clickhouse", "new_name": "  api renamed  "},
    )
    assert r.json() == {"ok": True}
    assert "api renamed" in names() and "api rn" not in names()

    r = c.delete("/api/predefined-queries", params={"type": "clickhouse"})
    assert r.status_code == 400
    r = c.delete("/api/predefined-queries", params={"query_name": "api renamed", "type": "clickhouse"})
    assert r.json() == {"ok": True}
    assert "api renamed" not in names() and "api renamed" in names(deleted=True)
    r = c.delete("/api/predefined-queries", params={"query_name": "api renamed", "type": "clickhouse"})
    assert r.status_code == 404

    undelete = {"query_name": "api renamed", "type": "clickhouse", "deleted": False}
    assert c.patch("/api/predefined-queries", json=undelete).json() == {"ok": True}
    assert "api renamed" in names() and "api renamed" not in names(deleted=True)
    assert c.patch("/api/predefined-queries", json=undelete).status_code == 404
    # Deleting goes through DELETE only.
    assert c.patch("/api/predefined-queries", json={**undelete, "deleted": True}).status_code == 400
    # Undelete + rename is all or nothing: a taken name leaves it deleted.
    c.delete("/api/predefined-queries", params={"query_name": "api renamed", "type": "clickhouse"})
    r = c.patch("/api/predefined-queries", json={**undelete, "new_name": "api taken"})
    assert r.status_code == 409
    assert "api renamed" in names(deleted=True)

    r = c.delete(
        "/api/predefined-queries",
        params={"query_name": "api taken", "type": "clickhouse", "workspace": "nope-del"},
    )
    assert r.status_code == 404
