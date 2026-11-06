"""Saved cards edit and delete: the form reopens on a saved connection's
values and re-saves it under its name; a delete drops the card and
disconnects the session on it."""

from conftest import open_connect
from playwright.sync_api import Page, expect
from test_drivers import CASES, _connect

DUCK = next(c for c in CASES if c.id == "duckdb")


def _card(page: Page, name: str):
    return page.locator(f'[data-testid="conn-card"][data-conn="{name}"]')


def test_edit_reopens_the_form_on_the_saved_values(seeded_duckdb, seeded_duckdb_long_names, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    open_connect(page)
    _card(page, DUCK.id).get_by_test_id("conn-edit").click()
    expect(page.get_by_test_id("duckdb-form")).to_contain_text("Edit DuckDB connection")
    expect(page.get_by_test_id("duck-name")).to_have_value(DUCK.id)
    expect(page.get_by_test_id("duck-name")).to_have_attribute("readonly", "")
    expect(page.get_by_test_id("duck-path")).to_have_value(seeded_duckdb)
    expect(page.get_by_test_id("conn-session-only")).to_have_count(0)

    # Re-saving under the same name replaces the config: the explorer now
    # lists the other file's extra table.
    page.get_by_test_id("duck-path").fill(seeded_duckdb_long_names)
    page.get_by_test_id("duck-connect").click()
    page.wait_for_url("**/explorer")
    expect(page.get_by_test_id("explorer-table")).to_have_count(3)
    open_connect(page)
    expect(_card(page, DUCK.id)).to_have_count(1)


def test_delete_drops_the_card_and_disconnects(seeded_duckdb, page: Page) -> None:
    _connect(page, DUCK, seeded_duckdb)
    open_connect(page)
    page.once("dialog", lambda d: d.dismiss())
    _card(page, DUCK.id).get_by_test_id("conn-delete").click()
    expect(_card(page, DUCK.id)).to_have_count(1)
    page.once("dialog", lambda d: d.accept())
    _card(page, DUCK.id).get_by_test_id("conn-delete").click()
    expect(_card(page, DUCK.id)).to_have_count(0)
    expect(page.get_by_test_id("connection-status")).to_have_count(0)
