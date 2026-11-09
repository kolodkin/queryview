// The explorer page: table sidebar -> rows with the field/order-by selects and
// pagination, for every driver (same seeds as drivers.spec.ts).
import type { Route } from "@playwright/test";
import { CASES, CH, DUCK, chDb, chExec, connect, expect, tableRow, test } from "./fixtures";

// Mirrors DEFAULT_SIDEBAR_WIDTH in frontend/src/app/explorerSettings.ts.
const DEFAULT_WIDTH = 256;

/** A route handler that holds the response for `ms`, long enough for a loader
 * to be observable. */
const hold = (ms: number) => async (route: Route) => {
  await new Promise((r) => setTimeout(r, ms));
  // The page may have navigated away meanwhile; then there is nothing to continue.
  await route.continue().catch(() => {});
};

for (const c of CASES) {
  test(`explorer browse, order, fields, paginate [${c.id}]`, async ({ page, seeds, shot }) => {
    await connect(page, c, await seeds[c.seed]());

    await page.getByTestId("nav-explorer").click();
    await expect(page.getByTestId("explorer-tables")).toBeVisible();

    // Each sidebar entry carries the engine's estimates. ClickHouse and DuckDB
    // know the seeded row count immediately; a fresh Postgres table has no
    // reltuples estimate yet, so its subline is just the on-disk size. SQLite
    // keeps no estimates at all, so it has no subline.
    const meta = tableRow(page, "items").getByTestId("explorer-table-meta");
    if (c.id !== "sqlite") await expect(meta).toBeVisible();
    if (c.id === "clickhouse" || c.id === "duckdb") await expect(meta).toContainText("3 rows");
    await shot(`${c.id} explorer table list`);

    // Clicking a table selects it into the URL and loads its rows.
    await tableRow(page, "items").click();
    await expect(page).toHaveURL(/table=items/);
    const output = page.getByTestId("explorer-output");
    const headers = output.locator("table thead th");
    await expect(output).toBeVisible();
    await expect(headers).toContainText(["id", "name"]);
    await expect(output).toContainText("alpha");
    await expect(output).toContainText("gamma");
    await shot(`${c.id} explorer rows`);

    // The pickers come pre-populated from an automatic describe.
    await expect(page.getByTestId("field-pickers")).toBeVisible();
    await expect(page.getByTestId("fields-count")).toHaveText("2/2");

    // Order by id, flipped to DESC, re-runs immediately: gamma (id 3) first.
    await page.getByTestId("orderby-menu").click();
    await page.locator('[data-testid="orderby-add"][data-col="id"]').click();
    const chip = page.locator('[data-testid="orderby-chip"][data-col="id"]');
    await expect(chip).toBeVisible();
    await chip.getByTestId("orderby-dir").click();
    await expect(output.locator("tbody tr").first()).toContainText("gamma");
    await shot(`${c.id} explorer ordered desc`);

    // Hiding a field is client-side column visibility — no re-run.
    await page.getByTestId("fields-menu").click();
    const idToggle = page.locator('[data-testid="field-toggle"][data-col="id"]');
    await idToggle.click();
    await expect(headers).toHaveCount(1);
    await idToggle.click();
    await expect(headers).toHaveCount(2);

    // Pagination under the DESC order: limit 2 (applies on blur) shows
    // gamma, beta; the next page holds only alpha.
    await page.getByTestId("explorer-limit").fill("2");
    await page.keyboard.press("Tab");
    await expect(output).not.toContainText("alpha");
    await page.getByTestId("explorer-next").click();
    await expect(output).toContainText("alpha");
    await expect(output).not.toContainText("gamma");
    await shot(`${c.id} explorer page 2`);

    // Short values are left alone: no per-cell expand button in a normal table.
    await expect(output.locator('[data-testid="cell-expand"]')).toHaveCount(0);
    await shot(`${c.id} explorer short cells stay plain`);
  });
}

test("explorer stale run does not overwrite the newest", async ({ page, seeds }) => {
  // Adding an order-by column and flipping its direction fire two browse runs
  // back to back. The two are held at the network and released in reverse,
  // so the superseded ASC response always lands after the DESC one; the rows
  // shown must still be the newest run's.
  await connect(page, DUCK, await seeds.duckdb());

  await page.getByTestId("nav-explorer").click();
  await tableRow(page, "items").click();
  const output = page.getByTestId("explorer-output");
  await expect(output).toContainText("alpha");
  await expect(page.getByTestId("fields-count")).toHaveText("2/2");
  await page.getByTestId("orderby-menu").click();

  // From here on, hold every browse run instead of letting it reach the server.
  const held: Route[] = [];
  await page.route("**/api/db/query", (route) => {
    held.push(route);
  });

  const chip = page.locator('[data-testid="orderby-chip"][data-col="id"]');
  await Promise.all([
    page.waitForRequest("**/api/db/query"),
    page.locator('[data-testid="orderby-add"][data-col="id"]').click(), // id ASC
  ]);
  await Promise.all([page.waitForRequest("**/api/db/query"), chip.getByTestId("orderby-dir").click()]); // id DESC
  // The request fires before its route handler runs.
  await expect.poll(() => held.length).toBe(2);
  const [asc, desc] = held;

  // The DESC run answers first and its rows land.
  await desc.continue();
  await expect(output.locator("tbody tr").first()).toContainText("gamma");

  // The ASC run it superseded answers last, and must not win. Waiting on the
  // response keeps the assertion behind the app's handling of it.
  await Promise.all([page.waitForResponse("**/api/db/query"), asc.continue()]);
  await expect(output.locator("tbody tr").first()).toContainText("gamma");
});

