import re

import httpx
from conftest import connect_clickhouse_test_db
from playwright.sync_api import Page, expect


def _connect_and_select_test_db(page: Page) -> None:
    """Connect with the form defaults and select the seeded `test` database."""
    connect_clickhouse_test_db(page)


# A dashboard that reads window.queries and writes a value into the DOM, so the
# e2e can assert the injected results reached the agent HTML. Styled to render
# the value as large, centered text (nicer as a screenshot); #out's textContent
# stays exactly the joined names so the assertions below are unchanged.
_DASHBOARD_HTML = (
    "<style>"
    "html,body{height:100%;margin:0}"
    "body{display:flex;align-items:center;justify-content:center;"
    "font-family:system-ui,-apple-system,sans-serif}"
    "#out{font-size:72px;font-weight:800;color:#4338ca;letter-spacing:-0.02em}"
    "</style>"
    "<div id='out'></div>"
    "<script>"
    "const items = window.queries && window.queries.items;"
    "document.getElementById('out').textContent = "
    "items ? items.name.join(',') : 'NO DATA';"
    "</script>"
)


def test_dashboard_push_and_reopen(seeded_test_db, page: Page, base_url: str, shot) -> None:
    _connect_and_select_test_db(page)
    shot("connected to test db")

    # Arm remote control via the agent popover, then read the session id.
    page.get_by_test_id("agent-toggle").click()
    expect(page.get_by_test_id("agent-panel")).to_be_visible()
    page.get_by_test_id("remote-arm").check()
    sid_el = page.get_by_test_id("remote-session-id")
    expect(sid_el).to_be_visible()
    session_id = sid_el.inner_text().strip()
    assert session_id
    shot("remote control armed")

    # Push a dashboard the way the MCP tool would (via the REST mirror).
    res = httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "session_id": session_id,
            "name": "sales",
            "html": _DASHBOARD_HTML,
            "queries": {"items": "SELECT name FROM items ORDER BY id"},
        },
        timeout=10.0,
    )
    res.raise_for_status()
    body = res.json()
    assert body["persisted"] is True
    assert body["pushed"] is True

    # The browser navigated to the dashboard and the iframe rendered the values
    # injected as window.queries (column-oriented: items.name is the column).
    expect(page).to_have_url(re.compile(r"/dashboard\?name=sales"))
    expect(page.get_by_test_id("dashboard-view")).to_be_visible()
    frame = page.frame_locator('[data-testid="dashboard-frame"]')
    expect(frame.locator("#out")).to_have_text("alpha,beta,gamma")
    shot("pushed dashboard rendered")

    # Reopen from the store (no live push): navigate directly to the deep link.
    page.goto("/dashboard?name=sales", wait_until="networkidle")
    expect(page.get_by_test_id("dashboard-view")).to_be_visible()
    frame = page.frame_locator('[data-testid="dashboard-frame"]')
    expect(frame.locator("#out")).to_have_text("alpha,beta,gamma")

    # The dropdown lists the saved dashboard.
    expect(page.get_by_test_id("dashboard-select")).to_contain_text("sales")
    shot("reopened from store")


def test_dashboard_runqueries_error_shows_banner(seeded_test_db, page: Page, base_url: str, shot) -> None:
    # Persist a dashboard whose query is invalid; reopening it should surface a
    # fail-fast error banner instead of rendering the iframe.
    _connect_and_select_test_db(page)
    res = httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "broken",
            "html": _DASHBOARD_HTML,
            "queries": {"items": "SELECT name FROM no_such_table"},
        },
        timeout=10.0,
    )
    res.raise_for_status()

    page.goto("/dashboard?name=broken", wait_until="networkidle")
    expect(page.get_by_test_id("dashboard-error")).to_be_visible()
    expect(page.get_by_test_id("dashboard-error")).to_contain_text("items")
    expect(page.get_by_test_id("dashboard-frame")).to_have_count(0)
    shot("fail-fast error banner")


def test_a_dashboard_runs_on_the_viewing_sessions_connection(seeded_test_db, page: Page, base_url: str) -> None:
    """A saved dashboard names no connection: a disconnected session is told to
    connect rather than failing on some connection the dashboard remembers."""
    _connect_and_select_test_db(page)
    httpx.post(
        f"{base_url}/api/dashboards",
        json={"name": "portable", "html": _DASHBOARD_HTML, "queries": {"items": "SELECT name FROM items ORDER BY id"}},
        timeout=10.0,
    ).raise_for_status()

    page.get_by_test_id("session-switcher").click()
    page.get_by_test_id("session-new").click()
    # The switch lands on the new session's page (disconnected: Connect); wait
    # for it, or it would navigate away from a dashboard opened too early.
    expect(page.get_by_test_id("connect-page")).to_be_visible()
    # Navigate inside the app: a reload would re-run the fixture's init script
    # and put the tab back on the original (connected) session.
    page.get_by_test_id("nav-dashboard").click()
    page.get_by_test_id("dashboard-select").select_option("portable")

    expect(page.get_by_test_id("dashboard-error")).to_contain_text("Connect to a database")


# Draws its own selector from window.params and re-runs via setParams; the
# results come back through onQueryResults without reloading the frame.
_PARAMS_HTML = (
    "<button id='go' onclick=\"window.setParams({n: 'beta'})\">beta</button>"
    "<div id='out'></div><div id='pick'></div>"
    "<script>"
    "function show(q){document.getElementById('out').textContent ="
    " q.items ? q.items.name.join(',') : 'NO DATA';}"
    "show(window.queries);"
    "document.getElementById('pick').textContent = window.params[0].options.join('|');"
    "window.onQueryResults = function(q){show(q);};"
    "</script>"
)


def test_dashboard_params_resolve_and_rerun_through_set_params(seeded_test_db, page: Page, base_url: str) -> None:
    _connect_and_select_test_db(page)
    httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "picker",
            "html": _PARAMS_HTML,
            "queries": {"items": "SELECT name FROM items WHERE name = {n}"},
            "params": [{"name": "n", "options_sql": "SELECT name FROM items ORDER BY id"}],
        },
        timeout=10.0,
    ).raise_for_status()

    page.get_by_test_id("nav-dashboard").click()
    page.get_by_test_id("dashboard-select").select_option("picker")
    frame = page.frame_locator('[data-testid="dashboard-frame"]')
    # options_sql ran on the session; the first option is the default.
    expect(frame.locator("#pick")).to_have_text("alpha|beta|gamma")
    expect(frame.locator("#out")).to_have_text("alpha")

    frame.locator("#go").click()  # the page calls setParams({n: 'beta'})
    expect(frame.locator("#out")).to_have_text("beta")
