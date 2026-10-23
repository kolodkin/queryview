"""A passphrase-locked connection: the tab that knows the passphrase keeps
working, the agent is refused on every path, and a lock survives a reload but
asks again in a fresh tab (docs/connect.md#locked-connections)."""

import httpx
from conftest import arm_remote, mcp_call, open_connect, open_query_panel
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")
PASSPHRASE = "open sesame"


def _answer_prompt(page: Page, passphrase: str) -> None:
    expect(page.get_by_test_id("passphrase-prompt")).to_be_visible()
    page.get_by_test_id("passphrase-input").fill(passphrase)
    page.get_by_test_id("passphrase-submit").click()


def test_locked_connection_keeps_the_agent_out(seeded_duckdb, page: Page, base_url: str) -> None:
    _connect(page, DUCK, seeded_duckdb)
    session_id = arm_remote(page)
    assert mcp_call(base_url, "run_sql", {"session_id": session_id, "sql": "SELECT count(*) FROM items"})["ok"]

    # Lock the connection from its card. The locking tab stays unlocked.
    open_connect(page)
    card = page.get_by_test_id("conn-card").filter(has_text=DUCK.id).first
    card.get_by_test_id("conn-lock").click()
    _answer_prompt(page, PASSPHRASE)
    expect(card).to_have_attribute("data-locked", "true")

    # The agent: MCP tools and the REST surface alike, with the session id only.
    out = mcp_call(base_url, "run_sql", {"session_id": session_id, "sql": "SELECT 1"})
    assert out == {"ok": False, "message": "connection is locked"}
    out = mcp_call(base_url, "push_query", {"session_id": session_id, "query": "SELECT 1"})
    assert not out["ok"] and out["message"] == "connection is locked"
    info = mcp_call(base_url, "session_info", {"session_id": session_id})
    assert info["locked"] is True and info["tables"] == []
    r = httpx.post(f"{base_url}/api/db/query", json={"query": "SELECT 1"}, headers={"X-QV-Session": session_id})
    assert r.status_code == 403 and r.json()["message"] == "connection is locked"

    # This tab still queries, and a reload keeps its token.
    card.click()
    _answer_prompt(page, PASSPHRASE)
    page.wait_for_url("**/explorer")  # a ready DuckDB connection lands there
    open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT count(*) AS n FROM items")
    page.get_by_test_id("query-run").click()
    expect(page.get_by_test_id("query-output").locator("table thead th")).to_contain_text(["n"])
    page.reload(wait_until="networkidle")
    expect(page.get_by_test_id("passphrase-prompt")).to_have_count(0)
    expect(page.get_by_test_id("connection-status")).to_contain_text(DUCK.id)

    # A tab without the token is asked; a wrong passphrase is refused.
    page.evaluate("sessionStorage.removeItem('qv_token')")
    page.reload(wait_until="networkidle")
    _answer_prompt(page, "wrong")
    expect(page.get_by_test_id("passphrase-error")).to_contain_text("wrong passphrase")
    _answer_prompt(page, PASSPHRASE)
    expect(page.get_by_test_id("passphrase-prompt")).to_have_count(0)
    expect(page.get_by_test_id("connection-status")).to_contain_text(DUCK.id)

    # Removing the lock lets the agent back in.
    open_connect(page)
    card = page.get_by_test_id("conn-card").filter(has_text=DUCK.id).first
    card.get_by_test_id("conn-lock").click()
    _answer_prompt(page, PASSPHRASE)
    expect(card).to_have_attribute("data-locked", "false")
    assert mcp_call(base_url, "run_sql", {"session_id": session_id, "sql": "SELECT 1"})["ok"]
