import httpx
from conftest import connect_clickhouse_test_db, open_query_panel
from playwright.sync_api import Page, expect


def _open_query_panel(page: Page) -> None:
    """Connect with form defaults, select the seeded `test` db, open the panel."""
    connect_clickhouse_test_db(page)
    open_query_panel(page)


def test_mcp_push_to_live_session(seeded_test_db, page: Page, base_url: str) -> None:
    _open_query_panel(page)

    # Arm remote control via the agent popover, then read the session id.
    page.get_by_test_id("agent-toggle").click()
    expect(page.get_by_test_id("agent-panel")).to_be_visible()
    page.get_by_test_id("remote-arm").check()
    sid_el = page.get_by_test_id("remote-session-id")
    expect(sid_el).to_be_visible()
    session_id = sid_el.inner_text().strip()
    assert session_id

    # Push a query the way an MCP client would (via the REST surface).
    res = httpx.post(
        f"{base_url}/api/remote/push",
        json={
            "session_id": session_id,
            "query": "SELECT id, name FROM items",
            "limit": 10,
            "order_by": [{"name": "id", "dir": "DESC"}],
            "fields": ["name"],
        },
        timeout=10.0,
    )
    res.raise_for_status()
    assert res.json()["ok"] is True

    # The browser filled the SQL box and auto-ran; only the pushed field shows.
    expect(page.get_by_test_id("query-input")).to_have_value("SELECT id, name FROM items")
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    expect(output.locator("table thead th")).to_have_count(1)
    expect(output.locator("table thead th")).to_contain_text("name")
    expect(output).to_contain_text("gamma")  # id DESC -> gamma first

    # Disarm: the popover no longer exposes the session id...
    page.get_by_test_id("remote-arm").uncheck()
    expect(page.get_by_test_id("remote-session-id")).to_have_count(0)

    # ...and a push to an unknown/inactive id is reported as not delivered.
    res2 = httpx.post(
        f"{base_url}/api/remote/push",
        json={"session_id": "deadbeef", "query": "SELECT 1"},
        timeout=10.0,
    )
    assert res2.json()["ok"] is False
