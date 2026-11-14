// What a New query draft's results table shows, beyond the generic connect ->
// query -> paginate -> CSV -> describe flow in drivers.spec.ts. The features
// that only see rows (pickers, long cells) run once on DuckDB, a file with no
// service; ClickHouse's own types (Array/Map/Tuple) run on ClickHouse.
import { readFileSync } from "node:fs";
import type { FrameLocator, Page } from "@playwright/test";
import { CH, DUCK, chDb, connect, executeSql, expect, openNewQuery, test } from "./fixtures";

/** Connect to ClickHouse, select the seeded db, open a New query draft. */
async function openChDraft(page: Page): Promise<FrameLocator> {
  await connect(page, CH, chDb());
  return openNewQuery(page);
}

test("default views for array map tuple", async ({ page, seeds, shot }) => {
  // Array/Map/Tuple columns get a built-in default view: a vertical list,
  // collapsed to the first 3 items with an expander. Types come with the
  // result, so a named tuple renders `name: value` and Array(Tuple) renders
  // each element by its inner view.
  await seeds.testDb();
  const frame = await openChDraft(page);
  await executeSql(
    page,
    "SELECT ['apple','banana','cherry','date','elderberry'] AS arr, map('x',1,'y',2) AS m, " +
      "CAST((1,'alpha'), 'Tuple(id Int32, name String)') AS tup, " +
      "CAST([(1,'a'),(2,'b'),(3,'c'),(4,'d')], 'Array(Tuple(id Int32, name String))') AS arr_tup",
  );
  const output = frame.getByTestId("qv-results");
  await expect(output).toBeVisible();

  const arr = output.getByTestId("cell-arr");
  await expect(arr).toContainText("apple");
  await expect(arr).toContainText("cherry");
  await expect(arr).not.toContainText("elderberry");
  await shot("default views: array/map/tuple collapsed");

  await expect(output.getByTestId("cell-m")).toContainText("x → 1");

  const tup = output.getByTestId("cell-tup");
  await expect(tup).toContainText("id: 1");
  await expect(tup).toContainText("name: alpha");

  const arrTup = output.getByTestId("cell-arr_tup");
  await expect(arrTup).toContainText("id: 1");
  await expect(arrTup).toContainText("name: c");
  await expect(arrTup).not.toContainText("name: d");

  await frame.getByTestId("cell-arr-toggle").click();
  await expect(arr).toContainText("elderberry");
  await expect(frame.getByTestId("cell-arr-toggle")).toContainText("collapse");
  await shot("default views: array expanded");
});

test("field pickers visibility and order by", async ({ page, seeds, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openNewQuery(page);
  await executeSql(page, "SELECT id, name FROM items");
  const output = frame.getByTestId("qv-results");
  const headers = output.locator("thead th");
  await expect(headers).toHaveCount(2);

  // Fields describes the query's output columns and reveals both pickers.
  await frame.getByTestId("qv-fields").click();
  await expect(frame.getByTestId("field-pickers")).toBeVisible();
  await expect(frame.getByTestId("fields-count")).toHaveText("2/2");
  await frame.getByTestId("fields-menu").click();
  await expect(frame.locator('[data-testid="field-toggle"]')).toHaveCount(2);
  const idToggle = frame.locator('[data-testid="field-toggle"][data-col="id"]');
  await expect(idToggle).toBeVisible();
  await expect(frame.locator('[data-testid="field-toggle"][data-col="name"]')).toBeVisible();
  await shot("fields described - both pickers");

  // Select fields is client-side: hiding `id` drops its column without re-running.
  let queries = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/db/query")) queries += 1;
  });
  await idToggle.click();
  await expect(headers).toHaveCount(1);
  await expect(headers).toContainText("name");
  await expect(idToggle).toHaveAttribute("data-on", "false");
  await shot("id column hidden (client-side)");

  // Clear all hides every column; Select all restores them.
  await frame.getByTestId("fields-clear").click();
  await expect(headers).toHaveCount(0);
  await shot("clear all - no columns");
  await frame.getByTestId("fields-select-all").click();
  await expect(headers).toHaveCount(2);
  await shot("select all - columns restored");
  expect(queries).toBe(0);

  // CSV exports all columns regardless of visibility.
  await idToggle.click();
  await expect(headers).toHaveCount(1);
  const [download] = await Promise.all([page.waitForEvent("download"), frame.getByTestId("qv-csv").click()]);
  const header = readFileSync(await download.path(), "utf-8").split("\n")[0];
  expect(header).toContain("id");
  expect(header).toContain("name");

  // Order by is server-side and re-queries at once, with the current limit:
  // name ASC, then DESC.
  await frame.getByTestId("qv-limit").fill("2");
  await frame.getByTestId("qv-limit").press("Enter");
  await expect(output.locator("tbody tr")).toHaveCount(2);
  await frame.getByTestId("orderby-menu").click();
  await frame.locator('[data-testid="orderby-add"][data-col="name"]').click();
  const chip = frame.locator('[data-testid="orderby-chip"][data-col="name"]');
  await expect(chip).toBeVisible();
  await expect(output.locator("tbody tr")).toContainText(["alpha", "beta"]);
  await chip.getByTestId("orderby-dir").click(); // ASC -> DESC
  await expect(chip.getByTestId("orderby-dir")).toHaveText("DESC");
  await expect(output.locator("tbody tr")).toContainText(["gamma", "beta"]);
  await expect(output).not.toContainText("alpha");
  await shot("ordered + limited results");
});

