"""Sessions survive a refresh, are one-per-tab, and are switchable.

Uses DuckDB throughout: it needs no server, so these run anywhere the SPA does.
"""

from __future__ import annotations

import re
import uuid

import httpx
import pytest
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

    # No focus-out happened, so the reload's pagehide beacon is what carries it.
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


def test_a_restored_panel_does_not_page_a_new_query_into_nothing(seeded_duckdb, page: Page) -> None:
    """The page you were on is not restored: an offset is a cursor into a result
    set, and results are not restored either (docs/session.md)."""
    _connect_duckdb(page, seeded_duckdb)
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT name FROM items ORDER BY id")
    page.get_by_test_id("query-limit").fill("1")
    page.get_by_test_id("query-run").click()
    expect(page.get_by_test_id("query-output")).to_contain_text("alpha")
    page.get_by_test_id("query-next").click()
    expect(page.get_by_test_id("query-output")).to_contain_text("beta")

    page.reload(wait_until="networkidle")

    # The SQL comes back; the cursor does not...
    expect(page.get_by_test_id("query-input")).to_have_value("SELECT name FROM items ORDER BY id")
    expect(page.get_by_test_id("query-offset")).to_have_value("0")
    # ...so a re-run starts at the first page rather than past the end of a
    # fresh result set.
    page.get_by_test_id("query-run").click()
    expect(page.get_by_test_id("query-output")).to_contain_text("alpha")


@pytest.fixture
def left_behind(base_url: str):
    """An earlier test's session: panel state saved, then released by its closing
    tab, so it is the most recently active unheld session — exactly what a new
    tab resumes. Requested before `page`, so it exists when the `context` fixture
    seeds this test's session."""
    tab = f"e2e-{uuid.uuid4().hex}"
    sid = httpx.post(f"{base_url}/api/sessions/attach", json={"tab": tab}).json()["session"]["id"]
    ui = {"query": {"sql": "SELECT 'left behind'", "orderBy": [{"name": "name", "dir": "DESC"}]}}
    httpx.post(f"{base_url}/api/sessions/release", json={"tab": tab, "session_id": sid, "ui": ui})
    yield sid
    httpx.delete(f"{base_url}/api/sessions/{sid}")


def test_each_test_starts_on_a_fresh_session(left_behind: str, seeded_duckdb, page: Page) -> None:
    """The `context` fixture must seed a brand-new session, not resume the last
    one another test released: that one carries its SQL and order-by, and a
    restored DESC order turned this suite's first page into its last."""
    page.goto("/", wait_until="networkidle")
    assert page.evaluate("() => sessionStorage.getItem('qv_session')") != left_behind

    _connect_duckdb(page, seeded_duckdb)
    open_query_panel(page)
    expect(page.get_by_test_id("query-input")).to_have_value("")
    expect(page.get_by_test_id("orderby-chip")).to_have_count(0)
    expect(page.get_by_test_id("query-offset")).to_have_value("0")
