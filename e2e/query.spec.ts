// The generic connect -> query -> paginate -> CSV -> describe flow is in
// drivers.spec.ts. Here: query params run on every driver (substitution and
// options_sql go through it); the UI features that only see rows (cell views,
// pickers, long cells) run once on DuckDB, a file with no service;
// ClickHouse's own types (Array/Map/Tuple) run on ClickHouse.
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import {
  CASES,
  CH,
  DUCK,
  type DriverCase,
  authorParamsYaml,
  chDb,
  connect,
  expect,
  openQueryPanel,
  test,
} from "./fixtures";

/** Connect to ClickHouse, select the seeded db, open the panel. */
async function openChPanel(page: Page): Promise<void> {
  await connect(page, CH, chDb());
  await openQueryPanel(page);
}

async function openCasePanel(page: Page, c: DriverCase, seed: string): Promise<void> {
  await connect(page, c, seed);
  await openQueryPanel(page);
}

test("cell view renders link and custom html", async ({ page, seeds, shot }) => {
  // Saving a predefined query with a cell_view YAML map renders cells per the
  // map: `link` becomes an <a href> using {cell}, `custom` injects the
  // template with {cell} HTML-escaped. Both wrappers carry an automatic
  // data-testid="cell-<col>". The YAML is authored in a modal from the toolbar.
  await openCasePanel(page, DUCK, await seeds.duckdb());

  await page.getByTestId("query-input").fill("SELECT id, name FROM items ORDER BY id LIMIT 2");
  await shot("cell view toggle in toolbar");

  // Name the query first — the modal Save is disabled without a name.
  page.once("dialog", (d) => d.accept("with-views"));
  await page.getByTestId("query-predefined-select").selectOption("::new::");

  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await page
    .getByTestId("cell-view-input")
    .fill(
      "name:\n  type: link\n  value: https://example.com/{cell}\n" +
        'id:\n  type: custom\n  value: <strong style="color:#a5b4fc">{cell}</strong>\n',
    );
  await shot("cell view modal - YAML authored");

  // Save persists cell_view + sql under the selected name and closes the modal.
  await page.getByTestId("cell-view-save").click();
  await expect(page.getByTestId("cell-view-modal")).not.toBeVisible();
  await expect(page.getByTestId("query-predefined-select").locator('option[value="with-views"]')).toHaveCount(1);
  await shot("saved - modal closed");

  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
  await expect(output).toBeVisible();

  const link = output.getByTestId("cell-name").first();
  await expect(link).toBeVisible();
  await expect(link).toHaveText("alpha");
  await expect(link).toHaveAttribute("href", "https://example.com/alpha");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");

  const custom = output.getByTestId("cell-id").first();
  await expect(custom).toBeVisible();
  await expect(custom).toHaveText("1");
  await expect(custom.locator("strong")).toHaveText("1");
  await shot("results: name as link, id as custom HTML");
});

test("cell view row placeholder references other columns", async ({ page, seeds, shot }) => {
  // A template can reference other columns of the same row via `{row.<col>}`;
  // each row resolves against its own values.
  await openCasePanel(page, DUCK, await seeds.duckdb());

  await page.getByTestId("query-input").fill("SELECT id, name FROM items ORDER BY id LIMIT 2");
  page.once("dialog", (d) => d.accept("with-row-refs"));
  await page.getByTestId("query-predefined-select").selectOption("::new::");

  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await page
    .getByTestId("cell-view-input")
    .fill(
      "name:\n  type: link\n  value: https://example.com/items/{row.id}\n" +
        "id:\n  type: custom\n  value: <em>{cell}:{row.name}</em>\n",
    );
  await shot("cell view modal - row.* placeholders authored");
  await page.getByTestId("cell-view-save").click();
  await expect(page.getByTestId("cell-view-modal")).not.toBeVisible();

  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
  await expect(output).toBeVisible();

  const link = output.getByTestId("cell-name").first();
  await expect(link).toHaveText("alpha");
  await expect(link).toHaveAttribute("href", "https://example.com/items/1");
  await expect(output.getByTestId("cell-id").first().locator("em")).toHaveText("1:alpha");
  await shot("results: row.* placeholders resolved per row");
});

