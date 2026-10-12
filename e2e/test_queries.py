"""The Queries page (`/queries`): a flat SQL textbox that runs a `;`-separated
script as written — writes included — leaving one status line and, when the
last statement returned rows, a results table and an Open-in-QueryView button,
parameterized across every driver (same seeds as test_drivers)."""

from __future__ import annotations

import uuid

import pytest
from conftest import CH_DB, PG_DB, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER, _ch_exec
from playwright.sync_api import Page, expect
from test_drivers import CASES, DriverCase, _connect

# A table the write round-trip creates: unique per run, so parallel workers
# sharing one database server never collide; _drop_table cleans it up.
_DDL = {
    "clickhouse": "CREATE TABLE {t} (id UInt32, name String) ENGINE = MergeTree ORDER BY id",
    "postgres": "CREATE TABLE {t} (id integer, name text)",
    "duckdb": "CREATE TABLE {t} (id INTEGER, name TEXT)",
}
# A temporary table: it lives on the run's connection (ClickHouse: its session).
_TEMP_DDL = {
    "clickhouse": "CREATE TEMPORARY TABLE {t} (x UInt8)",
    "postgres": "CREATE TEMP TABLE {t} (x integer)",
    "duckdb": "CREATE TEMP TABLE {t} (x INTEGER)",
}

DUCK = next(c for c in CASES if c.id == "duckdb")


def _drop_table(case: DriverCase, seed: str, table: str) -> None:
    """Drop a table the test created, straight on the server, whatever state
    the UI was left in."""
    if case.id == "clickhouse":
        _ch_exec(f"DROP TABLE IF EXISTS {CH_DB}.{table}")
    elif case.id == "postgres":
        import asyncio
        import concurrent.futures

        import asyncpg

        async def _go():
            conn = await asyncpg.connect(
                host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD or None, database=PG_DB
            )
            try:
                await conn.execute(f"DROP TABLE IF EXISTS {table}")
            finally:
                await conn.close()

        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            pool.submit(asyncio.run, _go()).result()
    else:
        import duckdb

        con = duckdb.connect(seed)
        try:
            con.execute(f"DROP TABLE IF EXISTS {table}")
        finally:
            con.close()


def _open_queries_page(page: Page) -> None:
    page.get_by_test_id("nav-queries").click()
    expect(page.get_by_test_id("queries-page")).to_be_visible()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_run_all_writes_and_shows_the_last_select(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    table = f"qv_sql_{uuid.uuid4().hex[:8]}"
    request.addfinalizer(lambda: _drop_table(case, seed, table))
    _connect(page, case, seed)
    _open_queries_page(page)

    select = f"SELECT id, name FROM {table} ORDER BY id"
    script = (
        f"{_DDL[case.id].format(t=table)};\nINSERT INTO {table} (id, name) VALUES (1, 'one'), (2, 'two');\n{select}"
    )
    page.get_by_test_id("queries-input").fill(script)
    # Nothing has run yet: no rows to hand to QueryView.
    expect(page.get_by_test_id("queries-open-queryview")).to_be_disabled()
    shot(f"{case.id} script typed")
    page.get_by_test_id("queries-run-all").click()

    # One status line for the run: how much ran, what the last statement left.
    status = page.get_by_test_id("queries-status")
    expect(status).to_contain_text("3 statements")
    expect(status).to_contain_text("2 rows")
    expect(status).to_contain_text("ms")
    # The last statement returned rows: they're the table below the textbox.
    output = page.get_by_test_id("queries-output")
    expect(output.locator("table thead th")).to_contain_text(["id", "name"])
    expect(output).to_contain_text("one")
    expect(output).to_contain_text("two")
    shot(f"{case.id} script results")

    # Open in QueryView carries that SELECT over.
    page.get_by_test_id("queries-open-queryview").click()
    expect(page.get_by_test_id("query-panel")).to_be_visible()
    expect(page.get_by_test_id("query-input")).to_have_value(select)
    shot(f"{case.id} opened in QueryView")

    # Back on Queries the script is still there; run just the DROP under the cursor.
    _open_queries_page(page)
    textarea = page.get_by_test_id("queries-input")
    expect(textarea).to_have_value(script)
    textarea.focus()
    textarea.press("End")  # the cursor lands at the very end after focus
    textarea.press("Control+End")
    textarea.type(f";\nDROP TABLE {table}")
    page.get_by_test_id("queries-run-current").click()
    expect(status).not_to_contain_text("statements")
    expect(status).to_contain_text("ms")
    expect(page.get_by_test_id("queries-output")).to_have_count(0)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_statements_share_the_runs_connection(case: DriverCase, request, page: Page) -> None:
    """A temporary table made by one statement is there for the next: the run
    is one connection (one server session on ClickHouse)."""
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)
    _open_queries_page(page)

    table = f"qv_tmp_{uuid.uuid4().hex[:8]}"
    page.get_by_test_id("queries-input").fill(
        f"{_TEMP_DDL[case.id].format(t=table)}; INSERT INTO {table} VALUES (7); SELECT x FROM {table}"
    )
    page.get_by_test_id("queries-run-all").click()
    expect(page.get_by_test_id("queries-status")).to_contain_text("3 statements · 1 row")
    expect(page.get_by_test_id("queries-output")).to_contain_text("7")


