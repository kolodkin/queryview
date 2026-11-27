// Acceptance tests: one end-to-end journey per user goal stated in the user
// guide (docs/user_guide/), each under the `req:` ID it proves; how a feature
// behaves in detail is tested in the other spec files.
import { readFileSync } from "node:fs";
import {
  CASES,
  CH,
  DUCK,
  api,
  armRemote,
  chDb,
  chExec,
  connCard,
  connect,
  dashboardFrame,
  dbExec,
  executeSql,
  expect,
  gitConfigured,
  mcpCall,
  openConnect,
  openDashboard,
  openNewQuery,
  savePostgresMarks,
  startNewConnection,
  tableRow,
  test,
  uid,
} from "./fixtures";


// req: user_guide/connect/add-connection
for (const c of CASES) {
  test(`a new connection is saved [${c.id}]`, async ({ page, seeds, baseURL }) => {
    const seed = await seeds[c.seed]();
    const name = `saved-${c.id}-${uid()}`;
    try {
      // The form comes filled with the suite's server; a file driver takes the seed's path.
      await openConnect(page);
      await startNewConnection(page, c.id);
      await page.getByTestId(c.connectTestid.replace("-connect", "-name")).fill(name);
      if (c.pathField) await page.getByTestId(c.pathField).fill(seed);
      await page.getByTestId(c.connectTestid).click();
      await expect(page.getByTestId(`${c.id}-form`)).toHaveCount(0);

      // Coming back to the app, it is among the saved connections (a server
      // connection with no database picked yet reopens on its picker first).
      await openConnect(page);
      if (!c.pathField) await page.getByTestId("picker-back").click();
      await expect(connCard(page, name)).toBeVisible();
    } finally {
      await api(`${baseURL}/api/db/connections`, { method: "DELETE", json: { name } });
    }
  });
}

