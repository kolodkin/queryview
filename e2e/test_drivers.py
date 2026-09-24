"""The connect -> (pick db) -> query -> paginate -> CSV -> describe flow,
parameterized across every driver. Each case names the driver's command, form
testids, seeding fixture, and whether it has a database picker. Driver-specific
ClickHouse features (cell views, params, complex types) live in test_query.py."""

from __future__ import annotations

import dataclasses

import pytest
from conftest import open_queries, open_query_panel
from playwright.sync_api import Page, expect


@dataclasses.dataclass
class DriverCase:
    id: str
    command: str  # prompt command, e.g. "new postgres"
    form_testid: str  # connection form testid
    connect_testid: str  # the Connect button testid
    seed_fixture: str  # conftest fixture that seeds an `items` table
    status_text: str  # expected connection-status text after connecting
    path_field: str | None = None  # a file-path field to fill with the seed value
    db_option: str | None = None  # picker option to click, or None for no picker


# Every case seeds the same `items(id, name)` table with alpha/beta/gamma so the
# query body and assertions below are shared verbatim.
CASES = [
    DriverCase(
        "clickhouse",
        "new clickhouse",
        "clickhouse-form",
        "ch-connect",
        "seeded_test_db",
        "connected - test",
        db_option="test",
    ),
    DriverCase(
        "postgres",
        "new postgres",
        "postgres-form",
        "pg-connect",
        "seeded_pg_db",
        "connected - qvtest",
        db_option="qvtest",
    ),
    DriverCase(
        "duckdb",
        "new duckdb",
        "duckdb-form",
        "duck-connect",
        "seeded_duckdb",
        "connected - duckdb",
        path_field="duck-path",
    ),
]


def _connect(page: Page, case: DriverCase, seed) -> None:
    open_queries(page)
    page.get_by_test_id("prompt-input").fill(case.command)
    page.keyboard.press("Enter")
    expect(page.get_by_test_id(case.form_testid)).to_be_visible()
    if case.path_field:
        page.get_by_test_id(case.path_field).fill(seed)
    page.get_by_test_id(case.connect_testid).click()
    # The status pill can already read "connected" from the session the shell
    # auto-resumed on load (the previous test's saved connection), so wait for
    # the form to close: only the connect response's handler dismisses it, and
    # that same handler resets the prompt.
    expect(page.get_by_test_id(case.form_testid)).to_have_count(0)
    if case.db_option:
        expect(page.get_by_test_id("db-picker")).to_be_visible()
        page.locator(f'[data-db="{case.db_option}"]').click()
    else:
        # Picker-less driver (DuckDB): connecting goes straight to ready.
        expect(page.get_by_test_id("db-picker")).to_have_count(0)
    expect(page.get_by_test_id("connection-status")).to_contain_text(case.status_text)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_connect_query_paginate_csv(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)
    shot(f"{case.id} connected")
    open_query_panel(page)

    sql = "SELECT id, name FROM items ORDER BY id"
    page.get_by_test_id("query-input").fill(sql)

    # Predefined save/load round-trip (driver-agnostic; queries are keyed by type).
    select = page.get_by_test_id("query-predefined-select")
    page.once("dialog", lambda d: d.accept("all items"))
    select.select_option("::new::")
    page.get_by_test_id("query-save").click()
    expect(select.locator('option[value="all items"]')).to_have_count(1)
    select.select_option("")
    page.get_by_test_id("query-input").fill("")
    select.select_option("all items")
    expect(page.get_by_test_id("query-input")).to_have_value(sql)
    shot(f"{case.id} saved predefined query")

    # Pagination: limit 2 -> first page is alpha, beta (not gamma).
    page.get_by_test_id("query-limit").fill("2")
    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    # Two columns: assert each header in order (a bare string would trip
    # Playwright strict mode on the multi-element locator).
    expect(output.locator("table thead th")).to_contain_text(["id", "name"])
    expect(output).to_contain_text("alpha")
    expect(output).to_contain_text("beta")
    expect(output).not_to_contain_text("gamma")
    shot(f"{case.id} results page 1")

    # CSV download of the current page.
    with page.expect_download() as dl_info:
        page.get_by_test_id("query-csv").click()
    csv_text = open(dl_info.value.path(), encoding="utf-8").read()
    assert "name" in csv_text and "alpha" in csv_text

    # Next page: gamma (not alpha).
    page.get_by_test_id("query-next").click()
    expect(output).to_contain_text("gamma")
    expect(output).not_to_contain_text("alpha")
    shot(f"{case.id} results page 2")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_fields_describe(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT id, name FROM items")
    page.get_by_test_id("query-fields").click()
    expect(page.get_by_test_id("field-pickers")).to_be_visible()
    expect(page.get_by_test_id("fields-count")).to_have_text("2/2")
    page.get_by_test_id("fields-menu").click()
    expect(page.locator('[data-testid="field-toggle"]')).to_have_count(2)
    expect(page.locator('[data-testid="field-toggle"][data-col="id"]')).to_be_visible()
    expect(page.locator('[data-testid="field-toggle"][data-col="name"]')).to_be_visible()
    shot(f"{case.id} describe fields")
