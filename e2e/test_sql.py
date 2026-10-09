"""The Queries page (`/sql`): a flat SQL textbox that runs a `;`-separated
script as written — writes included — a log line per statement and, when the
last statement returned rows, a results table and an Open-in-QueryView button,
parameterized across every driver (same seeds as test_drivers)."""

from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page, expect
from test_drivers import CASES, DriverCase, _connect

# A table the write round-trip creates: unique per run, so parallel workers
# sharing one database server never collide; the test drops it at the end.
_DDL = {
    "clickhouse": "CREATE TABLE {t} (id UInt32, name String) ENGINE = MergeTree ORDER BY id",
    "postgres": "CREATE TABLE {t} (id integer, name text)",
    "duckdb": "CREATE TABLE {t} (id INTEGER, name TEXT)",
}

DUCK = next(c for c in CASES if c.id == "duckdb")


def _open_sql_page(page: Page) -> None:
    page.get_by_test_id("nav-sql").click()
    expect(page.get_by_test_id("sql-page")).to_be_visible()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_run_all_writes_and_shows_the_last_select(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)
    _open_sql_page(page)

    table = f"qv_sql_{uuid.uuid4().hex[:8]}"
    select = f"SELECT id, name FROM {table} ORDER BY id"
    script = (
        f"{_DDL[case.id].format(t=table)};\nINSERT INTO {table} (id, name) VALUES (1, 'one'), (2, 'two');\n{select}"
    )
    page.get_by_test_id("sql-input").fill(script)
    # Nothing has run yet: no rows to hand to QueryView.
    expect(page.get_by_test_id("sql-open-queryview")).to_be_disabled()
    shot(f"{case.id} script typed")
    page.get_by_test_id("sql-run-all").click()

    # One log line per statement; DDL/DML carry a status, the SELECT its count.
    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(3)
    expect(results.nth(0)).to_contain_text("CREATE TABLE")
    expect(results.nth(0).get_by_test_id("sql-result-status")).to_contain_text("ms")
    expect(results.nth(1).get_by_test_id("sql-result-status")).to_contain_text("ms")
    expect(results.nth(2).get_by_test_id("sql-result-status")).to_contain_text("2 rows")
    # The last statement returned rows: they're the table below the textbox.
    output = page.get_by_test_id("sql-output")
    expect(output.locator("table thead th")).to_contain_text(["id", "name"])
    expect(output).to_contain_text("one")
    expect(output).to_contain_text("two")
    shot(f"{case.id} script results")

    # Open in QueryView carries that SELECT over.
    page.get_by_test_id("sql-open-queryview").click()
    expect(page.get_by_test_id("query-panel")).to_be_visible()
    expect(page.get_by_test_id("query-input")).to_have_value(select)
    shot(f"{case.id} opened in QueryView")

    # Back on Queries the script is still there; run just the DROP under the cursor.
    _open_sql_page(page)
    textarea = page.get_by_test_id("sql-input")
    expect(textarea).to_have_value(script)
    textarea.focus()
    textarea.press("End")  # the cursor lands at the very end after focus
    textarea.press("Control+End")
    textarea.type(f";\nDROP TABLE {table}")
    page.get_by_test_id("sql-run-current").click()
    expect(results).to_have_count(1)
    expect(results.nth(0)).to_contain_text("DROP TABLE")
    expect(page.get_by_test_id("sql-output")).to_have_count(0)


def test_run_all_stops_at_the_first_failing_statement(seeded_duckdb, page: Page, shot) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_sql_page(page)

    page.get_by_test_id("sql-input").fill("SELECT 1 AS a; SELECT * FROM no_such_table; SELECT 2 AS b")
    page.get_by_test_id("sql-input").press("ControlOrMeta+Shift+Enter")

    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(2)
    expect(results.nth(0).get_by_test_id("sql-result-status")).to_contain_text("1 row")
    expect(results.nth(1).get_by_test_id("sql-result-error")).to_contain_text("no_such_table")
    # The last statement run failed, so there is no table to show.
    expect(page.get_by_test_id("sql-output")).to_have_count(0)
    expect(page.get_by_test_id("sql-open-queryview")).to_be_disabled()
    shot("error stops the script")


def test_run_current_runs_the_statement_under_the_cursor(seeded_duckdb, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_sql_page(page)

    textarea = page.get_by_test_id("sql-input")
    textarea.fill("SELECT 1 AS a;\nSELECT * FROM no_such_table;\nSELECT 2 AS b")
    # Put the cursor inside the last statement and run it alone.
    textarea.evaluate("el => el.setSelectionRange(el.value.length - 3, el.value.length - 3)")
    textarea.press("ControlOrMeta+Enter")
    results = page.get_by_test_id("sql-result")
    expect(results).to_have_count(1)
    expect(results.nth(0)).to_contain_text("SELECT 2 AS b")
    expect(page.get_by_test_id("sql-output").locator("table thead th")).to_contain_text(["b"])

    # A selection wins over the cursor.
    textarea.evaluate("el => el.setSelectionRange(0, el.value.indexOf(';'))")
    page.get_by_test_id("sql-run-current").click()
    expect(results).to_have_count(1)
    expect(results.nth(0)).to_contain_text("SELECT 1 AS a")


def test_sql_text_is_remembered_and_results_are_not(seeded_duckdb, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_sql_page(page)

    script = "SELECT 1 AS a;\nSELECT 2 AS b"
    textarea = page.get_by_test_id("sql-input")
    textarea.fill(script)
    page.get_by_test_id("sql-run-all").click()
    expect(page.get_by_test_id("sql-result")).to_have_count(2)

    textarea.blur()
    page.reload(wait_until="networkidle")
    expect(page.get_by_test_id("sql-input")).to_have_value(script)
    expect(page.get_by_test_id("sql-result")).to_have_count(0)
