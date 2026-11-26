"""dashboard_entries: the entry shapes, the strict and lenient checks, and the one-kind rule."""

from __future__ import annotations

import pytest

from queryview.dashboard_entries import clean_queries, entry_connection, entry_sql, is_federated, queries_error

ORDERS = {"connection": "warehouse", "sql": "SELECT 1"}


def test_a_string_and_a_map_are_both_entries():
    assert queries_error({"sales": "SELECT 1", "orders": ORDERS, "blank": ""}) is None
    assert entry_sql("SELECT 1") == entry_sql(ORDERS) == "SELECT 1"
    assert entry_connection("SELECT 1") is None
    assert entry_connection(ORDERS) == ("warehouse", None)
    assert entry_connection({**ORDERS, "database": "reporting"}) == ("warehouse", "reporting")


@pytest.mark.parametrize(
    "entry, why",
    [
        ({"connection": "warehouse"}, "sql must be a non-empty string"),
        ({"connection": "warehouse", "sql": " "}, "sql must be a non-empty string"),
        ({"sql": "SELECT 1"}, "connection must be a non-empty string"),
        ({**ORDERS, "connection": 5}, "connection must be a non-empty string"),
        ({**ORDERS, "database": ""}, "database must be a non-empty string"),
        ({**ORDERS, "limit": 5}, "unknown key 'limit'"),
    ],
)
def test_a_malformed_map_is_named(entry, why):
    assert queries_error({"orders": entry}) == f"query 'orders': {why}"


@pytest.mark.parametrize("raw", [None, [], {"q": 5}, {"q": ["SELECT 1"]}, {5: "SELECT 1"}])
def test_anything_else_is_not_a_queries_map(raw):
    assert queries_error(raw) == "queries must be a {name: SQL} map"


def test_a_dashboard_is_one_kind():
    assert is_federated({"orders": ORDERS}, [{"name": "r", "options_sql": "SELECT r", "connection": "warehouse"}])
    assert not is_federated({"sales": "SELECT 1"}, [{"name": "r", "options_sql": "SELECT r"}])
    assert not is_federated({}, [{"name": "r", "options": ["a"]}])
    for queries, params in [
        ({"sales": "SELECT 1", "orders": ORDERS}, []),
        ({"orders": ORDERS}, [{"name": "r", "options_sql": "SELECT r"}]),
        ({"sales": "SELECT 1"}, [{"name": "r", "options_sql": "SELECT r", "connection": "warehouse"}]),
    ]:
        with pytest.raises(ValueError, match="names a connection, or none does"):
            is_federated(queries, params)


def test_cleaning_keeps_what_can_run():
    raw = {"sales": "SELECT 1", "blank": " ", "orders": ORDERS, "bad": {"sql": "SELECT 1"}, "n": 5, "": "SELECT 1"}
    assert clean_queries(raw) == {"sales": "SELECT 1", "orders": ORDERS}
    assert clean_queries("nope") == {}
