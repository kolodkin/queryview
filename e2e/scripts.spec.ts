// The Scripts page (`/scripts`): a flat SQL textbox that runs a `;`-separated
// script as written — writes included — leaving one status line and, when the
// last statement returned rows, a results table and an Open-in-Dashboard button,
// for every driver (same seeds as drivers.spec.ts).
import type { Page } from "@playwright/test";
import {
  CASES,
  CH,
  DUCK,
  type DriverCase,
  chDb,
  chExec,
  connect,
  dashboardFrame,
  dbExec,
  expect,
  test,
} from "./fixtures";

// A table the write round-trip creates: unique per run, so parallel workers
// sharing one database server never collide; dropTable cleans it up.
const DDL: Record<string, string> = {
  clickhouse: "CREATE TABLE {t} (id UInt32, name String) ENGINE = MergeTree ORDER BY id",
  postgres: "CREATE TABLE {t} (id integer, name text)",
  duckdb: "CREATE TABLE {t} (id INTEGER, name TEXT)",
  sqlite: "CREATE TABLE {t} (id INTEGER, name TEXT)",
};
// A temporary table: it lives on the run's connection (ClickHouse: its session).
const TEMP_DDL: Record<string, string> = {
  clickhouse: "CREATE TEMPORARY TABLE {t} (x UInt8)",
  postgres: "CREATE TEMP TABLE {t} (x integer)",
  duckdb: "CREATE TEMP TABLE {t} (x INTEGER)",
  sqlite: "CREATE TEMP TABLE {t} (x INTEGER)",
};

const uniqueTable = (prefix: string) => `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;

/** Drop a table the test created, straight on the server, whatever state the
 * UI was left in. */
async function dropTable(c: DriverCase, seed: string, table: string): Promise<void> {
  const sql = `DROP TABLE IF EXISTS ${table}`;
  if (c.id === "clickhouse") await chExec(`DROP TABLE IF EXISTS ${chDb()}.${table}`);
  else await dbExec(c.id === "postgres" ? "pg" : (c.id as "duckdb" | "sqlite"), seed, sql);
}

async function openScriptsPage(page: Page): Promise<void> {
  await page.getByTestId("nav-scripts").click();
  await expect(page.getByTestId("scripts-page")).toBeVisible();
}

for (const c of CASES) {
  test(`run all writes and shows the last select [${c.id}]`, async ({ page, seeds, shot }) => {
    const seed = await seeds[c.seed]();
    const table = uniqueTable("qv_sql");
    try {
      await connect(page, c, seed);
      await openScriptsPage(page);

      const select = `SELECT id, name FROM ${table} ORDER BY id`;
      const script = `${DDL[c.id].replace("{t}", table)};\nINSERT INTO ${table} (id, name) VALUES (1, 'one'), (2, 'two');\n${select}`;
      await page.getByTestId("scripts-input").fill(script);
      // Nothing has run yet: no rows to hand to a dashboard.
      await expect(page.getByTestId("scripts-open-dashboard")).toBeDisabled();
      await shot(`${c.id} script typed`);
      await page.getByTestId("scripts-run-all").click();

      // One status line for the run: how much ran, what the last statement left.
      const status = page.getByTestId("scripts-status");
      await expect(status).toContainText("3 statements");
      await expect(status).toContainText("2 rows");
      await expect(status).toContainText("ms");
      // The last statement returned rows: they're the table below the textbox.
      const output = page.getByTestId("scripts-output");
      await expect(output.locator("table thead th")).toContainText(["id", "name"]);
      await expect(output).toContainText("one");
      await expect(output).toContainText("two");
      await shot(`${c.id} script results`);

      // Open in Dashboard carries that SELECT over into a New query draft,
      // which runs it: the same rows, now pageable.
      await page.getByTestId("scripts-open-dashboard").click();
      await expect(page.getByTestId("dash-sql")).toHaveValue(select);
      const draft = dashboardFrame(page).getByTestId("qv-results");
      await expect(draft.locator("thead th")).toContainText(["id", "name"]);
      await expect(draft.locator("tbody tr")).toContainText(["one", "two"]);
      await shot(`${c.id} opened in Dashboard`);

      // Back on Scripts the script is still there; run just the DROP under the cursor.
      await openScriptsPage(page);
      const textarea = page.getByTestId("scripts-input");
      await expect(textarea).toHaveValue(script);
      await textarea.focus();
      await textarea.press("End"); // the cursor lands at the very end after focus
      await textarea.press("Control+End");
      await textarea.pressSequentially(`;\nDROP TABLE ${table}`);
      await page.getByTestId("scripts-run-current").click();
      await expect(status).not.toContainText("statements");
      await expect(status).toContainText("ms");
      await expect(page.getByTestId("scripts-output")).toHaveCount(0);
    } finally {
      await dropTable(c, seed, table);
    }
  });

  test(`statements share the run's connection [${c.id}]`, async ({ page, seeds }) => {
    // A temporary table made by one statement is there for the next: the run
    // is one connection (one server session on ClickHouse).
    await connect(page, c, await seeds[c.seed]());
    await openScriptsPage(page);

    const table = uniqueTable("qv_tmp");
    await page
      .getByTestId("scripts-input")
      .fill(`${TEMP_DDL[c.id].replace("{t}", table)}; INSERT INTO ${table} VALUES (7); SELECT x FROM ${table}`);
    await page.getByTestId("scripts-run-all").click();
    await expect(page.getByTestId("scripts-status")).toContainText("3 statements · 1 row");
    await expect(page.getByTestId("scripts-output")).toContainText("7");
  });
}

