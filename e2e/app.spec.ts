import type { Page } from "@playwright/test";
import {
  CASES,
  CH,
  CH_HOST,
  CH_PASSWORD,
  CH_PORT,
  CH_USER,
  DUCK,
  api,
  authorParamsYaml,
  chDb,
  chExec,
  connCard,
  connect,
  expect,
  openClickhousePicker,
  openConnect,
  openQueryPanel,
  sessionId,
  startNewConnection,
  tableRow,
  test,
} from "./fixtures";

// Drivers with a database picker switch databases differently (ClickHouse
// passes the database per request, Postgres reconnects), so switching runs on
// both: the SQL naming the current database and another database to switch to.
// Both start on chDb(): the Postgres database has the same name.
const PICKER = CASES.filter((c) => !c.pathField);
const CURRENT_DB: Record<string, string> = { clickhouse: "currentDatabase()", postgres: "current_database()" };
const OTHER_DB: Record<string, string> = { clickhouse: "system", postgres: "postgres" };

async function switchDatabaseFromPill(page: Page, database: string): Promise<void> {
  await page.getByTestId("connection-status").click();
  await page.getByTestId("db-select-filter").fill(database);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("connection-status")).toContainText(`· ${database}`);
}

test("queryview e2e", async ({ page }) => {
  // loads the app and shows the heading
  await openConnect(page);
  await expect(page.locator("h1")).toHaveText("QueryView");

  // the ClickHouse "new connection" card opens its form, and Back returns
  await startNewConnection(page, "clickhouse");
  await expect(page.getByTestId("clickhouse-form")).toBeVisible();
  await page.getByTestId("form-back").click();
  await expect(page.getByTestId("clickhouse-form")).toHaveCount(0);
  await startNewConnection(page, "clickhouse");
  await expect(page.getByTestId("clickhouse-form")).toBeVisible();
  for (const id of ["ch-name", "ch-host", "ch-port", "ch-username", "ch-password"])
    await expect(page.getByTestId(id)).toBeVisible();

  // test connection succeeds against the real ClickHouse
  await page.getByTestId("ch-test").click();
  const result = page.getByTestId("ch-result");
  await expect(result).toBeVisible();
  await expect(result).toHaveAttribute("data-ok", "true");
  await expect(result).toContainText("Connected");

  // connect opens the database picker
  await page.getByTestId("ch-connect").click();
  await expect(page.getByTestId("db-picker")).toBeVisible();
  await expect(page.locator('[data-db="default"]')).toBeVisible();
  // The picker's Back returns to the cards; with no database visited yet, the
  // card opens the picker again.
  let card = connCard(page, "clickhouse");
  await page.getByTestId("picker-back").click();
  await expect(page.getByTestId("db-picker")).toHaveCount(0);
  await card.click();
  // The picker's filter narrows the chips (a non-match hides `default`).
  const dbFilter = page.getByTestId("db-filter");
  await dbFilter.fill("sys");
  await expect(page.locator('[data-db="default"]')).toHaveCount(0);
  await expect(page.locator('[data-db="system"]')).toBeVisible();
  await dbFilter.fill("");

  // selecting a database shows the connected indicator and, because the
  // connection is now ready, lands on the explorer. The session's URL write is
  // fire-and-forget; wait for it so the reload below resumes the explorer.
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("/api/sessions/")),
    page.locator('[data-db="default"]').click(),
  ]);
  await expect(page.getByTestId("connection-indicator")).toBeVisible();
  await expect(page.getByTestId("connection-status")).toContainText("· default");
  await expect(page).toHaveURL(/\/explorer/);
  await expect(page.getByTestId("explorer-tables")).toBeVisible();

  // reload resumes the session, then reconnect and select the system database
  await page.goto("/", { waitUntil: "networkidle" });
  // Resume: came back connected to the previously selected database, and the
  // landing redirect picks the explorer over Connect.
  await expect(page.getByTestId("connection-status")).toContainText("· default");
  await expect(page).toHaveURL(/\/explorer/);
  // The saved connection's card, marked active and showing its database,
  // goes straight back to the database last visited in this session.
  await page.getByTestId("nav-connect").click();
  card = connCard(page, "clickhouse");
  await expect(card).toHaveAttribute("data-active", "true");
  await expect(card).toContainText("default");
  await card.click();
  await expect(page).toHaveURL(/\/explorer/);
  await expect(page.getByTestId("connection-status")).toContainText("· default");

  // opening with ?connection=<name> opens that connection, on its last database too.
  await page.goto("/?connection=clickhouse", { waitUntil: "networkidle" });
  await expect(page.getByTestId("connection-status")).toContainText("· default");
  await expect(page.getByTestId("db-picker")).toHaveCount(0);

  // the connection pill's database menu carries the same filter
  await page.getByTestId("connection-status").click();
  const menuFilter = page.getByTestId("db-select-filter");
  await expect(menuFilter).toBeVisible();
  await menuFilter.fill("zzz");
  await expect(page.getByTestId("db-select-empty")).toBeVisible();
  await menuFilter.fill("sys");
  await expect(page.getByTestId("db-select").getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("connection-status")).toContainText("· system");
});

