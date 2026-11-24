from queryview.validation import dashboard_params_error, page_bounds


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
    assert dashboard_params_error(twice) == "invalid params[1] 'col' is declared twice"


def test_page_bounds():
    assert page_bounds(50, 10) == (50, 10)
    assert page_bounds(0, -5) == (100, 0)
    assert page_bounds(5000, "7") == (1000, 7)
    assert page_bounds(True, [1]) == (100, 0)


def test_dashboard_params_errors_name_the_param():
    def err(**entry):
        return dashboard_params_error([{"name": "region", **entry}])

    assert err(kind="dropdown") == "invalid params[0] 'region' kind must be one of value, identifier, dimension, text"
    assert err() == "invalid params[0] 'region' must declare exactly one of options or options_sql"
    assert err(options=[]) == "invalid params[0] 'region' options must be a non-empty list"
    assert err(options=["a"], default="x") == "invalid params[0] 'region' default must be 'none' when given"
    assert err(kind="text", options=["a"]) == "invalid params[0] 'region' a text param takes no options"
    # No usable name to show.
    assert dashboard_params_error([{"kind": "dropdown"}]) == "invalid params[0] name must be a non-empty string"
