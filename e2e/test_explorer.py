"""The explorer page: table sidebar -> rows with the field/order-by selects and
pagination, parameterized across every driver (same seeds as test_drivers)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from test_drivers import CASES, DriverCase, _connect


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


# The browse query run by the order-by controls, delayed in the browser for the
# ASC direction only, so the two runs the test fires back to back are guaranteed
# to answer out of order. `__slow_runs` counts the delayed responses, giving the
# assertion below a condition to wait on instead of a sleep.
_DELAY_ASC_RUNS = """
(() => {
  window.__slow_runs = 0
  const orig = window.fetch
  window.fetch = async (...args) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0].url
    const body = args[1] && args[1].body ? String(args[1].body) : ''
    const slow = url.includes('/api/db/query') && body.includes('"dir":"ASC"')
    const res = await orig(...args)
    if (slow) {
      await new Promise((r) => setTimeout(r, 1500))
      window.__slow_runs += 1
    }
    return res
  }
})()
"""


def test_explorer_stale_run_does_not_overwrite_the_newest(seeded_test_db, page: Page) -> None:
    """Order-by add and its direction flip fire two runs back to back, and the
    server answers them concurrently. The rows shown must be the newest run's,
    not whichever response happens to land last."""
    case = CASES[0]  # ClickHouse
    page.add_init_script(_DELAY_ASC_RUNS)
    _connect(page, case, seeded_test_db)

    page.get_by_test_id("nav-explorer").click()
    page.locator('[data-testid="explorer-table"][data-table="items"]').click()
    output = page.get_by_test_id("explorer-output")
    expect(output).to_contain_text("alpha")
    expect(page.locator('[data-testid="field-toggle"]')).to_have_count(2)

    # Add `id` (ASC, delayed), then immediately flip it to DESC.
    page.locator('[data-testid="orderby-add"][data-col="id"]').click()
    chip = page.locator('[data-testid="orderby-chip"][data-col="id"]')
    expect(chip).to_be_visible()
    chip.get_by_test_id("orderby-dir").click()
    expect(output.locator("tbody tr").first).to_contain_text("gamma")

    # Once the superseded ASC response has landed, the table still reads DESC.
    page.wait_for_function("window.__slow_runs >= 1")
    expect(output.locator("tbody tr").first).to_contain_text("gamma")