test("cell view cancel discards edits", async ({ page, seeds, shot }) => {
  // Cancel closes without saving, so author-time edits never leak through.
  await openCasePanel(page, DUCK, await seeds.duckdb());

  await page.getByTestId("query-input").fill("SELECT name FROM items ORDER BY id LIMIT 1");
  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await page.getByTestId("cell-view-input").fill("name:\n  type: link\n  value: https://example.com/{cell}\n");
  await shot("cell view modal - draft YAML before Cancel");
  await page.getByTestId("cell-view-cancel").click();
  await expect(page.getByTestId("cell-view-modal")).not.toBeVisible();

  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
  await expect(output).toBeVisible();
  // Nothing saved => no cell_view applied => plain text, no <a>.
  await expect(output.locator("a")).toHaveCount(0);
  await expect(output).toContainText("alpha");

  // Re-opening the modal shows the saved value (empty).
  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-input")).toHaveValue("");
});

test("default views for array map tuple", async ({ page, seeds, shot }) => {
  // Array/Map/Tuple columns get a built-in default view: a vertical list,
  // collapsed to the first 3 items with an expander. Types come from an
  // auto-DESCRIBE, so a named tuple renders `name: value` and Array(Tuple)
  // renders each element by its inner view.
  await seeds.testDb();
  await openChPanel(page);

  await page
    .getByTestId("query-input")
    .fill(
      "SELECT ['apple','banana','cherry','date','elderberry'] AS arr, map('x',1,'y',2) AS m, " +
        "CAST((1,'alpha'), 'Tuple(id Int32, name String)') AS tup, " +
        "CAST([(1,'a'),(2,'b'),(3,'c'),(4,'d')], 'Array(Tuple(id Int32, name String))') AS arr_tup",
    );
  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
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

  await page.getByTestId("cell-arr-toggle").click();
  await expect(arr).toContainText("elderberry");
  await expect(page.getByTestId("cell-arr-toggle")).toContainText("collapse");
  await shot("default views: array expanded");
});

test("field pickers visibility and order by", async ({ page, seeds, shot }) => {
  await openCasePanel(page, DUCK, await seeds.duckdb());
  await page.getByTestId("query-input").fill("SELECT id, name FROM items");

  // Fields describes the query's output columns and reveals both pickers.
  await page.getByTestId("query-fields").click();
  await expect(page.getByTestId("field-pickers")).toBeVisible();
  await expect(page.getByTestId("fields-count")).toHaveText("2/2");
  await page.getByTestId("fields-menu").click();
  await expect(page.locator('[data-testid="field-toggle"]')).toHaveCount(2);
  await expect(page.locator('[data-testid="field-toggle"][data-col="id"]')).toBeVisible();
  await expect(page.locator('[data-testid="field-toggle"][data-col="name"]')).toBeVisible();
  await shot("fields described - both pickers");

  // Execute renders both columns (the click also closes the fields menu).
  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
  const headers = output.locator("table thead th");
  await expect(output).toBeVisible();
  await expect(headers).toHaveCount(2);
  await shot("results with all columns");

  // Select fields is client-side: hiding `id` drops its column without re-running.
  await page.getByTestId("fields-menu").click();
  const idToggle = page.locator('[data-testid="field-toggle"][data-col="id"]');
  await idToggle.click();
  await expect(headers).toHaveCount(1);
  await expect(headers).toContainText("name");
  await expect(idToggle).toHaveAttribute("data-on", "false");
  await shot("id column hidden (client-side)");

  // Clear all hides every column; Select all restores them.
  await page.getByTestId("fields-clear").click();
  await expect(headers).toHaveCount(0);
  await shot("clear all - no columns");
  await page.getByTestId("fields-select-all").click();
  await expect(headers).toHaveCount(2);
  await shot("select all - columns restored");

  // CSV exports all columns regardless of visibility.
  await idToggle.click();
  await expect(headers).toHaveCount(1);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("query-csv").click()]);
  const header = readFileSync(await download.path(), "utf-8").split("\n")[0];
  expect(header).toContain("id");
  expect(header).toContain("name");

  // Order by name DESC (server-side) applies only when the query re-runs; the
  // order-by Run button re-runs it (like Execute), with the current limit.
  await page.getByTestId("orderby-menu").click();
  await page.locator('[data-testid="orderby-add"][data-col="name"]').click();
  const chip = page.locator('[data-testid="orderby-chip"][data-col="name"]');
  await expect(chip).toBeVisible();
  await chip.getByTestId("orderby-dir").click(); // ASC -> DESC
  await expect(chip.getByTestId("orderby-dir")).toHaveText("DESC");
  await shot("order by name DESC selected");
  await page.getByTestId("query-limit").fill("2");
  await page.getByTestId("orderby-run").click();
  await expect(output).toContainText("gamma");
  await expect(output).toContainText("beta");
  await expect(output).not.toContainText("alpha");
  await shot("ordered + limited results (order-by Run)");
});

