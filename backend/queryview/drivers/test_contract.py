"""Driver contract, parameterized across every registered driver. Adding a
driver to the registry (with a SAMPLES entry) automatically extends these
checks. Driver-specific behavior (dialect SQL, real-DB queries) lives in the
per-driver test modules."""

from __future__ import annotations

import asyncio
import inspect
import typing
from dataclasses import dataclass
from typing import Any

import pytest

from queryview.drivers import DRIVERS, Driver
from queryview.drivers.base import DatabasesResult, Err, FieldsResult, RowsResult, TablesResult, TextResult
from queryview.drivers.clickhouse import ChConfig
from queryview.drivers.duckdb import DuckConfig
from queryview.drivers.mysql import MySqlConfig
from queryview.drivers.postgres import PgConfig
from queryview.drivers.sqlite import SqliteConfig


@dataclass
class DriverSample:
    config: Any  # a representative config object
    valid_body: dict  # a request body that parses to `config`
    requires_database: bool


# One sample per driver `type`. A network driver is identified by a `host` field
# in its valid body (so host/port validation checks auto-apply to it).
SAMPLES: dict[str, DriverSample] = {
    "clickhouse": DriverSample(
        ChConfig("h", 8123, "u", "p"),
        {"host": "h", "port": "8123", "username": "u", "password": "p"},
        requires_database=True,
    ),
    "postgres": DriverSample(
        PgConfig("h", 5432, "u", "p"),
        {"host": "h", "port": "5432", "username": "u", "password": "p"},
        requires_database=True,
    ),
    "mysql": DriverSample(
        MySqlConfig("h", 3306, "u", "p"),
        {"host": "h", "port": "3306", "username": "u", "password": "p"},
        requires_database=True,
    ),
    "duckdb": DriverSample(
        DuckConfig("/tmp/x.duckdb"),
        {"path": "/tmp/x.duckdb"},
        requires_database=False,
    ),
    "sqlite": DriverSample(
        SqliteConfig("/tmp/x.sqlite"),
        {"path": "/tmp/x.sqlite"},
        requires_database=False,
    ),
}

ALL = sorted(DRIVERS)
NETWORK = sorted(t for t, s in SAMPLES.items() if "host" in s.valid_body)


def test_samples_cover_every_registered_driver():
    assert set(SAMPLES) == set(DRIVERS), "add a SAMPLES entry for each driver"


@pytest.mark.parametrize("type_", ALL)
def test_protocol_type_and_requires_database(type_):
    d = DRIVERS[type_]
    assert isinstance(d, Driver)
    assert d.type == type_
    assert d.requires_database is SAMPLES[type_].requires_database


@pytest.mark.parametrize("type_", ALL)
def test_parse_valid_body_and_config_round_trip(type_):
    d = DRIVERS[type_]
    sample = SAMPLES[type_]
    parsed, err = d.parse_config(sample.valid_body)
    assert err is None and parsed == sample.config
    assert d.config_from_dict(d.config_to_dict(sample.config)) == sample.config


@pytest.mark.parametrize("type_", NETWORK)
def test_network_driver_rejects_missing_host_and_bad_port(type_):
    d = DRIVERS[type_]
    assert d.parse_config({"port": 5432})[0] is None  # missing host
    assert d.parse_config({"host": "h", "port": 0})[0] is None  # port too low
    assert d.parse_config({"host": "h", "port": 99999})[0] is None  # too high
    assert d.parse_config({"host": "h", "port": "x"})[0] is None  # non-numeric


RESULT_OF = {
    "list_databases": DatabasesResult,
    "list_tables": TablesResult,
    "run_query": RowsResult,
    "export_csv": TextResult,
    "describe_query": FieldsResult,
}


@pytest.mark.parametrize("method", sorted(RESULT_OF))
@pytest.mark.parametrize("type_", ALL)
def test_query_methods_are_annotated_named_result_or_err(type_, method):
    # One shape per method across every driver: callers narrow with isinstance(r, Err).
    fn = getattr(type(DRIVERS[type_]), method)
    hints = typing.get_type_hints(fn)
    assert set(typing.get_args(hints["return"])) == {RESULT_OF[method], Err}, hints["return"]


@pytest.mark.parametrize("type_", ALL)
def test_list_tables_accepts_union_flag(type_):
    # The Explorer's union-by-name flag reaches every driver; only DuckDB's
    # folder mode acts on it.
    assert "union" in inspect.signature(DRIVERS[type_].list_tables).parameters
    # ...and the Explorer's Max entries, which caps DuckDB folder mode's lists.
    assert "limit" in inspect.signature(DRIVERS[type_].list_tables).parameters
    assert "limit" in inspect.signature(DRIVERS[type_].list_databases).parameters
    assert "current" in inspect.signature(DRIVERS[type_].list_databases).parameters


# MySQL builds its SQL after connecting: test_mysql.py checks it on a fake connection.
@pytest.mark.parametrize("method", ["run_query", "export_csv"])
@pytest.mark.parametrize("type_", [t for t in ALL if t != "mysql"])
def test_sorting_by_a_name_with_the_quote_character_is_an_error(type_, method):
    """Not a silent skip: the rows would come back unsorted under a sorted header."""
    d = DRIVERS[type_]
    order_by = [{"name": f"a{d.ident_quote}b", "dir": "ASC"}]
    r = asyncio.run(getattr(d, method)(SAMPLES[type_].config, "SELECT 1", None, 10, 0, order_by))
    assert isinstance(r, Err) and "cannot sort by" in r.message, r
