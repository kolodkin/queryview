// The connect -> (pick db) -> query -> paginate -> CSV -> describe flow, for
// every driver, through a New query draft on the Dashboard page. What the
// results table shows for a driver's own types (ClickHouse Array/Map/Tuple)
// lives in query.spec.ts.
import { readFileSync } from "node:fs";
import { CASES, caseById, connect, executeSql, expect, openNewQuery, test } from "./fixtures";

for (const c of CASES) {
  test(`connect, query, paginate, csv [${c.id}]`, async ({ page, seeds, shot }) => {
    await connect(page, c, await seeds[c.seed]());
    await shot(`${c.id} connected`);
    const frame = await openNewQuery(page);
    await executeSql(page, "SELECT id, name FROM items ORDER BY id");

    const output = frame.getByTestId("qv-results");
    await expect(output.locator("tbody tr")).toHaveCount(3);
    await expect(output.locator("thead th")).toContainText(["id", "name"]);

    // Pagination: limit 2 -> first page is alpha, beta (not gamma).
    await frame.getByTestId("qv-limit").fill("2");
    await frame.getByTestId("qv-limit").press("Enter");
    await expect(output.locator("tbody tr")).toHaveCount(2);
    await expect(output).toContainText("alpha");
    await expect(output).toContainText("beta");
    await expect(output).not.toContainText("gamma");
    await shot(`${c.id} results page 1`);

    // CSV of the current page: the app page downloads it, not the frame.
    const [download] = await Promise.all([page.waitForEvent("download"), frame.getByTestId("qv-csv").click()]);
    expect(download.suggestedFilename()).toBe("query.csv");
    const csv = readFileSync(await download.path(), "utf-8");
    expect(csv).toContain("name");
    expect(csv).toContain("alpha");
    expect(csv).not.toContain("gamma");

    // Next page: gamma (not alpha).
    await frame.getByTestId("qv-next").click();
    await expect(output).toContainText("gamma");
    await expect(output).not.toContainText("alpha");
    await shot(`${c.id} results page 2`);
  });

  test(`fields describe [${c.id}]`, async ({ page, seeds, shot }) => {
    await connect(page, c, await seeds[c.seed]());
    const frame = await openNewQuery(page);
    await executeSql(page, "SELECT id, name FROM items");
    await frame.getByTestId("qv-fields").click();
    await expect(frame.getByTestId("field-pickers")).toBeVisible();
    await expect(frame.getByTestId("fields-count")).toHaveText("2/2");
    await frame.getByTestId("fields-menu").click();
    await expect(frame.locator('[data-testid="field-toggle"]')).toHaveCount(2);
    await expect(frame.locator('[data-testid="field-toggle"][data-col="id"]')).toBeVisible();
    await expect(frame.locator('[data-testid="field-toggle"][data-col="name"]')).toBeVisible();
    await shot(`${c.id} describe fields`);
  });
}

test("postgres jsonb renders structured", async ({ page, seeds, shot }) => {
  // jsonb arrives as a collection, so it gets the default list view (like a
  // ClickHouse JSON column), not the serialized text.
  await connect(page, caseById("postgres"), await seeds.pgDb());
  const frame = await openNewQuery(page);
  await executeSql(
    page,
    `SELECT '{"region": "emea", "tier": 2}'::jsonb AS doc, '["a", "b", "c", "d", "e"]'::jsonb AS tags`,
  );
  const output = frame.getByTestId("qv-results");
  await expect(output.getByTestId("cell-doc")).toContainText("region: emea");
  await expect(output.getByTestId("cell-doc")).toContainText("tier: 2");
  const items = output.getByTestId("cell-tags").locator(":scope > div");
  await expect(items).toHaveCount(3);
  await shot("postgres jsonb default view");
  await output.getByTestId("cell-tags-toggle").click();
  await expect(items).toHaveCount(5);
  await shot("postgres jsonb expanded");
});
