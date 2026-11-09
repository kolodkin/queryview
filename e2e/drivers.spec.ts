// The connect -> (pick db) -> query -> paginate -> CSV -> describe flow, for
// every driver. Driver-specific ClickHouse features (cell views, params,
// complex types) live in query.spec.ts.
import { readFileSync } from "node:fs";
import { CASES, caseById, connect, expect, openQueryPanel, test } from "./fixtures";

for (const c of CASES) {
  test(`connect, query, paginate, csv [${c.id}]`, async ({ page, seeds, shot }) => {
    await connect(page, c, await seeds[c.seed]());
    await shot(`${c.id} connected`);
    await openQueryPanel(page);

    const sql = "SELECT id, name FROM items ORDER BY id";
    await page.getByTestId("query-input").fill(sql);

    // Predefined save/load round-trip (driver-agnostic; queries are keyed by type).
    const select = page.getByTestId("query-predefined-select");
    page.once("dialog", (d) => d.accept("all items"));
    await select.selectOption("::new::");
    await page.getByTestId("query-save").click();
    await expect(select.locator('option[value="all items"]')).toHaveCount(1);
    await select.selectOption("");
    await page.getByTestId("query-input").fill("");
    await select.selectOption("all items");
    await expect(page.getByTestId("query-input")).toHaveValue(sql);
    await shot(`${c.id} saved predefined query`);

    // Pagination: limit 2 -> first page is alpha, beta (not gamma).
    await page.getByTestId("query-limit").fill("2");
    await page.getByTestId("query-run").click();
    const output = page.getByTestId("query-output");
    await expect(output).toBeVisible();
    await expect(output.locator("table thead th")).toContainText(["id", "name"]);
    await expect(output).toContainText("alpha");
    await expect(output).toContainText("beta");
    await expect(output).not.toContainText("gamma");
    await shot(`${c.id} results page 1`);

    // CSV download of the current page.
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("query-csv").click()]);
    const csv = readFileSync(await download.path(), "utf-8");
    expect(csv).toContain("name");
    expect(csv).toContain("alpha");

    // Next page: gamma (not alpha).
    await page.getByTestId("query-next").click();
    await expect(output).toContainText("gamma");
    await expect(output).not.toContainText("alpha");
    await shot(`${c.id} results page 2`);
  });

  test(`fields describe [${c.id}]`, async ({ page, seeds, shot }) => {
    await connect(page, c, await seeds[c.seed]());
    await openQueryPanel(page);
    await page.getByTestId("query-input").fill("SELECT id, name FROM items");
    await page.getByTestId("query-fields").click();
    await expect(page.getByTestId("field-pickers")).toBeVisible();
    await expect(page.getByTestId("fields-count")).toHaveText("2/2");
    await page.getByTestId("fields-menu").click();
    await expect(page.locator('[data-testid="field-toggle"]')).toHaveCount(2);
    await expect(page.locator('[data-testid="field-toggle"][data-col="id"]')).toBeVisible();
    await expect(page.locator('[data-testid="field-toggle"][data-col="name"]')).toBeVisible();
    await shot(`${c.id} describe fields`);
  });
}

test("postgres jsonb renders structured", async ({ page, seeds, shot }) => {
  // jsonb arrives as a collection, so it gets the default list view (like a
  // ClickHouse JSON column), not the serialized text.
  await connect(page, caseById("postgres"), await seeds.pgDb());
  await openQueryPanel(page);
  await page
    .getByTestId("query-input")
    .fill(`SELECT '{"region": "emea", "tier": 2}'::jsonb AS doc, '["a", "b", "c", "d", "e"]'::jsonb AS tags`);
  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
  await expect(output.getByTestId("cell-doc")).toContainText("region: emea");
  await expect(output.getByTestId("cell-doc")).toContainText("tier: 2");
  const items = output.getByTestId("cell-tags").locator(":scope > div");
  await expect(items).toHaveCount(3);
  await shot("postgres jsonb default view");
  await output.getByTestId("cell-tags-toggle").click();
  await expect(items).toHaveCount(5);
  await shot("postgres jsonb expanded");
});
