import re

import httpx
from conftest import open_connect, start_new_connection
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

# Driver-agnostic behaviour is exercised on DuckDB: no server to stand up.
_DUCKDB = next(c for c in CASES if c.id == "duckdb")


def test_queryview_e2e(page: Page) -> None:
    # loads the app and shows the heading
    open_connect(page)
    expect(page.locator("h1")).to_have_text("QueryView")

    # the ClickHouse "new connection" card opens its form, and Back returns
    start_new_connection(page, "clickhouse")
    expect(page.get_by_test_id("clickhouse-form")).to_be_visible()
    page.get_by_test_id("form-back").click()
    expect(page.get_by_test_id("clickhouse-form")).to_have_count(0)
    start_new_connection(page, "clickhouse")
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
    # connection is now ready, lands on the explorer. The session's URL write is
    # fire-and-forget; wait for it so the reload below resumes the explorer.
    with page.expect_response(lambda r: r.request.method == "PATCH" and "/api/sessions/" in r.url):
        page.locator('[data-db="default"]').click()
    expect(page.get_by_test_id("connection-indicator")).to_be_visible()
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - default")
    expect(page).to_have_url(re.compile(r"/explorer"))
    expect(page.get_by_test_id("explorer-tables")).to_be_visible()

    # reload resumes the session, then reconnect and select the system database
    page.goto("/", wait_until="networkidle")
    # Resume: came back connected to the previously selected database, and the
    # landing redirect picks the explorer over Connect.
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - default")
    expect(page).to_have_url(re.compile(r"/explorer"))
    # The saved connection's card, marked active and showing its database,
    # reopens the picker; choose a different database.
    page.get_by_test_id("nav-connect").click()
    card = page.locator('[data-testid="conn-card"][data-conn="clickhouse"]')
    expect(card).to_have_attribute("data-active", "true")
    expect(card).to_contain_text("default")
    card.click()
    # The picker's Back returns to the cards; the card opens it again.
    page.get_by_test_id("picker-back").click()
    expect(page.get_by_test_id("db-picker")).to_have_count(0)
    card.click()
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
    # not picked yet, so this stays on Connect rather than the explorer.
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


def test_connect_page_and_disconnect(seeded_duckdb, page: Page) -> None:
    """Connect keeps the cards up for a ready connection, and the pill's menu
    (even a picker-less driver's) ends with Disconnect."""
    _connect(page, _DUCKDB, seeded_duckdb)

    page.get_by_test_id("nav-connect").click()
    expect(page).to_have_url(re.compile(r"/connect"))
    expect(page.locator('[data-testid="conn-card"][data-conn="duckdb"]')).to_have_attribute("data-active", "true")
    expect(page.get_by_test_id("query-panel")).to_have_count(0)

    page.get_by_test_id("connection-status").click()
    page.get_by_test_id("disconnect").click()
    expect(page.get_by_test_id("connection-status")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/connect"))

    # Durable: a reload stays disconnected.
    page.reload(wait_until="networkidle")
    expect(page.get_by_test_id("connection-status")).to_have_count(0)


def test_disconnected_lands_on_connect(page: Page) -> None:
    """A disconnected session opens on /connect, and Queries sends it there
    too: the query panel needs a database. The old /prompt URL redirects."""
    page.goto("/", wait_until="networkidle")
    expect(page).to_have_url(re.compile(r"/connect$"))
    expect(page.get_by_test_id("connect-page")).to_be_visible()

    page.get_by_test_id("nav-queries").click()
    expect(page).to_have_url(re.compile(r"/connect$"))

    page.goto("/prompt", wait_until="networkidle")
    expect(page).to_have_url(re.compile(r"/connect$"))


def _save_connections(page: Page, base_url: str, configs: list[dict]) -> None:
    """Save connections through the API as the page's session."""
    sid = page.evaluate("() => sessionStorage.getItem('qv_session')")
    for config in configs:
        httpx.post(
            f"{base_url}/api/db/connect", json=config, headers={"X-QV-Session": sid}, timeout=10.0
        ).raise_for_status()


def test_many_connections(seeded_test_db, page: Page, base_url: str) -> None:
    """Past six saved connections: Recent row, a capped scrolling list, search
    with a count and arrow-key highlight, driver chips, and "+ New" alone.
    Self-contained: two drivers for the chips, and enough cards to scroll."""
    page.goto("/connect", wait_until="networkidle")
    bulk = [{"type": "duckdb", "name": f"bulk-{i:02d}", "path": ":memory:"} for i in range(14)]
    ch = {"type": "clickhouse", "name": "bulk-ch", "host": "localhost", "port": "8123", "username": "default"}
    # ClickHouse first: the last save becomes the session's connection, and a
    # picker-less DuckDB keeps the cards up rather than a database picker.
    _save_connections(page, base_url, [ch, *bulk])
    open_connect(page)

    # The most recent three get their own row; the rest scroll in a capped box.
    recent = page.get_by_test_id("conn-recent").get_by_test_id("conn-card")
    expect(recent).to_have_count(3)
    expect(recent.first).to_have_attribute("data-conn", "bulk-13")
    everything = page.get_by_test_id("conn-all")
    assert everything.evaluate("el => el.scrollHeight > el.clientHeight")

    # Only "+ New" creates connections now; the cards are gone.
    expect(page.get_by_test_id("new-conn-duckdb")).to_have_count(0)
    page.get_by_test_id("new-menu-toggle").click()
    expect(page.get_by_test_id("new-menu")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("new-menu")).to_have_count(0)

    # Driver chips narrow to one driver.
    page.locator('[data-testid="driver-chip"][data-type="clickhouse"]').click()
    expect(page.get_by_test_id("conn-recent")).to_have_count(0)
    cards = page.get_by_test_id("conn-card")
    expect(cards.first).to_be_visible()
    for i in range(cards.count()):
        expect(cards.nth(i)).to_contain_text("ClickHouse")
    page.locator('[data-testid="driver-chip"][data-type=""]').click()

    # `/` focuses search, which matches the name and shows a count.
    page.locator("h1").click()
    page.keyboard.press("/")
    search = page.get_by_test_id("conn-filter")
    expect(search).to_be_focused()
    page.keyboard.type("bulk-0")
    expect(cards).to_have_count(10)
    expect(page.get_by_test_id("conn-count")).to_contain_text("10 of")

    # Arrows move the highlight; Enter opens the highlighted card, and a
    # picker-less DuckDB lands on the explorer.
    expect(cards.first).to_have_attribute("data-highlighted", "true")
    page.keyboard.press("ArrowDown")
    second = cards.nth(1)
    expect(second).to_have_attribute("data-highlighted", "true")
    name = second.get_attribute("data-conn")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/explorer"))
    expect(page.get_by_test_id("connection-status")).to_contain_text(f"connected - {name}")
