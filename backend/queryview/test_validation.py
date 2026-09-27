from queryview.validation import MAX_LIMIT, cell_view_error, clamp_paging, presentation_error


def test_none_inputs_are_valid():
    assert presentation_error(None, None) is None


def test_valid_order_by_and_fields():
    assert presentation_error([{"name": "id", "dir": "DESC"}], ["id", "name"]) is None
    assert presentation_error([{"name": "id", "dir": "asc"}], None) is None  # case-insensitive


def test_bad_direction_rejected():
    msg = presentation_error([{"name": "id", "dir": "SIDEWAYS"}], None)
    assert msg is not None and "dir" in msg


def test_missing_name_rejected():
    assert presentation_error([{"dir": "ASC"}], None) is not None


def test_backtick_in_name_rejected():
    assert presentation_error([{"name": "a`b", "dir": "ASC"}], None) is not None


def test_non_list_order_by_rejected():
    assert presentation_error("id DESC", None) is not None


def test_non_string_field_rejected():
    assert presentation_error(None, ["ok", 3]) is not None
    assert presentation_error(None, ["ok", ""]) is not None


def test_cell_view_absent_or_empty_is_valid():
    assert cell_view_error(None) is None
    assert cell_view_error("") is None
    assert cell_view_error("   \n") is None
    assert cell_view_error("---\n") is None  # empty document


def test_cell_view_valid_entries_and_params():
    doc = (
        "cve_id:\n"
        "  type: link\n"
        "  value: https://nvd.nist.gov/vuln/detail/{cell}\n"
        "status:\n"
        "  type: custom\n"
        "  value: <strong>{cell}</strong>\n"
        "params:\n"
        "  - name: env\n"
        "    options: [prod, staging]\n"
        "  - name: host\n"
        "    options_sql: SELECT DISTINCT host FROM t\n"
    )
    assert cell_view_error(doc) is None


def test_cell_view_rejects_unparsable_yaml_and_non_mapping():
    assert cell_view_error("col: [unclosed\n") is not None
    assert cell_view_error("- a list\n") is not None
    assert cell_view_error("just a scalar") is not None
    assert cell_view_error(42) is not None  # not YAML text at all


def test_cell_view_rejects_bad_entries():
    assert cell_view_error("col: not a mapping\n") is not None
    assert cell_view_error("col:\n  type: lnik\n  value: x\n") is not None  # typo'd type
    assert cell_view_error("col:\n  type: link\n") is not None  # missing value
    assert cell_view_error("col:\n  type: link\n  value: ''\n") is not None


def test_cell_view_rejects_bad_params():
    assert cell_view_error("params: notalist\n") is not None
    assert cell_view_error("params:\n  - options: [a]\n") is not None  # no name
    # options and options_sql are mutually exclusive; one is required
    assert cell_view_error("params:\n  - name: p\n") is not None
    assert cell_view_error("params:\n  - name: p\n    options: [a]\n    options_sql: SELECT 1\n") is not None
    assert cell_view_error("params:\n  - name: p\n    options: []\n") is not None
    assert cell_view_error("params:\n  - name: p\n    options: [{a: b}]\n") is not None


def test_clamp_paging():
    assert clamp_paging(50, 10) == (50, 10)
    assert clamp_paging(-5, -5) == (0, 0)
    assert clamp_paging(MAX_LIMIT + 1, 0) == (MAX_LIMIT, 0)
    assert clamp_paging("x", None) == (100, 0)


def test_dashboard_params_rules():
    from queryview.validation import dashboard_params_error

    assert dashboard_params_error(None) is None
    assert dashboard_params_error([{"name": "d", "kind": "dimension"}]) is None  # a checkbox: no options
    assert (
        dashboard_params_error([{"name": "t", "kind": "identifier", "options_sql": "SELECT 1", "default": "none"}])
        is None
    )
    assert "kind" in (dashboard_params_error([{"name": "x", "kind": "nope", "options": ["a"]}]) or "")
    assert "default" in (dashboard_params_error([{"name": "x", "options": ["a"], "default": "a"}]) or "")
    assert "exactly one" in (dashboard_params_error([{"name": "x"}]) or "")  # a value param needs options