for (const c of PICKER) {
  test(`a database switch reruns the query on screen [${c.id}]`, async ({ page, seeds }) => {
    await connect(page, c, await seeds[c.seed]());
    const other = OTHER_DB[c.id];
    await openQueryPanel(page);
    await page.getByTestId("query-input").fill(`SELECT ${CURRENT_DB[c.id]} AS db`);
    await page.getByTestId("query-run").click();
    const output = page.getByTestId("query-output");
    await expect(output).toContainText(chDb());

    // An edit since the run is not what produced the results: the re-run is of
    // the run's own query, and the edit stays in the editor.
    await page.getByTestId("query-input").fill("SELECT 'edited'");
    await switchDatabaseFromPill(page, other);
    await expect(output).toContainText(other);
    await expect(output).not.toContainText(chDb());
    await expect(output).not.toContainText("edited");
    await expect(page.getByTestId("query-input")).toHaveValue("SELECT 'edited'");
  });

  test(`a database switch refreshes param options [${c.id}]`, async ({ page, seeds }) => {
    // `options_sql` choices are resolved on the session, so they follow its
    // database like the results do.
    await connect(page, c, await seeds[c.seed]());
    const other = OTHER_DB[c.id];
    await openQueryPanel(page);
    await authorParamsYaml(
      page,
      "by-database",
      "SELECT {db} AS picked",
      `params:\n  - name: db\n    options_sql: SELECT ${CURRENT_DB[c.id]}\n`,
    );
    const sel = page.locator('[data-testid="param-select"][data-param="db"]');
    await expect(sel.locator("option").first()).toHaveText(chDb());

    await switchDatabaseFromPill(page, other);
    await expect(sel.locator("option").first()).toHaveText(other);
  });

  test(`a database switch reruns with the new database param options [${c.id}]`, async ({ page, seeds }) => {
    // The re-run a database switch triggers substitutes `options_sql` values
    // resolved on the new database, not the ones the old database produced.
    await connect(page, c, await seeds[c.seed]());
    const other = OTHER_DB[c.id];
    await openQueryPanel(page);
    await authorParamsYaml(
      page,
      "by-database-run",
      "SELECT {db} AS picked",
      `params:\n  - name: db\n    options_sql: SELECT ${CURRENT_DB[c.id]}\n`,
    );
    await page.getByTestId("query-run").click();
    const output = page.getByTestId("query-output");
    await expect(output).toContainText(chDb());

    await switchDatabaseFromPill(page, other);
    await expect(output).toContainText(other);
    await expect(output).not.toContainText(chDb());
  });
}