// req: user_guide/connect/open-database
test("connect, pick a database, find it reconnected after a reload", async ({ page }) => {
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

// req: user_guide/query/run-sql
test("run SQL, pick columns, page and download CSV", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openNewQuery(page);
  await executeSql(page, "SELECT id, name FROM items ORDER BY id");
  const output = frame.getByTestId("qv-results");
  const headers = output.locator("thead th");
  await expect(headers).toContainText(["id", "name"]);
  await expect(output.locator("tbody tr")).toHaveCount(3);

  // Hiding `id` drops its column; showing it brings it back.
  await frame.getByTestId("qv-fields").click();
  await frame.getByTestId("fields-menu").click();
  const idToggle = frame.locator('[data-testid="field-toggle"][data-col="id"]');
  await idToggle.click();
  await expect(headers).toHaveCount(1);
  await expect(headers).toContainText("name");
  await idToggle.click();
  await expect(headers).toHaveCount(2);
  await frame.getByTestId("fields-menu").click();

  // Pages of two: alpha and beta, then gamma.
  await frame.getByTestId("qv-limit").fill("2");
  await frame.getByTestId("qv-limit").press("Enter");
  await expect(output.locator("tbody tr")).toHaveCount(2);
  await expect(output).not.toContainText("gamma");
  await frame.getByTestId("qv-next").click();
  await expect(output).toContainText("gamma");
  await expect(output).not.toContainText("alpha");

  // The CSV is the page on screen.
  const [download] = await Promise.all([page.waitForEvent("download"), frame.getByTestId("qv-csv").click()]);
  const csv = readFileSync(await download.path(), "utf-8");
  expect(csv).toContain("gamma");
  expect(csv).not.toContain("alpha");
});

// req: user_guide/scripts/run-script
test("a script runs its writes and stops at the first error", async ({ page, seeds }) => {
  const seed = await seeds.duckdb();
  const table = `qv_accept_${uid()}`;
  try {
    await connect(page, DUCK, seed);
    await page.getByTestId("nav-scripts").click();
    const input = page.getByTestId("scripts-input");
    const status = page.getByTestId("scripts-status");
    const output = page.getByTestId("scripts-output");

    await input.fill(`CREATE TABLE ${table} (id INTEGER, name TEXT); INSERT INTO ${table} VALUES (1, 'one'); SELECT name FROM ${table}`);
    await page.getByTestId("scripts-run-all").click();
    await expect(status).toContainText("3 statements");
    await expect(output).toContainText("one");

    // The second statement fails: the line says which and why, and the third never runs.
    await input.fill(`INSERT INTO ${table} VALUES (2, 'two'); SELECT * FROM no_such_table; INSERT INTO ${table} VALUES (3, 'three')`);
    await page.getByTestId("scripts-run-all").click();
    await expect(status).toContainText("Statement #2 Failed - ");
    await expect(status).toContainText("no_such_table");

    await input.fill(`SELECT name FROM ${table} ORDER BY id`);
    await page.getByTestId("scripts-run-all").click();
    await expect(status).toContainText("2 rows");
    await expect(output).toContainText("two");
    await expect(output).not.toContainText("three");
  } finally {
    await dbExec("duckdb", seed, `DROP TABLE IF EXISTS ${table}`);
  }
});

// req: user_guide/explorer/browse-tables
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

// req: user_guide/dashboard/live-dashboard
test("a saved dashboard shows its data as it is now", async ({ page, seeds, baseURL }) => {
  await seeds.testDb();
  const table = `${chDb()}.live_${uid()}`;
  await chExec(`CREATE TABLE ${table} (name String) ENGINE = MergeTree ORDER BY name`);
  try {
    await chExec(`INSERT INTO ${table} VALUES ('alpha')`);
    await connect(page, CH, chDb());
    const name = `live ${uid()}`;
    const frame = await openDashboard(page, baseURL, {
      name,
      html: "<div id='out'></div><script>document.getElementById('out').textContent = window.queries.rows.name.join(',')</script>",
      queries: { rows: `SELECT name FROM ${table} ORDER BY name` },
    });
    await expect(frame.locator("#out")).toHaveText("alpha");

    // A row added since: reopening the dashboard by its link shows it.
    await chExec(`INSERT INTO ${table} VALUES ('beta')`);
    await page.goto(`/dashboard?name=${encodeURIComponent(name)}`);
    await expect(frame.locator("#out")).toHaveText("alpha,beta");
  } finally {
    await chExec(`DROP TABLE IF EXISTS ${table}`);
  }
});

// req: user_guide/gitsync/workspace-git, user_guide/gitsync/restore-ui, user_guide/gitsync/not-in-git
test("git save and restore dashboard round trip", async ({ page, baseURL, seeds, shot }) => {
  test.skip(!(await gitConfigured(baseURL!)), "git sync is not configured for this stack");
  // Unique per attempt: a CI retry shares the remote, which keeps the first
  // attempt's commit.
  const name = `gs e2e ${uid(6)}`;
  const save = (v: number) =>
    api(`${baseURL}/api/dashboards`, {
      json: { name, html: `<html><body>v${v}</body></html>`, queries: { q: `SELECT ${v}` } },
    });

  // Each Save is one commit; restore v1 from the revision list.
  expect((await save(1)).body.committed).toBe(true);
  await save(2);
  // A YAML import overwrites the row outside git: the picker marks it until a restore.
  const doc = `kind: dashboard\nname: ${name}\nhtml: <p>v3</p>\nqueries:\n  q: SELECT 3\n`;
  expect((await fetch(`${baseURL}/api/import`, { method: "POST", body: doc })).ok).toBe(true);
  // Connected, so the dashboard renders instead of asking for a database.
  await connect(page, DUCK, await seeds.duckdb());
  await page.goto(`/dashboard?name=${encodeURIComponent(name)}`);
  await expect(dashboardFrame(page).locator("body")).toContainText("v3");
  const option = page.getByTestId("dashboard-select").locator("option", { hasText: name });
  await expect(option).toHaveText(`${name} · not in git`);
  await shot("imported dashboard marked not in git");
  page.on("dialog", (d) => d.accept());
  await page.getByTestId("git-restore-toggle").click();
  const rows = page.getByTestId("git-revision-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText(`store dashboard ${name}`);
  await rows.last().getByTestId("git-revision-restore").click();
  // The picker closes on a successful restore; only then check the store.
  await expect(page.getByTestId("git-revisions")).toBeHidden();
  await expect(option).toHaveText(name);
  await expect(dashboardFrame(page).locator("body")).toContainText("v1");
  await shot("restored dashboard no longer marked");
  const { body } = await api(`${baseURL}/api/dashboards/${encodeURIComponent(name)}`);
  expect(body.html).toContain("v1");
  expect(body.queries).toEqual({ q: "SELECT 1" });
});

// req: user_guide/export-import/yaml-export-import, user_guide/export-import/ui
test("dashboard export import round trip", async ({ page, baseURL, shot }, testInfo) => {
  // Download a dashboard as YAML from the UI, drift the stored copy, then
  // import the downloaded file back and verify it overwrote the drift.
  const save = (v: number) =>
    api(`${baseURL}/api/dashboards`, {
      json: { name: "yio e2e", html: `<html><body>v${v}</body></html>`, queries: { q: `SELECT ${v}` } },
    });
  await save(1);

  await page.goto("/dashboard?name=yio%20e2e");
  await expect(page.getByTestId("yaml-export")).toBeEnabled();
  await shot("dashboard with export-import controls");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("yaml-export").click()]);
  expect(download.suggestedFilename()).toBe("yio e2e.dashboard.yaml");
  const saved = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(saved);
  const text = readFileSync(saved, "utf-8");
  expect(text).toContain("kind: dashboard");
  expect(text).toContain("v1");

  // Drift the stored copy to v2, then import the downloaded v1 file back.
  await save(2);
  await page.getByTestId("yaml-import-file").setInputFiles(saved);
  await expect(page.getByTestId("yaml-import")).toHaveText("Imported");
  await shot("imported yaml overwrote the drifted copy");
  const { body } = await api(`${baseURL}/api/dashboards/yio%20e2e`);
  expect(body.html).toContain("v1");
  expect(body.queries).toEqual({ q: "SELECT 1" });
});

