// Renaming, deleting, undeleting and purging a saved (predefined) query from
// the query panel. Uses DuckDB and a uniquely-named workspace per run.
import type { Page } from "@playwright/test";
import { DUCK, api, connect, expect, openQueryPanel, switchWorkspace, test } from "./fixtures";

async function names(baseURL: string, ws: string, deleted = false): Promise<string[]> {
  const q = new URLSearchParams({ type: "duckdb", workspace: ws, include_deleted: "1" });
  const { body } = await api(`${baseURL}/api/predefined-queries?${q}`);
  return body.queries
    .filter((x: { deleted_at: string | null }) => (x.deleted_at !== null) === deleted)
    .map((x: { query_name: string }) => x.query_name);
}

/** Create a uniquely-named workspace saving `queries` (name -> saved fields),
 * connect DuckDB, switch to it and open the query panel. Returns its name. */
async function openNewWorkspace(
  page: Page,
  baseURL: string,
  seed: string,
  queries: Record<string, Record<string, string>> = {},
): Promise<string> {
  const ws = `e2e-pq-${crypto.randomUUID().slice(0, 6)}`;
  await api(`${baseURL}/api/workspaces`, { json: { name: ws } });
  for (const [name, fields] of Object.entries(queries))
    await api(`${baseURL}/api/predefined-queries`, { json: { query_name: name, type: "duckdb", workspace: ws, ...fields } });

  await connect(page, DUCK, seed);
  await switchWorkspace(page, ws);
  await openQueryPanel(page);
  return ws;
}

test("rename, delete, undelete and purge a saved query", async ({ page, seeds, baseURL, shot }) => {
  const ws = await openNewWorkspace(page, baseURL!, await seeds.duckdb());
  const live = () => names(baseURL!, ws);
  const deleted = () => names(baseURL!, ws, true);

  const select = page.getByTestId("query-predefined-select");
  const rename = page.getByTestId("query-rename");
  const del = page.getByTestId("query-delete");
  await expect(rename).toBeDisabled();
  await expect(del).toBeDisabled();

  // A new, not yet saved name can't be renamed or deleted.
  page.once("dialog", (d) => d.accept("pq first"));
  await select.selectOption("::new::");
  await expect(rename).toBeDisabled();
  await page.getByTestId("query-input").fill("SELECT id FROM items ORDER BY id");
  await page.getByTestId("query-save").click();
  await expect(rename).toBeEnabled();
  await shot("saved query: Rename and Delete enabled");

  page.once("dialog", (d) => d.accept("pq renamed"));
  await rename.click();
  await expect(select).toHaveValue("pq renamed");
  await expect(select.locator('option[value="pq first"]')).toHaveCount(0);
  expect(await live()).toEqual(["pq renamed"]);
  await shot("renamed");

  // Dismissing the confirmation keeps it.
  page.once("dialog", (d) => d.dismiss());
  await del.click();
  await expect(select).toHaveValue("pq renamed");
  expect(await live()).toEqual(["pq renamed"]);

  page.once("dialog", (d) => d.accept());
  await del.click();
  // Deleted, it stays selected (for Commit or Undelete) and keeps its SQL.
  await expect(select).toHaveValue("pq renamed");
  await expect(select.locator("option:checked")).toHaveText("pq renamed (deleted)");
  await expect(page.getByTestId("query-input")).toHaveValue("SELECT id FROM items ORDER BY id");
  await expect(page.getByTestId("query-undelete")).toBeVisible();
  await expect(rename).toBeDisabled();
  expect(await live()).toEqual([]);
  expect(await deleted()).toEqual(["pq renamed"]);
  await shot("deleted: still selected, Undelete offered");

  // Show deleted lists it in its own group; picking it loads its SQL.
  await select.selectOption("");
  await page.getByTestId("query-input").fill("");
  await select.selectOption("::deleted::");
  const group = page.getByTestId("query-deleted-group");
  await expect(group.locator("option")).toHaveText(["pq renamed"]);
  await select.selectOption("pq renamed");
  await expect(page.getByTestId("query-input")).toHaveValue("SELECT id FROM items ORDER BY id");
  await shot("show deleted: deleted group");

  await page.getByTestId("query-undelete").click();
  await expect(del).toBeEnabled();
  await expect(group).toHaveCount(0);
  expect(await live()).toEqual(["pq renamed"]);
  expect(await deleted()).toEqual([]);
  await shot("undeleted");

  // Purge clears the selection too.
  page.once("dialog", (d) => d.accept());
  await del.click();
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("query-purge").click();
  await expect(select).toHaveValue("");
  expect(await live()).toEqual([]);
  expect(await deleted()).toEqual([]);
  await shot("purged");
});

test("picking a saved query runs it", async ({ page, seeds, baseURL, shot }) => {
  await openNewWorkspace(page, baseURL!, await seeds.duckdb(), {
    "pq alpha": { query: "SELECT name FROM items WHERE id = 1" },
    "pq beta": { query: "SELECT name FROM items WHERE id = 2" },
    "pq broken": {
      query: "SELECT name FROM items WHERE name = {sel}",
      cell_view: "params:\n  - name: sel\n    options_sql: SELECT name FROM no_such_table\n",
    },
  });

  // Picking alone runs: Execute is never clicked.
  const select = page.getByTestId("query-predefined-select");
  const output = page.getByTestId("query-output");
  await select.selectOption("pq alpha");
  await expect(output).toContainText("alpha");
  await select.selectOption("pq beta");
  await expect(output).toContainText("beta");
  await expect(output).not.toContainText("alpha");
  await shot("swapped query: results follow the pick");

  // Param choices that fail to resolve block the run; the next pick still runs.
  await select.selectOption("pq broken");
  await expect(page.getByTestId("query-error")).toContainText('options for "sel"');
  await select.selectOption("pq alpha");
  await expect(output).toContainText("alpha");

  // A new name runs nothing: Execute's is the only run sent.
  const runs: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/db/query")) runs.push(r.url());
  });
  page.once("dialog", (d) => d.accept("pq new"));
  await select.selectOption("::new::");
  await expect(select).toHaveValue("pq new");
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/db/query")),
    page.getByTestId("query-run").click(),
  ]);
  expect(runs).toHaveLength(1);
});