test("the pill menu relists databases on open", async ({ page, seeds }) => {
  // A database created after connecting shows up the next time the pill menu
  // opens, without reconnecting.
  await seeds.testDb();
  const fresh = `${chDb()}_fresh`;
  await connect(page, CH, chDb());
  try {
    await chExec(`CREATE DATABASE IF NOT EXISTS ${fresh}`);
    await page.getByTestId("connection-status").click();
    await page.getByTestId("db-select-filter").fill(fresh);
    await expect(page.getByTestId("db-select").getByRole("option")).toHaveCount(1);
    await expect(page.getByTestId("db-select")).toContainText(fresh);
  } finally {
    await chExec(`DROP DATABASE IF EXISTS ${fresh}`);
  }
});

test("database names copy from the picker and the pill", async ({ page, context, seeds }) => {
  // A database name copies from its picker row (without selecting it) and,
  // once selected, from the status pill.
  await seeds.testDb();
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openClickhousePicker(page);
  await page.locator(`[data-db="${chDb()}"]`).locator("xpath=..").getByTestId("db-option-copy").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(chDb());
  await expect(page.getByTestId("db-picker")).toBeVisible();

  await page.locator(`[data-db="${chDb()}"]`).click();
  await expect(page.getByTestId("connection-status")).toContainText(chDb());
  await page.evaluate(() => navigator.clipboard.writeText(""));
  await page.getByTestId("status-db-copy").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(chDb());
  await expect(page.getByTestId("db-select")).toHaveCount(0);
});

test("a database switched elsewhere reaches the tab on its heartbeat", async ({ page, seeds, baseURL }) => {
  // A switch this tab did not make (an API caller here; another tab is the
  // same path) reaches its pill and views on the next heartbeat.
  await seeds.testDb();
  await connect(page, CH, chDb());
  await expect(tableRow(page, "items")).toBeVisible();

  const r = await api(`${baseURL}/api/db/database`, {
    json: { database: "system" },
    headers: { "X-QV-Session": await sessionId(page) },
  });
  expect(r.body).toEqual({ ok: true });

  await expect(page.getByTestId("connection-status")).toContainText("· system");
  // The explorer reloads its sidebar for the new database.
  await expect(tableRow(page, "items")).toHaveCount(0);
  await expect(tableRow(page, "databases")).toBeVisible();
});

test("ready connection shows query panel", async ({ page, seeds }) => {
  // A ready connection never needs the `query` command: connecting lands on
  // the explorer, and Studio puts the panel up — first visit and after a
  // detour alike.
  await connect(page, DUCK, await seeds.duckdb());
  await expect(page.getByTestId("explorer-tables")).toBeVisible();

  await page.getByTestId("nav-studio").click();
  await expect(page.getByTestId("query-panel")).toBeVisible();

  await page.getByTestId("nav-explorer").click();
  await expect(page.getByTestId("explorer-tables")).toBeVisible();
  await page.getByTestId("nav-studio").click();
  await expect(page.getByTestId("query-panel")).toBeVisible();
});

test("connect page and disconnect", async ({ page, seeds }) => {
  // Connect keeps the cards up for a ready connection, and the pill's menu
  // (even a picker-less driver's) ends with Disconnect.
  await connect(page, DUCK, await seeds.duckdb());

  await page.getByTestId("nav-connect").click();
  await expect(page).toHaveURL(/\/connect/);
  await expect(connCard(page, "duckdb")).toHaveAttribute("data-active", "true");
  await expect(page.getByTestId("query-panel")).toHaveCount(0);

  await page.getByTestId("connection-status").click();
  await page.getByTestId("disconnect").click();
  await expect(page.getByTestId("connection-status")).toHaveCount(0);
  await expect(page).toHaveURL(/\/connect/);

  // Durable: a reload stays disconnected.
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByTestId("connection-status")).toHaveCount(0);
});

test("disconnected lands on connect", async ({ page }) => {
  // A disconnected session opens on /connect, and Studio sends it there too:
  // the query panel needs a database. The old /prompt URL redirects.
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByTestId("connect-page")).toBeVisible();

  await page.getByTestId("nav-studio").click();
  await expect(page).toHaveURL(/\/connect$/);

  await page.goto("/prompt", { waitUntil: "networkidle" });
  await expect(page).toHaveURL(/\/connect$/);
});

