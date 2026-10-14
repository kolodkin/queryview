from conftest import api, arm_remote, connect_clickhouse_test_db, mcp_call, open_query_panel
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")


def _open_query_panel(page: Page) -> None:
    """Connect to ClickHouse, select the seeded `qvtest` db, open the panel."""
    connect_clickhouse_test_db(page)
    open_query_panel(page)


def test_mcp_push_script_fills_and_runs_the_scripts_editor(seeded_duckdb, page: Page, base_url: str) -> None:
    _connect(page, DUCK, seeded_duckdb)
    session_id = arm_remote(page)

    script = "SELECT 1 AS a; SELECT name FROM items ORDER BY id"
    out = mcp_call(base_url, "push_script", {"session_id": session_id, "sql": script, "run": True})
    assert out["ok"] is True, out

    # The browser opened the Scripts page, loaded the script and ran it all.
    expect(page.get_by_test_id("scripts-input")).to_have_value(script)
    expect(page.get_by_test_id("scripts-status")).to_contain_text("2 statements")
    expect(page.get_by_test_id("scripts-output").locator("table thead th")).to_contain_text(["name"])

    # While the user is typing in the editor, a push is refused, not applied.
    textarea = page.get_by_test_id("scripts-input")
    with page.expect_response(lambda r: r.url.endswith("/api/remote/lock")):  # focus takes the lock
        textarea.click()
    textarea.press("End")
    page.keyboard.type(" -- mine")
    blocked = mcp_call(base_url, "push_script", {"session_id": session_id, "sql": "SELECT 2"})
    assert not blocked["ok"] and blocked["message"] == "blocked, user editing"
    expect(page.get_by_test_id("scripts-input")).to_have_value(script + " -- mine")


def test_mcp_push_to_live_session(seeded_test_db, page: Page, base_url: str) -> None:
    _open_query_panel(page)

    session_id = arm_remote(page)

    # Push a query the way an MCP client would (via the REST surface).
    res = api(base_url).post(
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
    page.get_by_test_id("agent-toggle").click()
    page.get_by_test_id("remote-arm").uncheck()
    expect(page.get_by_test_id("remote-session-id")).to_have_count(0)

    # ...and a push to an unknown/inactive id is reported as not delivered.
    res2 = api(base_url).post(
        f"{base_url}/api/remote/push",
        json={"session_id": "deadbeef", "query": "SELECT 1"},
        timeout=10.0,
    )
    assert res2.json()["ok"] is False
