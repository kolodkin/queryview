"""The explorer page: table sidebar -> rows with the field/order-by selects and
pagination, parameterized across every driver (same seeds as test_drivers)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from test_drivers import CASES, DriverCase, _connect

# Mirrors DEFAULT_SIDEBAR_WIDTH in frontend/src/app/explorerSettings.ts.
DEFAULT_WIDTH = 256


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_explorer_browse_order_fields_paginate(case: DriverCase, request, page: Page, shot) -> None:
    seed = request.getfixturevalue(case.seed_fixture)
    _connect(page, case, seed)

    page.get_by_test_id("nav-explorer").click()
    expect(page.get_by_test_id("explorer-tables")).to_be_visible()

    # Each sidebar entry carries the engine's estimates. ClickHouse and DuckDB
    # know the seeded row count immediately; a freshly created Postgres table
    # has no reltuples estimate yet, so its subline is just the on-disk size.
    meta = page.locator('[data-testid="explorer-table"][data-table="items"] [data-testid="explorer-table-meta"]')
    expect(meta).to_be_visible()
    if case.id in ("clickhouse", "duckdb"):
        expect(meta).to_contain_text("3 rows")
    shot(f"{case.id} explorer table list")

    # Clicking a table selects it into the URL and loads its rows.
    page.locator('[data-testid="explorer-table"][data-table="items"]').click()
    expect(page).to_have_url(re.compile("table=items"))
    output = page.get_by_test_id("explorer-output")
    expect(output).to_be_visible()
    expect(output.locator("table thead th")).to_contain_text(["id", "name"])
    expect(output).to_contain_text("alpha")
    expect(output).to_contain_text("gamma")
    shot(f"{case.id} explorer rows")

    # The pickers come pre-populated from an automatic describe.
    expect(page.get_by_test_id("field-pickers")).to_be_visible()
    expect(page.locator('[data-testid="field-toggle"]')).to_have_count(2)

    # Order by id, flipped to DESC, re-runs immediately: gamma (id 3) first.
    page.locator('[data-testid="orderby-add"][data-col="id"]').click()
    chip = page.locator('[data-testid="orderby-chip"][data-col="id"]')
    expect(chip).to_be_visible()
    chip.get_by_test_id("orderby-dir").click()
    expect(output.locator("tbody tr").first).to_contain_text("gamma")
    shot(f"{case.id} explorer ordered desc")

    # Hiding a field is client-side column visibility — no re-run.
    page.locator('[data-testid="field-toggle"][data-col="id"]').click()
    expect(output.locator("table thead th")).to_have_count(1)
    page.locator('[data-testid="field-toggle"][data-col="id"]').click()
    expect(output.locator("table thead th")).to_have_count(2)

    # Pagination under the DESC order: limit 2 (applies on blur) shows
    # gamma, beta; the next page holds only alpha.
    page.get_by_test_id("explorer-limit").fill("2")
    page.keyboard.press("Tab")
    expect(output).not_to_contain_text("alpha")
    page.get_by_test_id("explorer-next").click()
    expect(output).to_contain_text("alpha")
    expect(output).not_to_contain_text("gamma")
    shot(f"{case.id} explorer page 2")

# Driver-independent, so these run once against DuckDB (a file, no service).
DUCK = next(c for c in CASES if c.id == "duckdb")


def test_sidebar_width_is_draggable_and_remembered(
    seeded_duckdb_long_names, page: Page, shot
) -> None:
    """The Tables sidebar resizes from its right edge so long names need not be
    truncated. The width is remembered per view and survives a reload; the reset
    control puts it back to the default."""
    _connect(page, DUCK, seeded_duckdb_long_names)
    page.get_by_test_id("nav-explorer").click()

    aside = page.get_by_test_id("explorer-tables")
    expect(aside).to_be_visible()
    expect(aside).to_have_attribute("data-width", str(DEFAULT_WIDTH))
    # No reset control while the sidebar is still at its default width.
    expect(page.get_by_test_id("explorer-sidebar-reset")).to_have_count(0)

    # The longest name doesn't fit the default width — the reason to resize.
    longest = page.locator(
        '[data-testid="explorer-table"]'
        '[data-table="warehouse_shipment_reconciliation_log"] span'
    ).first
    assert longest.evaluate("e => e.scrollWidth > e.clientWidth"), "expected truncation"
    shot("explorer sidebar default width")

    # Drag the handle 120px to the right. Its centre sits on the panel's right
    # edge, so the dragged width is the default plus the travel.
    handle = page.get_by_test_id("explorer-sidebar-resize")
    box = handle.bounding_box()
    assert box is not None
    mid_y = box["y"] + box["height"] / 2
    centre_x = box["x"] + box["width"] / 2
    page.mouse.move(centre_x, mid_y)
    page.mouse.down()
    page.mouse.move(centre_x + 120, mid_y, steps=10)
    page.mouse.up()
    expect(aside).to_have_attribute("data-width", str(DEFAULT_WIDTH + 120))
    # ...and now it does fit: the whole point of the drag.
    assert not longest.evaluate("e => e.scrollWidth > e.clientWidth"), "still truncated"
    shot("explorer sidebar widened")

    # Stored as JSON under the explorer's view key, and restored on reload.
    stored = page.evaluate("() => localStorage.getItem('qv_view_explorer')")
    assert stored is not None
    assert f'"sidebarWidth":{DEFAULT_WIDTH + 120}' in stored.replace(" ", "")
    page.reload(wait_until="networkidle")
    aside = page.get_by_test_id("explorer-tables")
    expect(aside).to_have_attribute("data-width", str(DEFAULT_WIDTH + 120))

    # Arrow keys nudge it; the reset control restores the default and then hides.
    page.get_by_test_id("explorer-sidebar-resize").press("ArrowRight")
    expect(aside).to_have_attribute("data-width", str(DEFAULT_WIDTH + 136))
    page.get_by_test_id("explorer-sidebar-reset").click()
    expect(aside).to_have_attribute("data-width", str(DEFAULT_WIDTH))
    expect(page.get_by_test_id("explorer-sidebar-reset")).to_have_count(0)


def test_panels_show_loaders_until_data_arrives(seeded_duckdb, page: Page, shot) -> None:
    """Both panels show a loader while their first payload is in flight."""
    _connect(page, DUCK, seeded_duckdb)

    # Hold both requests open long enough for the loaders to be observable.
    # page.wait_for_timeout inside a sync route handler yields to the event
    # loop (unlike time.sleep), so the assertions below still run.
    def slow(route):
        page.wait_for_timeout(1500)
        try:
            route.continue_()
        except Exception:
            # The page navigated away while the response was held; the request
            # is gone and there is nothing left to continue.
            pass

    # Already on the explorer, so reload to refetch the list with the response
    # held back.
    page.route("**/api/db/tables", slow)
    page.reload()
    expect(page.get_by_test_id("explorer-tables-loading")).to_be_visible()
    shot("explorer tables loading")
    expect(page.locator('[data-testid="explorer-table"][data-table="items"]')).to_be_visible()
    page.unroute_all(behavior="ignoreErrors")

    page.route("**/api/db/query", slow)
    page.locator('[data-testid="explorer-table"][data-table="items"]').click()
    expect(page.get_by_test_id("explorer-rows-loading")).to_be_visible()
    shot("explorer rows loading")
    expect(page.get_by_test_id("explorer-output")).to_be_visible()
    expect(page.get_by_test_id("explorer-rows-loading")).to_have_count(0)
    # Drop any handler still holding a response, so page close doesn't race it.
    page.unroute_all(behavior="ignoreErrors")