test("clickhouse row cap leaves subqueries alone", async ({ page, seeds }) => {
  // The cap is a setting on the ClickHouse session; it must bound only the
  // statement's own result, never what a subquery feeds it.
  await connect(page, CH, await seeds.testDb());
  await openScriptsPage(page);

  await page.getByTestId("scripts-input").fill("SELECT count() AS n FROM (SELECT number FROM numbers(200000))");
  await page.getByTestId("scripts-run-all").click();
  await expect(page.getByTestId("scripts-output")).toContainText("200000");
});

test("run all stops at the first failing statement", async ({ page, seeds, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openScriptsPage(page);

  await page.getByTestId("scripts-input").fill("SELECT 1 AS a; SELECT * FROM no_such_table; SELECT 2 AS b");
  await page.getByTestId("scripts-input").press("ControlOrMeta+Shift+Enter");

  // The second statement failed: the line says which and why, and the
  // statement itself is marked red in the textbox.
  const status = page.getByTestId("scripts-status");
  await expect(status).toHaveAttribute("data-ok", "false");
  await expect(status).toContainText("Statement #2 Failed - ");
  await expect(status).toContainText("no_such_table");
  await expect(status).not.toContainText("SELECT * FROM no_such_table");
  const mark = page.getByTestId("scripts-failed-mark");
  await expect(mark).toHaveText("SELECT * FROM no_such_table");
  await shot("failing statement marked");
  // Clicking into the textbox (to fix it) clears the mark — a keyboard run
  // leaves the focus there, so a click or a keystroke is what clears it.
  await page.getByTestId("scripts-input").click();
  await expect(mark).toHaveCount(0);
  // The last statement run failed, so there is no table to show.
  await expect(page.getByTestId("scripts-output")).toHaveCount(0);
  await expect(page.getByTestId("scripts-open-dashboard")).toBeDisabled();
});

test("run current runs the statement under the cursor", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openScriptsPage(page);

  const textarea = page.getByTestId("scripts-input");
  const headers = page.getByTestId("scripts-output").locator("table thead th");
  await textarea.fill("SELECT 1 AS a;\nSELECT * FROM no_such_table;\nSELECT 2 AS b");
  // Put the cursor inside the last statement and run it alone.
  await textarea.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(el.value.length - 3, el.value.length - 3));
  await textarea.press("ControlOrMeta+Enter");
  await expect(page.getByTestId("scripts-status")).toContainText("1 row");
  await expect(headers).toContainText(["b"]);

  // A selection wins over the cursor.
  await textarea.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(0, el.value.indexOf(";")));
  await page.getByTestId("scripts-run-current").click();
  await expect(headers).toContainText(["a"]);
});

test("sql text is remembered and results are not", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openScriptsPage(page);

  const script = "SELECT 1 AS a;\nSELECT 2 AS b";
  const textarea = page.getByTestId("scripts-input");
  await textarea.fill(script);
  await page.getByTestId("scripts-run-all").click();
  await expect(page.getByTestId("scripts-status")).toContainText("2 statements");

  await textarea.blur();
  await page.reload({ waitUntil: "networkidle" });
  await expect(textarea).toHaveValue(script);
  await expect(page.getByTestId("scripts-status")).toHaveCount(0);
  await expect(page.getByTestId("scripts-output")).toHaveCount(0);
});

test("textarea sizes collapse and expand", async ({ page, seeds, shot }) => {
  // Min collapses the textbox so the results get the room; the other steps
  // set its height in rows. The text survives every step.
  await connect(page, DUCK, await seeds.duckdb());
  await openScriptsPage(page);

  const textarea = page.getByTestId("scripts-input");
  await textarea.fill("SELECT 1 AS a");
  await page.getByTestId("scripts-run-all").click();
  await expect(page.getByTestId("scripts-output")).toBeVisible();

  await page.getByTestId("scripts-size-min").click();
  expect((await textarea.boundingBox())!.height).toBeLessThan(4); // just its (transparent) border
  await expect(page.getByTestId("scripts-output")).toBeVisible();
  await shot("textbox collapsed");

  await page.getByTestId("scripts-size-xl").click();
  await expect(textarea).toHaveAttribute("rows", "28");
  await expect(textarea).toHaveValue("SELECT 1 AS a");
});
