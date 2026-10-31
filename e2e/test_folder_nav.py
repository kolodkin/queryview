"""DuckDB folder mode: a connection whose path is a directory lands on the
root's files, the pill menu walks folders one level at a time under the full
path, and the Union by name checkbox changes the glob entry's query."""

from __future__ import annotations

import os

from conftest import open_connect, start_new_connection
from playwright.sync_api import Page, expect


def test_folder_connection_navigates_folders_and_browses_files(seeded_folder, page: Page, shot) -> None:
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
    shot("folder mode: root files and glob entry")

    # The menu shows the full path and the root's subfolders, no `..` at the root.
    status.click()
    expect(page.get_by_test_id("db-select-path")).to_have_text(seeded_folder)
    options = page.get_by_test_id("db-select").get_by_role("option")
    expect(options).to_have_text(["sub"])
    shot("folder picker at the root: full path, no parent")
    options.first.click()
    expect(status).to_contain_text("· sub")
    expect(status).to_have_attribute("title", f"{seeded_folder}/sub")
    expect(names).to_have_text(["nested.csv.gz"])
    tables.first.click()
    expect(page.get_by_test_id("explorer-panel")).to_contain_text("gamma")
    expect(page.get_by_test_id("explorer-table-path")).to_have_text("sub/nested.csv.gz")
    shot("subfolder: gzipped csv browsed")

    # `..` goes back up.
    status.click()
    expect(options).to_have_text([".."])
    shot("folder picker in a subfolder: parent entry")
    options.first.click()
    expect(names).to_have_text(["extra.csv", "items.csv", "*.csv"])

    # Union by name: the glob entry still browses, now across both files.
    page.get_by_test_id("explorer-union").check()
    tables.last.click()
    panel = page.get_by_test_id("explorer-panel")
    expect(panel).to_contain_text("delta")
    expect(panel).to_contain_text("gamma")
    shot("union by name: glob entry across both files")


def test_union_by_name_adds_columns_only_some_files_have(seeded_mixed_folder, page: Page, shot) -> None:
    open_connect(page)
    start_new_connection(page, "duckdb")
    page.get_by_test_id("duck-path").fill(seeded_mixed_folder)
    page.get_by_test_id("duck-connect").click()
    expect(page.get_by_test_id("duckdb-form")).to_have_count(0)
    page.locator('[data-testid="explorer-table"][data-table="*.csv"]').click()
    panel = page.get_by_test_id("explorer-panel")
    headers = panel.locator("thead th")

    # Without union: the first file's columns only; b.csv's `city` is dropped.
    expect(panel).to_contain_text("gamma")
    expect(headers).to_have_text(["id", "name"])
    shot("glob without union: city column dropped")

    # With union: every file's columns, NULL where a file lacks one.
    page.get_by_test_id("explorer-union").check()
    expect(headers).to_have_text(["id", "name", "city"])
    expect(panel).to_contain_text("lisbon")
    shot("glob with union by name: shared columns aligned, city added")


def test_max_entries_cuts_lists_and_says_so(seeded_wide_folder, page: Page, shot) -> None:
    files = [f"f{i:02d}.csv" for i in range(1, 13)]
    folders = [f"d{i:02d}" for i in range(1, 13)]
    open_connect(page)
    start_new_connection(page, "duckdb")
    page.get_by_test_id("duck-path").fill(seeded_wide_folder)
    page.get_by_test_id("duck-connect").click()
    expect(page.get_by_test_id("duckdb-form")).to_have_count(0)
    names = page.locator('[data-testid="explorer-table"] > span:first-child')
    options = page.get_by_test_id("db-select").get_by_role("option")
    status = page.get_by_test_id("connection-status")
    # The default 1000 lists all twelve of each.
    expect(names).to_have_text([*files, "*.csv"])
    expect(page.get_by_test_id("explorer-truncated")).to_have_count(0)

    # Max entries 10: the first ten files (and a glob over just those), ten folders.
    limit = page.get_by_test_id("explorer-max-entries")
    limit.fill("10")
    limit.press("Enter")
    expect(names).to_have_text([*files[:10], "*.csv"])
    expect(page.get_by_test_id("explorer-truncated")).to_contain_text("More than 10 files")
    shot("max entries 10: file list cut, with notice")
    page.locator('[data-testid="explorer-table"][data-table="*.csv"]').click()
    expect(page.get_by_test_id("explorer-panel").locator("tbody tr")).to_have_count(10)
    status.click()
    expect(options).to_have_text(folders[:10])
    expect(page.get_by_test_id("db-select-truncated")).to_contain_text("More than 10 folders")
    shot("max entries 10: folder list cut, with notice")
    status.click()

    # The setting survives a reload: it lives in the session.
    page.reload()
    expect(page.get_by_test_id("explorer-max-entries")).to_have_value("10")
    expect(names).to_have_text([*files[:10], "*.csv"])

    # Raise it to 12: everything is listed again, no notices.
    limit.fill("12")
    limit.press("Enter")
    expect(names).to_have_text([*files, "*.csv"])
    expect(page.get_by_test_id("explorer-truncated")).to_have_count(0)
    status.click()
    expect(options).to_have_text(folders)
    expect(page.get_by_test_id("db-select-truncated")).to_have_count(0)
