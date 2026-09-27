"""yamlio: export/import round trips at the module level, plus document
validation (parse_document rejects malformed files before anything writes)."""

from __future__ import annotations

import asyncio

import pytest
import yaml

from queryview.yamlio import (
    YamlIOError,
    export_dashboard,
    export_query,
    export_workspace,
    import_text,
    parse_document,
    slug,
)


def _run(coro):
    return asyncio.run(coro)


def test_slug_passthrough_and_encoding():
    assert slug("top_errors") == "top_errors"
    assert slug("top errors 2.0") == "top errors 2.0"
    assert slug("a/b") == "a%2Fb"
    assert slug(".hidden") == "%2Ehidden"
    assert slug("héllo") == "h%C3%A9llo"


# --- parse_document validation ---------------------------------------------


def test_parse_rejects_non_mapping_and_unknown_kind():
    with pytest.raises(YamlIOError):
        parse_document("- just\n- a list\n")
    with pytest.raises(YamlIOError):
        parse_document("kind: nope\n")
    with pytest.raises(YamlIOError):
        parse_document("query_name: no kind\n")


def test_parse_rejects_invalid_yaml():
    with pytest.raises(YamlIOError):
        parse_document("kind: [unclosed\n")


def test_parse_query_requires_fields():
    with pytest.raises(YamlIOError):
        parse_document("kind: query\nquery_name: x\n")  # no type/query
    with pytest.raises(YamlIOError):
        parse_document("kind: query\ntype: clickhouse\nquery_name: ''\nquery: SELECT 1\n")


def test_parse_query_validates_presentation():
    doc = "kind: query\ntype: clickhouse\nquery_name: x\nquery: SELECT 1\norder_by: notalist\n"
    with pytest.raises(YamlIOError):
        parse_document(doc)


def test_parse_query_validates_cell_view_yaml():
    doc = 'kind: query\ntype: clickhouse\nquery_name: x\nquery: SELECT 1\ncell_view: "col: [unclosed"\n'
    with pytest.raises(YamlIOError):
        parse_document(doc)


def test_parse_dashboard_requires_fields():
    with pytest.raises(YamlIOError):
        parse_document("kind: dashboard\nname: d\nconnection: c\n")  # no html
    with pytest.raises(YamlIOError):
        parse_document("kind: dashboard\nname: d\nconnection: c\nhtml: <p/>\nqueries: [notamap]\n")


def test_parse_workspace_validates_entries():
    doc = "kind: workspace\nqueries:\n  - query_name: missing type\n    query: SELECT 1\n"
    with pytest.raises(YamlIOError):
        parse_document(doc)
    with pytest.raises(YamlIOError):
        parse_document("kind: workspace\nqueries: notalist\n")


def test_parse_empty_workspace_bundle_is_valid():
    kind, payload = parse_document("kind: workspace\n")
    assert kind == "workspace"
    assert payload == {"queries": [], "dashboards": []}


# --- Round trips ------------------------------------------------------------


def test_query_export_import_round_trip(default_ws_id):
    from queryview.queries import get_predefined_query, save_predefined_query

    _run(
        save_predefined_query(
            "yio query",
            "clickhouse",
            "SELECT 1\nFROM t",
            "col:\n  type: link\n  value: https://x/{cell}\n",
            '[{"name": "col", "dir": "DESC"}]',
            '["col"]',
            workspace_id=default_ws_id,
        )
    )
    text = _run(export_query("clickhouse", "yio query", default_ws_id))
    data = yaml.safe_load(text)
    assert data["kind"] == "query" and data["type"] == "clickhouse"
    assert data["query"] == "SELECT 1\nFROM t"

    # Re-import under a changed name to prove the import writes the file's
    # content, then compare rows field by field.
    _run(import_text(text.replace("yio query", "yio query copy"), default_ws_id))
    orig = _run(get_predefined_query("clickhouse", "yio query", default_ws_id))
    copy = _run(get_predefined_query("clickhouse", "yio query copy", default_ws_id))
    assert orig is not None and copy is not None
    for key in ("query", "cell_view", "fields"):
        assert copy[key] == orig[key]
    import json

    ob_copy, ob_orig = copy["order_by"], orig["order_by"]
    assert ob_copy is not None and ob_orig is not None
    assert json.loads(ob_copy) == json.loads(ob_orig)


def test_dashboard_export_import_round_trip(default_ws_id):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(
        upsert_dashboard(
            "yio dash",
            "<html>\n<body>v1</body>\n</html>",
            {"panel": "SELECT 1"},
            workspace_id=default_ws_id,
        )
    )
    text = _run(export_dashboard("yio dash", default_ws_id))
    data = yaml.safe_load(text)
    assert data["kind"] == "dashboard" and "connection" not in data

    # Drift the stored copy, then import the export to restore it.
    _run(upsert_dashboard("yio dash", "<p>v2</p>", {}, workspace_id=default_ws_id))
    r = _run(import_text(text, default_ws_id))
    assert r == {"kind": "dashboard", "queries": 0, "dashboards": 1}
    d = _run(get_dashboard("yio dash", default_ws_id))
    assert d is not None
    assert "v1" in d["html"] and d["queries"] == {"panel": "SELECT 1"}


def test_workspace_export_import_round_trip(default_ws_id, wipe_workspace_entities):
    """Export one workspace's whole content and import it into another."""
    from queryview.dashboards import get_dashboard, upsert_dashboard
    from queryview.queries import get_predefined_query, save_predefined_query
    from queryview.workspaces import create_workspace, delete_workspace, resolve

    _run(save_predefined_query("ws q1", "clickhouse", "SELECT 1", workspace_id=default_ws_id))
    _run(save_predefined_query("ws q2", "postgres", "SELECT 2", workspace_id=default_ws_id))
    _run(upsert_dashboard("ws dash", "<p>hi</p>", {"a": "SELECT 3"}, workspace_id=default_ws_id))
    text = _run(export_workspace(default_ws_id))
    data = yaml.safe_load(text)
    assert data["kind"] == "workspace"
    names = {(q["type"], q["query_name"]) for q in data["queries"]}
    assert {("clickhouse", "ws q1"), ("postgres", "ws q2")} <= names

    _run(create_workspace("yio target"))
    try:
        target = _run(resolve("yio target"))
        r = _run(import_text(text, target.id))
        assert r["kind"] == "workspace" and r["queries"] >= 2 and r["dashboards"] >= 1
        q = _run(get_predefined_query("postgres", "ws q2", target.id))
        assert q is not None and q["query"] == "SELECT 2"
        d = _run(get_dashboard("ws dash", target.id))
        assert d is not None and d["queries"] == {"a": "SELECT 3"}
        # Clean the target so delete_workspace succeeds (it must be empty).
        wipe_workspace_entities(target.id)
    finally:
        _run(delete_workspace("yio target"))


def test_import_validates_before_writing(default_ws_id):
    """A workspace bundle with one bad entry writes nothing at all."""
    from queryview.queries import get_predefined_query

    doc = (
        "kind: workspace\n"
        "queries:\n"
        "  - type: clickhouse\n"
        "    query_name: good entry\n"
        "    query: SELECT 1\n"
        "  - type: clickhouse\n"
        "    query_name: bad entry\n"
    )
    with pytest.raises(YamlIOError):
        _run(import_text(doc, default_ws_id))
    assert _run(get_predefined_query("clickhouse", "good entry", default_ws_id)) is None
