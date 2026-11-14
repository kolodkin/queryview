"""yamlio: export/import round trips at the module level, plus document
validation (parse_document rejects malformed files before anything writes)."""

from __future__ import annotations

import asyncio

import pytest
import yaml

from queryview.yamlio import (
    YamlIOError,
    export_dashboard,
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


def test_saved_queries_are_refused_not_ignored(default_ws_id):
    """The removed `query` kind, alone or inside a workspace bundle, fails
    with a message that says why — and writes nothing."""
    from queryview.dashboards import get_dashboard

    query = "kind: query\ntype: clickhouse\nquery_name: x\nquery: SELECT 1\n"
    bundle = (
        "kind: workspace\n"
        "queries:\n  - {type: clickhouse, query_name: x, query: SELECT 1}\n"
        "dashboards:\n  - {name: yio beside queries, html: <p/>}\n"
    )
    for doc in (query, bundle):
        with pytest.raises(YamlIOError) as e:
            _run(import_text(doc, default_ws_id))
        assert e.value.status == 400 and "saved queries are no longer supported" in str(e.value)
    assert _run(get_dashboard("yio beside queries", default_ws_id)) is None
    # An empty `queries` list (an older export of a query-free workspace) still imports.
    assert parse_document("kind: workspace\nqueries: []\n") == ("workspace", {"dashboards": []})


def test_parse_dashboard_requires_fields():
    with pytest.raises(YamlIOError):
        parse_document("kind: dashboard\nname: d\nconnection: c\n")  # no html
    with pytest.raises(YamlIOError):
        parse_document("kind: dashboard\nname: d\nconnection: c\nhtml: <p/>\nqueries: [notamap]\n")


def test_parse_workspace_validates_entries():
    doc = "kind: workspace\ndashboards:\n  - name: missing html\n"
    with pytest.raises(YamlIOError):
        parse_document(doc)
    with pytest.raises(YamlIOError):
        parse_document("kind: workspace\ndashboards: notalist\n")


def test_parse_empty_workspace_bundle_is_valid():
    kind, payload = parse_document("kind: workspace\n")
    assert kind == "workspace"
    assert payload == {"dashboards": []}


# --- Round trips ------------------------------------------------------------


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
    assert r == {"kind": "dashboard", "dashboards": 1}
    d = _run(get_dashboard("yio dash", default_ws_id))
    assert d is not None
    assert "v1" in d["html"] and d["queries"] == {"panel": "SELECT 1"}


def test_workspace_export_import_round_trip(default_ws_id, wipe_workspace_entities):
    """Export one workspace's whole content and import it into another."""
    from queryview.dashboards import get_dashboard, upsert_dashboard
    from queryview.workspaces import create_workspace, delete_workspace, resolve

    params = [{"name": "region", "options": ["emea", "apac"]}]
    _run(upsert_dashboard("ws dash", "<p>hi</p>", {"a": "SELECT 3"}, workspace_id=default_ws_id))
    _run(upsert_dashboard("ws dash 2", "<p>{region}</p>", {}, params, workspace_id=default_ws_id))
    text = _run(export_workspace(default_ws_id))
    data = yaml.safe_load(text)
    assert data["kind"] == "workspace" and "queries" not in data
    assert {"ws dash", "ws dash 2"} <= {d["name"] for d in data["dashboards"]}

    _run(create_workspace("yio target"))
    try:
        target = _run(resolve("yio target"))
        r = _run(import_text(text, target.id))
        assert r["kind"] == "workspace" and r["dashboards"] >= 2 and "queries" not in r
        d = _run(get_dashboard("ws dash", target.id))
        assert d is not None and d["queries"] == {"a": "SELECT 3"}
        d2 = _run(get_dashboard("ws dash 2", target.id))
        assert d2 is not None and d2["params"] == params
        # Clean the target so delete_workspace succeeds (it must be empty).
        wipe_workspace_entities(target.id)
    finally:
        _run(delete_workspace("yio target"))


def test_import_validates_before_writing(default_ws_id):
    """A workspace bundle with one bad entry writes nothing at all."""
    from queryview.dashboards import get_dashboard

    doc = "kind: workspace\ndashboards:\n  - name: good entry\n    html: <p/>\n  - name: bad entry\n"
    with pytest.raises(YamlIOError):
        _run(import_text(doc, default_ws_id))
    assert _run(get_dashboard("good entry", default_ws_id)) is None
