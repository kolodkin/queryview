from queryview.validation import MAX_LIMIT, clamp_paging, dashboard_params_error


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
    # text: free input, an optional default string, never an option list
    assert dashboard_params_error([{"name": "t", "kind": "text"}]) is None
    assert dashboard_params_error([{"name": "t", "kind": "text", "default": "abc"}]) is None
    assert dashboard_params_error([{"name": "t", "kind": "text", "default": None}]) is None  # a blank `default:`
    assert "options" in (dashboard_params_error([{"name": "t", "kind": "text", "options": ["a"]}]) or "")
    assert "default" in (dashboard_params_error([{"name": "t", "kind": "text", "default": 3}]) or "")
    assert "name" in (dashboard_params_error([{"kind": "text"}]) or "")


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


def test_dashboard_params_rejects_a_name_declared_twice():
    twice = [{"name": "col", "kind": "text"}, {"name": "col", "kind": "identifier", "options": ["city"]}]
    assert dashboard_params_error(twice) == "invalid params[1] name 'col' is declared twice"


def test_an_each_param_is_a_list_with_no_default():
    assert dashboard_params_error([{"name": "region", "kind": "each", "options": ["eu"]}]) is None
    assert dashboard_params_error([{"name": "region", "kind": "each"}]) is not None
    with_default = [{"name": "region", "kind": "each", "options": ["eu"], "default": "none"}]
    assert "takes no default" in str(dashboard_params_error(with_default))


def test_an_each_param_is_checked_when_pushed():
    many = [{"name": "n", "kind": "each", "options": list(range(101))}]
    assert "no more than 100 options" in str(dashboard_params_error(many))
    used = [
        {"name": "region", "kind": "each", "options": ["eu"]},
        {"name": "city", "options_sql": "SELECT city FROM t WHERE region = {region}"},
    ]
    assert "cannot use the each param region" in str(dashboard_params_error(used))
