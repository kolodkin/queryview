from queryview.validation import MAX_LIMIT, clamp_paging


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


def test_dashboard_params_selector_rules():
    """The selector rules a value/identifier param shares: a name and exactly
    one non-empty source of options."""
    from queryview.validation import dashboard_params_error

    assert dashboard_params_error([{"name": "env", "options": ["prod", "staging"]}]) is None
    assert dashboard_params_error("notalist") is not None
    assert dashboard_params_error(["not a mapping"]) is not None
    assert dashboard_params_error([{"options": ["a"]}]) is not None  # no name
    assert dashboard_params_error([{"name": "p", "options": ["a"], "options_sql": "SELECT 1"}]) is not None
    assert dashboard_params_error([{"name": "p", "options_sql": "  "}]) is not None
    assert dashboard_params_error([{"name": "p", "options": []}]) is not None
    assert dashboard_params_error([{"name": "p", "options": [{"a": "b"}]}]) is not None
