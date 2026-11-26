"""yamlio: export/import round trips at the module level, plus document
validation (parse_document rejects malformed files before anything writes)."""

from __future__ import annotations

import asyncio

import pytest
import yaml

from queryview.dashboard_entries import MIXED
from queryview.dashboards import get_dashboard, upsert_dashboard
from queryview.yamlio import (
    YamlIOError,
    dashboard_from_data,
    dashboard_to_data,
    export_dashboard,
    export_workspace,
    import_text,
    name_error,
    parse_document,
    slug,
    unslug,
)


def _run(coro):
    return asyncio.run(coro)


def test_slug_passthrough_and_encoding():
    assert slug("top_errors") == "top_errors"
    assert slug("top errors 2.0") == "top errors 2.0"
    assert slug("a/b") == "a%2Fb"
    assert slug(".hidden") == "%2Ehidden"
    assert slug("héllo") == "h%C3%A9llo"


def test_unslug_inverts_slug_and_refuses_other_spellings():
    for name in ["Sales 2026", ".hidden", "100% done", "a/b\\c", "销售", "x%41", ".."]:
        assert unslug(slug(name)) == name
    assert unslug("a%41") is None  # slug writes "aA"
    assert unslug("%zz") is None and unslug("%FF") is None and unslug("a%2f") is None
    assert unslug(" ") is None  # a blank name can't be saved or opened by name


def test_name_error():
    assert name_error("x" * 255, []) is None
    too_long = name_error("x" * 256, [])
    assert too_long is not None and too_long[0] == 400
    non_ascii = name_error("é" * 43, [])  # 258 bytes encoded
    assert non_ascii is not None and non_ascii[0] == 400
    twin = name_error("Sales", ["sales"])
    assert twin is not None and twin[0] == 409 and "'sales'" in twin[1]
    assert name_error("sales", ["sales", "Sales"]) is None  # not new
    assert name_error("É", ["é"]) is None  # folders differ on any filesystem


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
    doc = "kind: workspace\ndashboards:\n  - name: good entry\n    html: <p/>\n  - name: bad entry\n"
    with pytest.raises(YamlIOError):
        _run(import_text(doc, default_ws_id))
    assert _run(get_dashboard("good entry", default_ws_id)) is None


def test_import_refuses_a_case_twin(default_ws_id):
    _run(upsert_dashboard("imp sales", "<p>s</p>", {}, workspace_id=default_ws_id))
    doc = yaml.safe_dump({"kind": "dashboard", "name": "Imp sales", "html": "<p>x</p>", "queries": {}})
    with pytest.raises(YamlIOError) as e:
        _run(import_text(doc, default_ws_id))
    assert e.value.status == 409
    assert _run(get_dashboard("Imp sales", default_ws_id)) is None


def test_import_refuses_twins_inside_one_bundle(default_ws_id):
    entries = [{"name": n, "html": "<p>x</p>", "queries": {}} for n in ("imp A", "imp a")]
    with pytest.raises(YamlIOError) as e:
        _run(import_text(yaml.safe_dump({"kind": "workspace", "dashboards": entries}), default_ws_id))
    assert e.value.status == 409
    assert _run(get_dashboard("imp A", default_ws_id)) is None and _run(get_dashboard("imp a", default_ws_id)) is None


_ORDERS = {"connection": "warehouse", "sql": "SELECT 1"}


def test_dashboard_from_data_entries():
    from_data = lambda q: dashboard_from_data({"name": "d", "html": "<p>", "queries": q})  # noqa: E731
    assert from_data({"orders": _ORDERS})["queries"] == {"orders": _ORDERS}
    with pytest.raises(YamlIOError, match="query 'orders': connection must be a non-empty string"):
        from_data({"orders": {"sql": "SELECT 1"}})
    with pytest.raises(YamlIOError, match=MIXED):
        from_data({"orders": _ORDERS, "sales": "SELECT 1"})
    plain = {"name": "d", "html": "<p>", "queries": {"sales": "SELECT 1"}, "params": []}
    assert dashboard_to_data(dashboard_from_data(plain)) == {
        "name": "d",
        "html": "<p>",
        "queries": {"sales": "SELECT 1"},
    }
