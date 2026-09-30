"""Workspace autosave: no Save buttons, and a named query persists after each
successful run (never a failed one). Agent-push persistence is covered in the
backend tests (test_dashboards.py). Uses a uniquely-named workspace per run."""

import uuid

import httpx
from conftest import open_query_panel
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")


def _stored_sql(base_url: str, ws: str, name: str) -> str | None:
    queries = httpx.get(f"{base_url}/api/predefined-queries", params={"type": "duckdb", "workspace": ws}).json()[
        "queries"
    ]
    return next((q["query"] for q in queries if q["query_name"] == name), None)


def test_autosave_saves_successful_runs_and_hides_save(seeded_duckdb, page: Page, base_url: str, shot) -> None:
    ws = f"e2e-auto-{uuid.uuid4().hex[:6]}"
    httpx.post(f"{base_url}/api/workspaces", json={"name": ws, "autosave": True}).raise_for_status()

    _connect(page, DUCK, seeded_duckdb)
    page.get_by_test_id("workspace-switcher").click()
    page.get_by_test_id("workspace-option").filter(has_text=ws).click()
    expect(page.get_by_test_id("workspace-switcher")).to_contain_text(ws)

    open_query_panel(page)
    expect(page.get_by_test_id("query-save")).to_have_count(0)

    page.once("dialog", lambda d: d.accept("auto q"))
    page.get_by_test_id("query-predefined-select").select_option("::new::")
    page.get_by_test_id("query-input").fill("SELECT id, name FROM items ORDER BY id")
    page.get_by_test_id("query-run").click()
    expect(page.get_by_test_id("query-output")).to_be_visible()
    expect(page.get_by_test_id("query-predefined-select").locator('option[value="auto q"]')).to_have_count(1)
    assert _stored_sql(base_url, ws, "auto q") == "SELECT id, name FROM items ORDER BY id"
    shot("autosave: saved after a successful run")

    # A failing run leaves the stored SQL alone.
    page.get_by_test_id("query-input").fill("SELEC nope")
    page.get_by_test_id("query-run").click()
    expect(page.get_by_test_id("query-error")).to_be_visible()
    assert _stored_sql(base_url, ws, "auto q") == "SELECT id, name FROM items ORDER BY id"

    page.get_by_test_id("nav-dashboard").click()
    expect(page.get_by_test_id("dashboard-view")).to_be_visible()
    expect(page.get_by_test_id("dashboard-save")).to_have_count(0)

    # Turning it off in Manage workspaces brings Save back without a reload.
    page.get_by_test_id("workspace-switcher").click()
    page.get_by_test_id("workspace-manage").click()
    autosave = page.get_by_test_id("workspace-autosave-input")
    expect(autosave).to_be_checked()
    autosave.uncheck()
    page.get_by_test_id("workspace-save").click()
    expect(page.get_by_test_id("dashboard-save")).to_be_visible()
