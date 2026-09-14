import re

from conftest import open_queries
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

# Driver-agnostic behaviour is exercised on DuckDB: no server to stand up.
_DUCKDB = next(c for c in CASES if c.id == "duckdb")


def test_queryview_e2e(page: Page) -> None:
    # loads the app and shows the heading
    open_queries(page)
    expect(page.locator("h1")).to_have_text("QueryView")

    # typing `new clickhouse` reveals the connection form
    page.get_by_test_id("prompt-input").fill("new clickhouse")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("clickhouse-form")).to_be_visible()
    for test_id in ("ch-name", "ch-host", "ch-port", "ch-username", "ch-password"):
        expect(page.get_by_test_id(test_id)).to_be_visible()

    # test connection succeeds against the real ClickHouse
    page.get_by_test_id("ch-test").click()
    result = page.get_by_test_id("ch-result")
    expect(result).to_be_visible()
    expect(result).to_have_attribute("data-ok", "true")
    expect(result).to_contain_text("Connected")

    # connect opens the database picker
    page.get_by_test_id("ch-connect").click()
    expect(page.get_by_test_id("db-picker")).to_be_visible()
    expect(page.locator('[data-db="default"]')).to_be_visible()

    # selecting a database shows the connected indicator and, because the
    # connection is now ready, lands on the explorer
    page.locator('[data-db="default"]').click()
    expect(page.get_by_test_id("connection-indicator")).to_be_visible()
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - default")
    expect(page).to_have_url(re.compile(r"/explorer"))
    expect(page.get_by_test_id("explorer-tables")).to_be_visible()

    # reload resumes the session, then reconnect and select the system database
    page.goto("/", wait_until="networkidle")
    # Resume: came back connected to the previously selected database, and the
    # landing redirect picks the explorer over the prompt.
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - default")
    expect(page).to_have_url(re.compile(r"/explorer"))
    # `connect <name>` reopens the picker; choose a different database.
    page.get_by_test_id("nav-queries").click()
    page.get_by_test_id("prompt-input").fill("connect clickhouse")
    page.keyboard.press("Enter")
    # The picker's filter narrows the chips (a non-match hides `default`) and
    # Enter selects the single remaining match.
    db_filter = page.get_by_test_id("db-filter")
    expect(db_filter).to_be_visible()
    db_filter.fill("sys")
    expect(page.locator('[data-db="default"]')).to_have_count(0)
    expect(page.locator('[data-db="system"]')).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - system")

    # opening with ?connection=<name> opens that connection. The database is
    # not picked yet, so this stays on the prompt rather than the explorer.
    page.goto("/?connection=clickhouse", wait_until="networkidle")
    expect(page.get_by_test_id("db-picker")).to_be_visible()
    # The filter is case-insensitive, so both INFORMATION_SCHEMA chips remain;
    # click the exact one.
    page.get_by_test_id("db-filter").fill("information_schema")
    page.locator('[data-db="information_schema"]').click()
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - information_schema")

    # the connection pill's database menu carries the same filter
    page.get_by_test_id("connection-status").click()
    menu_filter = page.get_by_test_id("db-select-filter")
    expect(menu_filter).to_be_visible()
    menu_filter.fill("zzz")
    expect(page.get_by_test_id("db-select-empty")).to_be_visible()
    menu_filter.fill("sys")
    expect(page.get_by_test_id("db-select").get_by_role("option")).to_have_count(1)
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - system")


def test_ready_connection_shows_query_panel(seeded_duckdb, page: Page) -> None:
    """A ready connection never needs the `query` command: connecting lands on
    the explorer, and Queries puts the panel up — first visit and after a
    detour alike."""
    _connect(page, _DUCKDB, seeded_duckdb)
    expect(page.get_by_test_id("explorer-tables")).to_be_visible()

    page.get_by_test_id("nav-queries").click()
    expect(page.get_by_test_id("query-panel")).to_be_visible()

    page.get_by_test_id("nav-explorer").click()
    expect(page.get_by_test_id("explorer-tables")).to_be_visible()
    page.get_by_test_id("nav-queries").click()
    expect(page.get_by_test_id("query-panel")).to_be_visible()