for (const c of CASES) {
  test(`query param dropdown substitutes value [${c.id}]`, async ({ page, seeds, shot }) => {
    // A `params:` block renders a dropdown per param; the selected value is
    // substituted via {name} (auto-quoted) and the query re-runs on change.
    await openCasePanel(page, c, await seeds[c.seed]());
    await authorParamsYaml(
      page,
      "by-name",
      "SELECT name FROM items WHERE name = {sel} ORDER BY id",
      "params:\n  - name: sel\n    options: [alpha, beta, gamma]\n",
    );

    const sel = page.locator('[data-testid="param-select"][data-param="sel"]');
    await expect(sel).toBeVisible();
    await expect(sel.locator("option")).toHaveCount(3);
    await shot(`${c.id} params dropdown rendered`);

    // An unquoted value would be an SQL error, not a filtered result.
    await sel.selectOption("beta");
    const output = page.getByTestId("query-output");
    await expect(output).toBeVisible();
    await expect(output).toContainText("beta");
    await expect(output).not.toContainText("alpha");
    await expect(output).not.toContainText("gamma");
    await shot(`${c.id} query re-run with sel=beta`);

    await sel.selectOption("gamma");
    await expect(output).toContainText("gamma");
    await expect(output).not.toContainText("beta");
    await shot(`${c.id} query re-run with sel=gamma`);
  });

  test(`query param options_sql populates dropdown [${c.id}]`, async ({ page, seeds, shot }) => {
    // `options_sql` resolves the choices from a query, in its own order; the
    // first row is the default.
    await openCasePanel(page, c, await seeds[c.seed]());
    await authorParamsYaml(
      page,
      "by-options-sql",
      "SELECT name FROM items WHERE name = {sel} ORDER BY id",
      "params:\n  - name: sel\n    options_sql: SELECT DISTINCT name FROM items ORDER BY name\n",
    );

    const sel = page.locator('[data-testid="param-select"][data-param="sel"]');
    await expect(sel).toBeVisible();
    await expect(sel.locator("option")).toHaveCount(3);
    await expect(sel.locator("option").first()).toHaveText("alpha");
    await shot(`${c.id} options_sql dropdown populated`);

    await page.getByTestId("query-run").click();
    const output = page.getByTestId("query-output");
    await expect(output).toBeVisible();
    await expect(output).toContainText("alpha");
    await expect(output).not.toContainText("beta");
    await shot(`${c.id} options_sql default (alpha) run`);

    await sel.selectOption("gamma");
    await expect(output).toContainText("gamma");
    await expect(output).not.toContainText("alpha");
    await shot(`${c.id} options_sql re-run with sel=gamma`);
  });
}

test("query param options and options_sql are mutually exclusive", async ({ page, seeds, shot }) => {
  // Both keys on one param is a config error: the save is rejected, so the
  // modal stays open and no dropdown renders.
  await openCasePanel(page, DUCK, await seeds.duckdb());
  await page.getByTestId("query-input").fill("SELECT name FROM items WHERE name = {sel} ORDER BY id");
  page.once("dialog", (d) => d.accept("both-keys"));
  await page.getByTestId("query-predefined-select").selectOption("::new::");
  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await page
    .getByTestId("cell-view-input")
    .fill("params:\n  - name: sel\n    options: [alpha, beta]\n    options_sql: SELECT name FROM items\n");
  await page.getByTestId("cell-view-save").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await shot("both options + options_sql -> save rejected");
  await page.getByTestId("cell-view-cancel").click();
  await expect(page.getByTestId("query-error")).toContainText("invalid cell_view");
  await expect(page.locator('[data-testid="param-select"][data-param="sel"]')).toHaveCount(0);
});

