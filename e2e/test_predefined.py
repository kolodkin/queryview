"""Renaming and deleting a saved (predefined) query from the query panel.
Uses DuckDB and a uniquely-named workspace per run."""

import uuid

import httpx
from conftest import open_query_panel
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")


def _names(base_url: str, ws: str) -> list[str]:
    r = httpx.get(f"{base_url}/api/predefined-queries", params={"type": "duckdb", "workspace": ws})
    return [q["query_name"] for q in r.json()["queries"]]


def test_rename_and_delete_a_saved_query(seeded_duckdb, page: Page, base_url: str, shot) -> None:
    ws = f"e2e-pq-{uuid.uuid4().hex[:6]}"
    httpx.post(f"{base_url}/api/workspaces", json={"name": ws}).raise_for_status()

    _connect(page, DUCK, seeded_duckdb)
    page.get_by_test_id("workspace-switcher").click()
    page.get_by_test_id("workspace-option").filter(has_text=ws).click()
    expect(page.get_by_test_id("workspace-switcher")).to_contain_text(ws)
    open_query_panel(page)

    select = page.get_by_test_id("query-predefined-select")
    rename = page.get_by_test_id("query-rename")
    delete = page.get_by_test_id("query-delete")
    expect(rename).to_be_disabled()
    expect(delete).to_be_disabled()

    # A new, not yet saved name can't be renamed or deleted.
    page.once("dialog", lambda d: d.accept("pq first"))
    select.select_option("::new::")
    expect(rename).to_be_disabled()
    page.get_by_test_id("query-input").fill("SELECT id FROM items ORDER BY id")
    page.get_by_test_id("query-save").click()
    expect(rename).to_be_enabled()
    shot("saved query: Rename and Delete enabled")

    page.once("dialog", lambda d: d.accept("pq renamed"))
    rename.click()
    expect(select).to_have_value("pq renamed")
    expect(select.locator('option[value="pq first"]')).to_have_count(0)
    assert _names(base_url, ws) == ["pq renamed"]
    shot("renamed")

    # Dismissing the confirmation keeps it.
    page.once("dialog", lambda d: d.dismiss())
    delete.click()
    expect(select).to_have_value("pq renamed")
    assert _names(base_url, ws) == ["pq renamed"]

    page.once("dialog", lambda d: d.accept())
    delete.click()
    expect(select).to_have_value("")
    expect(select.locator('option[value="pq renamed"]')).to_have_count(0)
    expect(page.get_by_test_id("query-input")).to_have_value("SELECT id FROM items ORDER BY id")
    assert _names(base_url, ws) == []
    shot("deleted: selection cleared, SQL kept")