test("refresh reloads the rows from the database", async ({ page, seeds }) => {
  // The refresh button next to the table name re-runs the browse query: a row
  // inserted since the last load appears, and the loader shows while the
  // request is in flight.
  await seeds.testDb();
  const table = `${chDb()}.fresh_rows`;
  await chExec(`CREATE TABLE ${table} (id UInt32, name String) ENGINE = MergeTree ORDER BY id`);
  try {
    await chExec(`INSERT INTO ${table} VALUES (1, 'first')`);
    await connect(page, CH, chDb());
    await page.getByTestId("nav-explorer").click();
    await tableRow(page, "fresh_rows").click();
    const output = page.getByTestId("explorer-output");
    await expect(output).toContainText("first");
    await expect(output).not.toContainText("second");

    await chExec(`INSERT INTO ${table} VALUES (2, 'second')`);
    await page.route("**/api/db/query", hold(500));
    await page.getByTestId("explorer-refresh").click();
    await expect(page.getByTestId("explorer-busy")).toBeVisible();
    await expect(output).toContainText("second");
    await expect(page.getByTestId("explorer-busy")).toHaveCount(0);
  } finally {
    await chExec(`DROP TABLE IF EXISTS ${table}`);
  }
});

test("sidebar width is draggable and remembered", async ({ page, seeds, shot }) => {
  // The Tables sidebar resizes from its right edge so long names need not be
  // truncated. The width is remembered per view and survives a reload; the
  // reset control puts it back to the default.
  await connect(page, DUCK, await seeds.duckdbLongNames());
  await page.getByTestId("nav-explorer").click();

  const aside = page.getByTestId("explorer-tables");
  await expect(aside).toBeVisible();
  await expect(aside).toHaveAttribute("data-width", String(DEFAULT_WIDTH));
  // No reset control while the sidebar is still at its default width.
  await expect(page.getByTestId("explorer-sidebar-reset")).toHaveCount(0);

  // The longest name doesn't fit the default width — the reason to resize.
  const longest = tableRow(page, "warehouse_shipment_reconciliation_log").locator("span").first();
  const truncated = () => longest.evaluate((e) => e.scrollWidth > e.clientWidth);
  expect(await truncated(), "expected truncation").toBe(true);
  await shot("explorer sidebar default width");

  // Drag the handle 120px to the right. Its centre sits on the panel's right
  // edge, so the dragged width is the default plus the travel.
  const box = (await page.getByTestId("explorer-sidebar-resize").boundingBox())!;
  const midY = box.y + box.height / 2;
  const centreX = box.x + box.width / 2;
  await page.mouse.move(centreX, midY);
  await page.mouse.down();
  await page.mouse.move(centreX + 120, midY, { steps: 10 });
  await page.mouse.up();
  await expect(aside).toHaveAttribute("data-width", String(DEFAULT_WIDTH + 120));
  // ...and now it does fit: the whole point of the drag.
  expect(await truncated(), "still truncated").toBe(false);
  await shot("explorer sidebar widened");

  // Remembered in the session, so it survives a reload.
  await page.reload({ waitUntil: "networkidle" });
  await expect(aside).toHaveAttribute("data-width", String(DEFAULT_WIDTH + 120));

  // Arrow keys nudge it; the reset control restores the default and then hides.
  await page.getByTestId("explorer-sidebar-resize").press("ArrowRight");
  await expect(aside).toHaveAttribute("data-width", String(DEFAULT_WIDTH + 136));
  await page.getByTestId("explorer-sidebar-reset").click();
  await expect(aside).toHaveAttribute("data-width", String(DEFAULT_WIDTH));
  await expect(page.getByTestId("explorer-sidebar-reset")).toHaveCount(0);
});

test("panels show loaders until data arrives", async ({ page, seeds, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());

  // Already on the explorer, so reload to refetch the list with the response held back.
  await page.route("**/api/db/tables", hold(1500));
  await page.reload();
  await expect(page.getByTestId("explorer-tables-loading")).toBeVisible();
  await shot("explorer tables loading");
  await expect(tableRow(page, "items")).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });

  await page.route("**/api/db/query", hold(1500));
  await tableRow(page, "items").click();
  await expect(page.getByTestId("explorer-rows-loading")).toBeVisible();
  await shot("explorer rows loading");
  await expect(page.getByTestId("explorer-output")).toBeVisible();
  await expect(page.getByTestId("explorer-rows-loading")).toHaveCount(0);
  // Drop any handler still holding a response, so page close doesn't race it.
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("table copy puts the name on the clipboard", async ({ page, context, seeds }) => {
  // Each table row's copy icon copies its name without opening the table.
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await connect(page, DUCK, await seeds.duckdb());

  await tableRow(page, "items").locator("xpath=..").getByTestId("explorer-table-copy").click();

  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("items");
  await expect(page).not.toHaveURL(/table=/);
});

test("table filter narrows the sidebar", async ({ page, seeds }) => {
  // Typing in the sidebar search narrows the list case-insensitively; Enter
  // opens the first match, and a miss says so.
  await connect(page, DUCK, await seeds.duckdbLongNames());
  const tables = page.getByTestId("explorer-table");
  await expect(tables).toHaveCount(3);

  const search = page.getByTestId("explorer-table-filter");
  await search.fill("SALES");
  await expect(tables).toHaveCount(1);
  await expect(tables.first()).toHaveAttribute("data-table", "sales_reporting_monthly_rollup");

  await search.press("Enter");
  await expect(page).toHaveURL(/table=sales_reporting_monthly_rollup/);

  await search.fill("nope");
  await expect(tables).toHaveCount(0);
  await expect(page.getByTestId("explorer-table-filter-empty")).toBeVisible();

  await search.fill("");
  await expect(tables).toHaveCount(3);
});