test("query param options_sql no rows blocks run", async ({ page, seeds, shot }) => {
  await openCasePanel(page, DUCK, await seeds.duckdb());
  await authorParamsYaml(
    page,
    "empty-options",
    "SELECT name FROM items WHERE name = {sel}",
    "params:\n  - name: sel\n    options_sql: SELECT name FROM items WHERE 1 = 0\n",
  );
  const error = page.getByTestId("query-error");
  await expect(error).toBeVisible();
  await expect(error).toContainText('options for "sel"');
  await expect(error).toContainText("no rows");
  await expect(page.getByTestId("query-run")).toBeDisabled();
  await shot("options_sql empty -> blocked");
});

test("query param options_sql error blocks run", async ({ page, seeds, shot }) => {
  await openCasePanel(page, DUCK, await seeds.duckdb());
  await authorParamsYaml(
    page,
    "bad-options",
    "SELECT name FROM items WHERE name = {sel}",
    "params:\n  - name: sel\n    options_sql: SELECT name FROM no_such_table\n",
  );
  const error = page.getByTestId("query-error");
  await expect(error).toBeVisible();
  await expect(error).toContainText('options for "sel"');
  await expect(page.getByTestId("query-run")).toBeDisabled();
  await shot("options_sql error -> blocked");
});

test("long cells scroll and open in the cell popup", async ({ page, seeds, shot }) => {
  // Columns fit their widest value up to a cap; a longer value scrolls in its
  // cell and gains a button that opens the full value, glyphed `{ }` for
  // JSON/YAML (opening on a parsed tree with a Raw toggle) or `⤢` otherwise.
  await openCasePanel(page, DUCK, await seeds.duckdb());

  await page
    .getByTestId("query-input")
    .fill(
      "SELECT 'alpha' AS brief, " +
        `'{"service":"billing","ports":[8080,8443],"meta":{"region":"eu-west","labels":{"tier":"gold"}}}' AS payload, ` +
        "repeat('long text ', 12) AS notes",
    );
  await page.getByTestId("query-run").click();
  const output = page.getByTestId("query-output");
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
  const modal = page.getByTestId("cell-data-modal");
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
  await openChPanel(page);
  await page
    .getByTestId("query-input")
    .fill("SELECT map('service', ['billing', 'invoicing'], 'region', [repeat('eu-west ', 8)]) AS tags");
  await page.getByTestId("query-run").click();
  await page.getByTestId("query-output").locator('[data-testid="cell-expand"][data-col="tags"]').click();

  const modal = page.getByTestId("cell-data-modal");
  await expect(modal.getByTestId("cell-data-format")).toHaveText("Map");
  await expect(modal.getByTestId("cell-data-format")).toHaveAttribute("title", "Map(String, Array(String))");
  await expect(modal.getByTestId("cell-data-tree")).toContainText("service");
});

test("field menu keeps names beside long types", async ({ page, seeds }) => {
  // DESCRIBE spreads a named Tuple's long type over lines: the Fields menu
  // still shows the column's name, and the type keeps its real newlines.
  await seeds.testDb();
  await openChPanel(page);
  await page
    .getByTestId("query-input")
    .fill(
      "SELECT 1 AS id, CAST([('d1', 'v1', 'repo', 42)], " +
        "'Array(Tuple(artifact_digest String, artifact_tag String, artifact_repo String, artifact_size UInt32))'" +
        ") AS artifacts",
    );
  await page.getByTestId("query-fields").click();
  await page.getByTestId("fields-menu").click();

  const row = page.locator('[data-testid="field-toggle"][data-col="artifacts"]');
  await expect(row.getByText("artifacts", { exact: true })).toBeVisible();
  await expect(row).toHaveAttribute("title", /\n/);
  await expect(row).not.toHaveAttribute("title", /\\n/);
});