test("many connections", async ({ page, seeds, baseURL }) => {
  // Past six saved connections: Recent row, a capped scrolling list, search
  // with a count and arrow-key highlight, driver chips, and "+ New" alone.
  await seeds.testDb();
  await page.goto("/connect", { waitUntil: "networkidle" });
  const bulk = Array.from({ length: 14 }, (_, i) => ({
    type: "duckdb",
    name: `bulk-${String(i).padStart(2, "0")}`,
    path: ":memory:",
  }));
  const ch = { type: "clickhouse", name: "bulk-ch", host: CH_HOST, port: CH_PORT, username: CH_USER, password: CH_PASSWORD };
  // ClickHouse first: the last save becomes the session's connection, and a
  // picker-less DuckDB keeps the cards up rather than a database picker.
  const sid = await sessionId(page);
  for (const config of [ch, ...bulk])
    await api(`${baseURL}/api/db/connect`, { json: config, headers: { "X-QV-Session": sid } });
  await openConnect(page);

  // The most recent three get their own row; the rest scroll in a capped box.
  const recent = page.getByTestId("conn-recent").getByTestId("conn-card");
  await expect(recent).toHaveCount(3);
  await expect(recent.first()).toHaveAttribute("data-conn", "bulk-13");
  expect(await page.getByTestId("conn-all").evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);

  // Only "+ New" creates connections now; the cards are gone.
  await expect(page.getByTestId("new-conn-duckdb")).toHaveCount(0);
  await page.getByTestId("new-menu-toggle").click();
  await expect(page.getByTestId("new-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("new-menu")).toHaveCount(0);

  // Driver chips narrow to one driver.
  await page.locator('[data-testid="driver-chip"][data-type="clickhouse"]').click();
  await expect(page.getByTestId("conn-recent")).toHaveCount(0);
  const cards = page.getByTestId("conn-card");
  await expect(cards.first()).toBeVisible();
  for (let i = 0; i < (await cards.count()); i++) await expect(cards.nth(i)).toContainText("ClickHouse");
  await page.locator('[data-testid="driver-chip"][data-type=""]').click();

  // `/` focuses search, which matches the name and shows a count.
  await page.locator("h1").click();
  await page.keyboard.press("/");
  await expect(page.getByTestId("conn-filter")).toBeFocused();
  await page.keyboard.type("bulk-0");
  await expect(cards).toHaveCount(10);
  await expect(page.getByTestId("conn-count")).toContainText("10 of");

  // Arrows move the highlight; Enter opens the highlighted card, and a
  // picker-less DuckDB lands on the explorer.
  await expect(cards.first()).toHaveAttribute("data-highlighted", "true");
  await page.keyboard.press("ArrowDown");
  const second = cards.nth(1);
  await expect(second).toHaveAttribute("data-highlighted", "true");
  const name = await second.getAttribute("data-conn");
  expect(name).toBeTruthy();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/explorer/);
  await expect(page.getByTestId("connection-status")).toContainText(name!);
});

test("the query timeout chip is remembered with the session", async ({ page, seeds, shot }) => {
  // The header's Timeout chip shows the default, takes whole seconds in
  // 1..600, and keeps its value across a reload: it lives in the session.
  await connect(page, DUCK, await seeds.duckdb());
  const chip = page.getByTestId("query-timeout");
  await expect(chip).toHaveValue("30");

  await chip.fill("45");
  await chip.press("Enter");
  await expect(chip).toHaveValue("45");
  await shot("query timeout chip set to 45");
  await page.reload();
  await expect(chip).toHaveValue("45");

  // Out-of-range or blank entries clamp or keep the value.
  for (const [entry, shown] of [
    ["0", "1"],
    ["", "1"],
    ["9999", "600"],
  ]) {
    await chip.fill(entry);
    await chip.press("Enter");
    await expect(chip).toHaveValue(shown);
  }
});
