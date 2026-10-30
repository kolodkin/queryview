"""DuckDB folder mode: a connection whose path is a directory lands on the
root's files, the pill menu walks folders one level at a time under the full
path, and the Union by name checkbox changes the glob entry's query."""

from __future__ import annotations

import os

from conftest import open_connect, start_new_connection
from playwright.sync_api import Page, expect


def test_folder_connection_navigates_folders_and_browses_files(seeded_folder, page: Page) -> None:
    open_connect(page)
    start_new_connection(page, "duckdb")
    page.get_by_test_id("duck-path").fill(seeded_folder)
    page.get_by_test_id("duck-connect").click()
    expect(page.get_by_test_id("duckdb-form")).to_have_count(0)
    # Lands on the root, so no picker; the pill names the folder and holds the full path.
    expect(page.get_by_test_id("db-picker")).to_have_count(0)
    status = page.get_by_test_id("connection-status")
    expect(status).to_contain_text(f"· {os.path.basename(seeded_folder)}")
    expect(status).to_have_attribute("title", seeded_folder)
    tables = page.get_by_test_id("explorer-table")
    names = page.locator('[data-testid="explorer-table"] > span:first-child')  # the name, not the size
    expect(names).to_have_text(["extra.csv", "items.csv", "*.csv"])

    # The menu shows the full path and the root's subfolders, no `..` at the root.
    status.click()
    expect(page.get_by_test_id("db-select-path")).to_have_text(seeded_folder)
    options = page.get_by_test_id("db-select").get_by_role("option")
    expect(options).to_have_text(["sub"])
    options.first.click()
    expect(status).to_contain_text("· sub")
    expect(status).to_have_attribute("title", f"{seeded_folder}/sub")
    expect(names).to_have_text(["nested.csv.gz"])
    tables.first.click()
    expect(page.get_by_test_id("explorer-panel")).to_contain_text("gamma")

    # `..` goes back up.
    status.click()
    expect(options).to_have_text([".."])
    options.first.click()
    expect(names).to_have_text(["extra.csv", "items.csv", "*.csv"])

    # Union by name: the glob entry still browses, now across both files.
    page.get_by_test_id("explorer-union").check()
    tables.last.click()
    panel = page.get_by_test_id("explorer-panel")
    expect(panel).to_contain_text("delta")
    expect(panel).to_contain_text("gamma")
