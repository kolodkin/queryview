"""The Queries page (`/sql`): a flat SQL textbox that runs a `;`-separated
script as written — writes included — one result block per statement,
parameterized across every driver (same seeds as test_drivers)."""

from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page, expect
from test_drivers import CASES, DriverCase, _connect

# A table the write round-trip creates: unique per run, so parallel workers
# sharing one database server never collide, and dropped by the script itself.
_DDL = {
    "clickhouse": "CREATE TABLE {t} (id UInt32, name String) ENGINE = MergeTree ORDER BY id",
    "postgres": "CREATE TABLE {t} (id integer, name text)",
    "duckdb": "CREATE TABLE {t} (id INTEGER, name TEXT)",
}


def _open_sql_page(page: Page) -> None:
    page.get_by_test_id("nav-sql").click()
    expect(page.get_by_test_id("sql-page")).to_be_visible()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_script_runs_each_statement_and_writes(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)
    _open_sql_page(page)

    table = f"qv_sql_{uuid.uuid4().hex[:8]}"
    script = (
        f"{_DDL[case.id].format(t=table)};\n"
        f"INSERT INTO {table} (id, name) VALUES (1, 'one'), (2, 'two');\n"
        f"SELECT id, name FROM {table} ORDER BY id;\n"
        f"DROP TABLE {table}"
    )
    page.get_by_test_id("sql-input").fill(script)
    shot(f"{case.id} script typed")
    page.get_by_test_id("sql-run").click()

    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(4)
    # DDL/DML blocks carry a status, the SELECT its rows, each with the statement.
    expect(results.nth(0)).to_contain_text("CREATE TABLE")
    expect(results.nth(0).get_by_test_id("sql-result-status")).to_contain_text("ms")
    expect(results.nth(1).get_by_test_id("sql-result-status")).to_contain_text("ms")
    rows = results.nth(2).get_by_test_id("sql-result-rows")
    expect(rows.locator("table thead th")).to_contain_text(["id", "name"])
    expect(rows).to_contain_text("one")
    expect(rows).to_contain_text("two")
    expect(results.nth(2).get_by_test_id("sql-result-status")).to_contain_text("2 rows")
    expect(results.nth(3)).to_contain_text("DROP TABLE")
    shot(f"{case.id} script results")


def test_script_stops_at_the_first_failing_statement(seeded_duckdb, page: Page, shot) -> None:
    duck = next(c for c in CASES if c.id == "duckdb")
    _connect(page, duck, seeded_duckdb)
    _open_sql_page(page)

    page.get_by_test_id("sql-input").fill("SELECT 1 AS a; SELECT * FROM no_such_table; SELECT 2 AS b")
    page.get_by_test_id("sql-input").press("ControlOrMeta+Enter")

    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(2)
    expect(results.nth(0).get_by_test_id("sql-result-rows")).to_contain_text("1")
    expect(results.nth(1).get_by_test_id("sql-result-error")).to_contain_text("no_such_table")
    shot("error stops the script")


def test_selection_runs_alone_and_sql_is_remembered(seeded_duckdb, page: Page) -> None:
    duck = next(c for c in CASES if c.id == "duckdb")
    _connect(page, duck, seeded_duckdb)
    _open_sql_page(page)

    script = "SELECT 1 AS a;\nSELECT 2 AS b"
    textarea = page.get_by_test_id("sql-input")
    textarea.fill(script)
    # Select the second line only: Run executes just the selection.
    textarea.evaluate("el => el.setSelectionRange(el.value.indexOf('SELECT 2'), el.value.length)")
    page.get_by_test_id("sql-run").click()
    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(1)
    expect(results.nth(0)).to_contain_text("SELECT 2 AS b")

    # The text is session state; the results are not.
    textarea.blur()
    page.reload(wait_until="networkidle")
    expect(page.get_by_test_id("sql-input")).to_have_value(script)
    expect(page.get_by_test_id("sql-result")).to_have_count(0)