def test_clickhouse_row_cap_leaves_subqueries_alone(seeded_test_db, page: Page) -> None:
    """The cap is a setting on the ClickHouse session; it must bound only the
    statement's own result, never what a subquery feeds it."""
    _connect(page, CASES[0], seeded_test_db)
    _open_queries_page(page)

    page.get_by_test_id("queries-input").fill("SELECT count() AS n FROM (SELECT number FROM numbers(200000))")
    page.get_by_test_id("queries-run-all").click()
    expect(page.get_by_test_id("queries-output")).to_contain_text("200000")


def test_run_all_stops_at_the_first_failing_statement(seeded_duckdb, page: Page, shot) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_queries_page(page)

    page.get_by_test_id("queries-input").fill("SELECT 1 AS a; SELECT * FROM no_such_table; SELECT 2 AS b")
    page.get_by_test_id("queries-input").press("ControlOrMeta+Shift+Enter")

    # The second statement failed: the line says which and why, and the
    # statement itself is marked red in the textbox.
    status = page.get_by_test_id("queries-status")
    expect(status).to_have_attribute("data-ok", "false")
    expect(status).to_contain_text("Statement #2 Failed - ")
    expect(status).to_contain_text("no_such_table")
    expect(status).not_to_contain_text("SELECT * FROM no_such_table")
    mark = page.get_by_test_id("queries-failed-mark")
    expect(mark).to_have_text("SELECT * FROM no_such_table")
    shot("failing statement marked")
    # Clicking into the textbox (to fix it) clears the mark — a keyboard run
    # leaves the focus there, so a click or a keystroke is what clears it.
    page.get_by_test_id("queries-input").click()
    expect(mark).to_have_count(0)
    # The last statement run failed, so there is no table to show.
    expect(page.get_by_test_id("queries-output")).to_have_count(0)
    expect(page.get_by_test_id("queries-open-queryview")).to_be_disabled()


def test_run_current_runs_the_statement_under_the_cursor(seeded_duckdb, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_queries_page(page)

    textarea = page.get_by_test_id("queries-input")
    textarea.fill("SELECT 1 AS a;\nSELECT * FROM no_such_table;\nSELECT 2 AS b")
    # Put the cursor inside the last statement and run it alone.
    textarea.evaluate("el => el.setSelectionRange(el.value.length - 3, el.value.length - 3)")
    textarea.press("ControlOrMeta+Enter")
    status = page.get_by_test_id("queries-status")
    expect(status).to_contain_text("1 row")
    expect(page.get_by_test_id("queries-output").locator("table thead th")).to_contain_text(["b"])

    # A selection wins over the cursor.
    textarea.evaluate("el => el.setSelectionRange(0, el.value.indexOf(';'))")
    page.get_by_test_id("queries-run-current").click()
    expect(page.get_by_test_id("queries-output").locator("table thead th")).to_contain_text(["a"])


def test_sql_text_is_remembered_and_results_are_not(seeded_duckdb, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    _open_queries_page(page)

    script = "SELECT 1 AS a;\nSELECT 2 AS b"
    textarea = page.get_by_test_id("queries-input")
    textarea.fill(script)
    page.get_by_test_id("queries-run-all").click()
    expect(page.get_by_test_id("queries-status")).to_contain_text("2 statements")

    textarea.blur()
    page.reload(wait_until="networkidle")
    expect(page.get_by_test_id("queries-input")).to_have_value(script)
    expect(page.get_by_test_id("queries-status")).to_have_count(0)
    expect(page.get_by_test_id("queries-output")).to_have_count(0)


def test_textarea_sizes_collapse_and_expand(seeded_duckdb, page: Page, shot) -> None:
    """Min collapses the textbox so the results get the room; the other steps
    set its height in rows. The text survives every step."""
    _connect(page, DUCK, seeded_duckdb)
    _open_queries_page(page)

    textarea = page.get_by_test_id("queries-input")
    textarea.fill("SELECT 1 AS a")
    page.get_by_test_id("queries-run-all").click()
    expect(page.get_by_test_id("queries-output")).to_be_visible()

    page.get_by_test_id("queries-size-min").click()
    box = textarea.bounding_box()
    assert box is not None and box["height"] < 4  # just its (transparent) border
    expect(page.get_by_test_id("queries-output")).to_be_visible()
    shot("textbox collapsed")

    page.get_by_test_id("queries-size-xl").click()
    expect(textarea).to_have_attribute("rows", "28")
    expect(textarea).to_have_value("SELECT 1 AS a")