test("long cells scroll and open in the cell popup", async ({ page, seeds, shot }) => {
  // Columns fit their widest value up to a cap; a longer value scrolls in its
  // cell and gains a button that opens the full value, glyphed `{ }` for
  // JSON/YAML (opening on a parsed tree with a Raw toggle) or `⤢` otherwise.
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openNewQuery(page);
  await executeSql(
    page,
    "SELECT 'alpha' AS brief, " +
      `'{"service":"billing","ports":[8080,8443],"meta":{"region":"eu-west","labels":{"tier":"gold"}}}' AS payload, ` +
      "repeat('long text ', 12) AS notes",
  );
  const output = frame.getByTestId("qv-results");
  await expect(output).toBeVisible();

  const expand = (col: string) => output.locator(`[data-testid="cell-expand"][data-col="${col}"]`);
  await expect(expand("brief")).toHaveCount(0);
  await expect(expand("payload")).toHaveText("{ }");
  await expect(expand("notes")).toHaveText("⤢");

  // Both long columns stop at the same cap; the short one is only as wide as needed.
  const width = async (col: string) => (await output.locator(`thead th:has-text("${col}")`).boundingBox())!.width;
  const [brief, payload, notes] = [await width("brief"), await width("payload"), await width("notes")];
  // Sub-pixel rounding differs by a hundredth of a pixel between columns.
  expect(Math.abs(payload - notes)).toBeLessThan(1);
  expect(brief).toBeLessThan(payload / 2);
  await shot("long cells - fitted columns with expand buttons");

  await expand("payload").click();
  const modal = frame.getByTestId("cell-data-modal");
  const tree = modal.getByTestId("cell-data-tree");
  await expect(modal).toBeVisible();
  await expect(modal.getByTestId("cell-data-format")).toHaveText("json");
  await expect(tree).toContainText("service");
  await expect(tree).toContainText("billing");
  await shot("cell popup - parsed json tree");

  // Containers below the top level start folded; expanding one reveals it.
  await expect(tree).not.toContainText("gold");
  await modal.getByTestId("cell-data-row").filter({ hasText: "labels" }).getByTestId("cell-data-toggle").click();
  await expect(tree).toContainText("gold");
  await shot("cell popup - nested container expanded");

  // Raw shows the value exactly as the database returned it.
  await modal.getByTestId("cell-data-raw-toggle").click();
  await expect(modal.getByTestId("cell-data-raw")).toContainText('"service":"billing"');
  await modal.getByTestId("cell-data-close").click();
  await expect(modal).not.toBeVisible();

  // Long text that isn't JSON or YAML opens as raw text, with no format chip.
  await expand("notes").click();
  await expect(modal).toBeVisible();
  await expect(modal.getByTestId("cell-data-format")).toHaveCount(0);
  await expect(modal.getByTestId("cell-data-raw")).toContainText("long text");
  await shot("cell popup - raw long text");
});

test("a native map cell is labelled by its column type", async ({ page, seeds }) => {
  // A Map arrives from the driver as an object; the popup names it by its type.
  await seeds.testDb();
  const frame = await openChDraft(page);
  await executeSql(page, "SELECT map('service', ['billing', 'invoicing'], 'region', [repeat('eu-west ', 8)]) AS tags");
  await frame.getByTestId("qv-results").locator('[data-testid="cell-expand"][data-col="tags"]').click();

  const modal = frame.getByTestId("cell-data-modal");
  await expect(modal.getByTestId("cell-data-format")).toHaveText("Map");
  await expect(modal.getByTestId("cell-data-format")).toHaveAttribute("title", "Map(String, Array(String))");
  await expect(modal.getByTestId("cell-data-tree")).toContainText("service");
});

test("field menu keeps names beside long types", async ({ page, seeds }) => {
  // DESCRIBE spreads a named Tuple's long type over lines: the Fields menu
  // still shows the column's name, and the type keeps its real newlines.
  await seeds.testDb();
  const frame = await openChDraft(page);
  await executeSql(
    page,
    "SELECT 1 AS id, CAST([('d1', 'v1', 'repo', 42)], " +
      "'Array(Tuple(artifact_digest String, artifact_tag String, artifact_repo String, artifact_size UInt32))'" +
      ") AS artifacts",
  );
  await frame.getByTestId("qv-fields").click();
  await frame.getByTestId("fields-menu").click();

  const row = frame.locator('[data-testid="field-toggle"][data-col="artifacts"]');
  await expect(row.getByText("artifacts", { exact: true })).toBeVisible();
  await expect(row).toHaveAttribute("title", /\n/);
  await expect(row).not.toHaveAttribute("title", /\\n/);
});
