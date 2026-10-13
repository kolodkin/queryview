import asyncio
import concurrent.futures
import json
from typing import Any

import httpx
from conftest import connect_clickhouse_test_db, open_query_panel
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")


def _open_query_panel(page: Page) -> None:
    """Connect to ClickHouse, select the seeded `qvtest` db, open the panel."""
    connect_clickhouse_test_db(page)
    open_query_panel(page)


def _arm(page: Page) -> str:
    """Arm remote control via the agent popover; return the session id."""
    page.get_by_test_id("agent-toggle").click()
    expect(page.get_by_test_id("agent-panel")).to_be_visible()
    page.get_by_test_id("remote-arm").check()
    sid_el = page.get_by_test_id("remote-session-id")
    expect(sid_el).to_be_visible()
    session_id = sid_el.inner_text().strip()
    assert session_id
    page.get_by_test_id("agent-toggle").click()  # close the popover
    return session_id


def _mcp_call(base_url: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call one tool over the real MCP endpoint, the way an agent does. Run on
    its own thread: the sync Playwright API owns this one's event loop."""

    async def call() -> dict[str, Any]:
        async with streamable_http_client(f"{base_url}/mcp/") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                return json.loads(res.content[0].text)  # type: ignore[union-attr]

    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, call()).result(timeout=30)


def test_mcp_push_script_fills_and_runs_the_queries_editor(seeded_duckdb, page: Page, base_url: str) -> None:
    _connect(page, DUCK, seeded_duckdb)
    session_id = _arm(page)

    script = "SELECT 1 AS a; SELECT name FROM items ORDER BY id"
    out = _mcp_call(base_url, "push_script", {"session_id": session_id, "sql": script, "run": True})
    assert out["ok"] is True, out

    # The browser opened the Queries page, loaded the script and ran it all.
    expect(page.get_by_test_id("queries-input")).to_have_value(script)
    expect(page.get_by_test_id("queries-status")).to_contain_text("2 statements")
    expect(page.get_by_test_id("queries-output").locator("table thead th")).to_contain_text(["name"])

    # While the user is typing in the editor, a push is refused, not applied.
    page.get_by_test_id("queries-input").click()
    page.get_by_test_id("queries-input").press("End")
    page.keyboard.type(" -- mine")
    blocked: dict[str, Any] = {}
    for _ in range(20):  # the lock is taken by an async request on focus
        blocked = _mcp_call(base_url, "push_script", {"session_id": session_id, "sql": "SELECT 2"})
        if not blocked["ok"]:
            break
        page.wait_for_timeout(250)
    assert blocked == {"ok": False, "message": "blocked, user editing", "database": blocked["database"]}
    expect(page.get_by_test_id("queries-input")).to_have_value(script + " -- mine")


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
