// DuckDB folder mode: a connection whose path is a directory lands on the
// root's files, the pill menu walks folders one level at a time under the full
// path, and the Union by name checkbox changes the glob entry's query.
import { basename } from "node:path";
import type { Page } from "@playwright/test";
import { expect, openConnect, startNewConnection, test } from "./fixtures";

async function connectFolder(page: Page, path: string, name?: string): Promise<void> {
  await openConnect(page);
  await startNewConnection(page, "duckdb");
  if (name) await page.getByTestId("duck-name").fill(name);
  await page.getByTestId("duck-path").fill(path);
  await page.getByTestId("duck-connect").click();
  await expect(page.getByTestId("duckdb-form")).toHaveCount(0);
}

// The table names, not their sizes.
const names = (page: Page) => page.locator('[data-testid="explorer-table"] > span:first-child');

test("folder connection navigates folders and browses files", async ({ page, seeds, shot }) => {
  const folder = await seeds.folder();
  await connectFolder(page, folder);
  // Lands on the root, so no picker; the pill names the folder and holds the full path.
  await expect(page.getByTestId("db-picker")).toHaveCount(0);
  const status = page.getByTestId("connection-status");
  await expect(status).toContainText(`· ${basename(folder)}`);
  await expect(status).toHaveAttribute("title", folder);
  const tables = page.getByTestId("explorer-table");
  await expect(names(page)).toHaveText(["extra.csv", "items.csv", "*.csv"]);
  await shot("folder mode: root files and glob entry");

  // The menu shows the full path and the root's subfolders, no `..` at the root.
  await status.click();
  await expect(page.getByTestId("db-select-path")).toHaveText(folder);
  const options = page.getByTestId("db-select").getByRole("option");
  await expect(options).toHaveText(["sub"]);
  await shot("folder picker at the root: full path, no parent");
  await options.first().click();
  await expect(status).toContainText("· sub");
  await expect(status).toHaveAttribute("title", `${folder}/sub`);
  await expect(names(page)).toHaveText(["nested.csv.gz"]);
  await tables.first().click();
  await expect(page.getByTestId("explorer-panel")).toContainText("gamma");
  await expect(page.getByTestId("explorer-table-path")).toHaveText("sub/nested.csv.gz");
  await shot("subfolder: gzipped csv browsed");

  // `..` goes back up.
  await status.click();
  await expect(options).toHaveText([".."]);
  await shot("folder picker in a subfolder: parent entry");
  await options.first().click();
  await expect(names(page)).toHaveText(["extra.csv", "items.csv", "*.csv"]);

  // Union by name: the glob entry still browses, now across both files.
  await page.getByTestId("explorer-union").check();
  await tables.last().click();
  const panel = page.getByTestId("explorer-panel");
  await expect(panel).toContainText("delta");
  await expect(panel).toContainText("gamma");
  await shot("union by name: glob entry across both files");
});

test("union by name adds columns only some files have", async ({ page, seeds, shot }) => {
  await connectFolder(page, await seeds.mixedFolder());
  await page.locator('[data-testid="explorer-table"][data-table="*.csv"]').click();
  const panel = page.getByTestId("explorer-panel");
  const headers = panel.locator("thead th");

  // Without union: the first file's columns only; b.csv's `city` is dropped.
  await expect(panel).toContainText("gamma");
  await expect(headers).toHaveText(["id", "name"]);
  await shot("glob without union: city column dropped");

  // With union: every file's columns, NULL where a file lacks one.
  await page.getByTestId("explorer-union").check();
  await expect(headers).toHaveText(["id", "name", "city"]);
  await expect(panel).toContainText("lisbon");
  await shot("glob with union by name: shared columns aligned, city added");
});

test("max entries cuts lists and says so", async ({ page, seeds, shot }) => {
  const nums = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0"));
  const files = nums.map((n) => `f${n}.csv`);
  const folders = nums.map((n) => `d${n}`);
  await connectFolder(page, await seeds.wideFolder());
  const options = page.getByTestId("db-select").getByRole("option");
  const status = page.getByTestId("connection-status");
  // The default 1000 lists all twelve of each.
  await expect(names(page)).toHaveText([...files, "*.csv"]);
  await expect(page.getByTestId("explorer-truncated")).toHaveCount(0);

  // Max entries 10: the first ten files (and a glob over just those), ten folders.
  const limit = page.getByTestId("explorer-max-entries");
  await limit.fill("10");
  await limit.press("Enter");
  await expect(names(page)).toHaveText([...files.slice(0, 10), "*.csv"]);
  await expect(page.getByTestId("explorer-truncated")).toContainText("More than 10 files");
  await shot("max entries 10: file list cut, with notice");
  await page.locator('[data-testid="explorer-table"][data-table="*.csv"]').click();
  await expect(page.getByTestId("explorer-panel").locator("tbody tr")).toHaveCount(10);
  await status.click();
  await expect(options).toHaveText(folders.slice(0, 10));
  await expect(page.getByTestId("db-select-truncated")).toContainText("More than 10 folders");
  await shot("max entries 10: folder list cut, with notice");
  await status.click();

  // The setting survives a reload: it lives in the session.
  await page.reload();
  await expect(limit).toHaveValue("10");
  await expect(names(page)).toHaveText([...files.slice(0, 10), "*.csv"]);

  // Raise it to 12: everything is listed again, no notices.
  await limit.fill("12");
  await limit.press("Enter");
  await expect(names(page)).toHaveText([...files, "*.csv"]);
  await expect(page.getByTestId("explorer-truncated")).toHaveCount(0);
  await status.click();
  await expect(options).toHaveText(folders);
  await expect(page.getByTestId("db-select-truncated")).toHaveCount(0);
});

test("reopening a connection goes back to its last folder and file", async ({ page, seeds, shot }) => {
  await connectFolder(page, await seeds.folder(), "lv-folder");
  const status = page.getByTestId("connection-status");
  await status.click();
  await page.getByTestId("db-select").getByRole("option").first().click();
  await expect(status).toContainText("· sub");
  await page.locator('[data-testid="explorer-table"][data-table="nested.csv.gz"]').click();
  await expect(page.getByTestId("explorer-panel")).toContainText("gamma");
  // Visiting another page and coming back through the nav keeps the memory.
  await page.getByTestId("nav-studio").click();
  await page.getByTestId("nav-explorer").click();
  await expect(page.getByTestId("explorer-tables")).toBeVisible();

  // Switch to another connection, then reopen the first from its card.
  await openConnect(page);
  await startNewConnection(page, "duckdb");
  await page.getByTestId("duck-name").fill("lv-other");
  await page.getByTestId("duck-connect").click();
  await expect(status).toContainText("lv-other");
  await openConnect(page);
  await page.locator('[data-testid="conn-card"][data-conn="lv-folder"]').click();

  // Straight back to the folder and the file, with its rows.
  await expect(status).toContainText("lv-folder · sub");
  await expect(page).toHaveURL(/\/explorer\?table=nested\.csv\.gz/);
  await expect(page.getByTestId("explorer-table-name")).toHaveText("nested.csv.gz");
  await expect(page.getByTestId("explorer-panel")).toContainText("gamma");
  await shot("reopened connection: back on its last folder and file");
});
