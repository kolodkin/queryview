"""Sessions survive a refresh, are one-per-tab, and are switchable.

Uses DuckDB throughout: it needs no server, so these run anywhere the SPA does.
"""

from __future__ import annotations

import re

from conftest import open_query_panel
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCKDB = next(c for c in CASES if c.id == "duckdb")


def _connect_duckdb(page: Page, seeded_duckdb: str) -> None:
    # _connect already asserts the status text for the case.
    _connect(page, DUCKDB, seeded_duckdb)


def test_refresh_keeps_the_query_and_the_connection(seeded_duckdb, page: Page) -> None:
    _connect_duckdb(page, seeded_duckdb)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT 1 -- remembered")
    # The write-back is debounced; give it room to land before reloading.
    page.wait_for_timeout(900)

    page.reload(wait_until="networkidle")

    expect(page.get_by_test_id("query-input")).to_have_value("SELECT 1 -- remembered")
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - duckdb")


def test_refresh_keeps_the_page_you_were_on(seeded_duckdb, page: Page) -> None:
    _connect_duckdb(page, seeded_duckdb)
    page.get_by_test_id("nav-explorer").click()
    expect(page).to_have_url(re.compile(r"/explorer"))
    page.wait_for_timeout(600)

    page.reload(wait_until="networkidle")

    expect(page).to_have_url(re.compile(r"/explorer"))


def test_a_second_tab_gets_its_own_session(seeded_duckdb, page: Page, context) -> None:
    """The first tab holds its session, so a new tab starts a fresh one rather
    than showing the same state twice."""
    _connect_duckdb(page, seeded_duckdb)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT 1 -- first tab")
    page.wait_for_timeout(900)
    first = page.evaluate("() => sessionStorage.getItem('qv_session')")

    second = context.new_page()
    try:
        second.goto("/", wait_until="networkidle")
        assert second.evaluate("() => sessionStorage.getItem('qv_session')") != first
    finally:
        second.close()


def test_the_switcher_opens_a_new_session(seeded_duckdb, page: Page) -> None:
    _connect_duckdb(page, seeded_duckdb)
    page.get_by_test_id("session-switcher").click()
    expect(page.get_by_test_id("session-menu")).to_be_visible()

    page.get_by_test_id("session-new").click()

    # A brand-new session is disconnected, so it lands on the prompt.
    expect(page.get_by_test_id("prompt-input")).to_be_visible()
    expect(page.get_by_test_id("connection-status")).to_have_count(0)


def test_a_renamed_session_keeps_its_name(seeded_duckdb, page: Page) -> None:
    _connect_duckdb(page, seeded_duckdb)
    page.get_by_test_id("session-switcher").click()
    page.get_by_test_id("session-rename").click()
    page.get_by_test_id("session-rename-input").fill("nightly audit")
    page.keyboard.press("Enter")

    expect(page.get_by_test_id("session-switcher")).to_contain_text("nightly audit")

    page.reload(wait_until="networkidle")

    expect(page.get_by_test_id("session-switcher")).to_contain_text("nightly audit")