// req: user_guide/mcp/agent-drives, user_guide/mcp/arming, user_guide/scripts/agent-push, user_guide/query/edit-lock
test("mcp push_script fills and runs the scripts editor", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const sid = await armRemote(page);

  const script = "SELECT 1 AS a; SELECT name FROM items ORDER BY id";
  const out = await mcpCall(baseURL!, "push_script", { session_id: sid, sql: script, run: true });
  expect(out.ok).toBe(true);

  // The browser opened the Scripts page, loaded the script and ran it all.
  const textarea = page.getByTestId("scripts-input");
  await expect(textarea).toHaveValue(script);
  await expect(page.getByTestId("scripts-status")).toContainText("2 statements");
  await expect(page.getByTestId("scripts-output").locator("table thead th")).toContainText(["name"]);

  // While the user is typing in the editor, a push is refused, not applied.
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/remote/lock")), // focus takes the lock
    textarea.click(),
  ]);
  await textarea.press("End");
  await page.keyboard.type(" -- mine");
  const blocked = await mcpCall(baseURL!, "push_script", { session_id: sid, sql: "SELECT 2" });
  expect(blocked).toMatchObject({ ok: false, message: "blocked, user editing" });
  await expect(textarea).toHaveValue(script + " -- mine");

  // Disarm: the popover no longer exposes the session id...
  await page.getByTestId("agent-toggle").click();
  await page.getByTestId("remote-arm").uncheck();
  await expect(page.getByTestId("remote-session-id")).toHaveCount(0);
  // ...and a push to an unknown id is reported as not delivered.
  const lost = await mcpCall(baseURL!, "push_script", { session_id: "deadbeef", sql: "SELECT 2" });
  expect(lost.ok).toBe(false);
});

// req: user_guide/dashboard/dashboard-many-connections, user_guide/dashboard/federated, user_guide/queryview/federated-pill
test("one dashboard shows ClickHouse and Postgres side by side", async ({ page, seeds, baseURL }) => {
  await connect(page, CH, await seeds.testDb());
  const pg = await savePostgresMarks(baseURL, seeds);
  try {
    const name = `fed-${uid()}`;
    await api(`${baseURL}/api/dashboards`, {
      json: {
        name,
        html: '<b id="ch" data-qv-query="ch" data-qv-column="v"></b><b id="pg" data-qv-query="pg" data-qv-column="v"></b>',
        queries: {
          ch: { connection: "clickhouse", sql: "SELECT v FROM marks" },
          pg: { connection: pg.name, sql: "SELECT v FROM marks" },
        },
      },
    });
    await page.getByTestId("nav-dashboard").click();
    await page.getByTestId("dashboard-select").selectOption(name);
    const frame = dashboardFrame(page);
    await expect(frame.locator("#ch")).toHaveText("from-clickhouse");
    await expect(frame.locator("#pg")).toHaveText("from-postgres");

    // The pill lists both connections, answered.
    const pill = page.getByTestId("federated-pill");
    await expect(pill).toContainText("Federated · 2 connections");
    await pill.click();
    const rows = page.getByTestId("federated-pill-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: "clickhouse" })).toContainText("🟢");
    await expect(rows.filter({ hasText: pg.name })).toContainText("🟢");

    // Leaving the page shows the session's own connection again.
    await page.getByTestId("nav-explorer").click();
    await expect(page.getByTestId("federated-pill")).toHaveCount(0);
    await expect(page.getByTestId("connection-status")).toContainText(`clickhouse · ${chDb()}`);
  } finally {
    await pg.drop();
  }
});
