// Dashboards run their queries through the path drivers.spec.ts covers per
// driver, so these run once on DuckDB (no service).
import { readFileSync } from "node:fs";

import { DUCK, api, armRemote, closeQueries, connect, dashboardFrame, expect, openDashboard, test } from "./fixtures";

// Reads window.queries and writes a value into the DOM, so the test can
// assert the injected results reached the agent HTML. Styled as large,
// centered text for the screenshots; #out's text stays exactly the names.
const DASHBOARD_HTML =
  "<style>" +
  "html,body{height:100%;margin:0}" +
  "body{display:flex;align-items:center;justify-content:center;" +
  "font-family:system-ui,-apple-system,sans-serif}" +
  "#out{font-size:72px;font-weight:800;color:#4338ca;letter-spacing:-0.02em}" +
  "</style>" +
  "<div id='out'></div>" +
  "<script>" +
  "const items = window.queries && window.queries.items;" +
  "document.getElementById('out').textContent = items ? items.name.join(',') : 'NO DATA';" +
  "</script>";

test("dashboard push and reopen", async ({ page, seeds, baseURL, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await shot("connected");

  const sessionId = await armRemote(page);
  await shot("remote control armed");

  // Push a dashboard the way the MCP tool would (via the REST mirror).
  const { body } = await api(`${baseURL}/api/dashboards`, {
    json: {
      session_id: sessionId,
      name: "sales",
      html: DASHBOARD_HTML,
      queries: { items: "SELECT name FROM items ORDER BY id" },
    },
  });
  expect(body.persisted).toBe(true);
  expect(body.pushed).toBe(true);

  // The browser navigated to the dashboard and the iframe rendered the values
  // injected as window.queries (column-oriented: items.name is the column).
  await expect(page).toHaveURL(/\/dashboard\?name=sales/);
  await expect(page.getByTestId("dashboard-view")).toBeVisible();
  const frame = page.frameLocator('[data-testid="dashboard-frame"]');
  await expect(frame.locator("#out")).toHaveText("alpha,beta,gamma");
  await shot("pushed dashboard rendered");

  // Reopen from the store (no live push): navigate directly to the deep link.
  await page.goto("/dashboard?name=sales", { waitUntil: "networkidle" });
  await expect(page.getByTestId("dashboard-view")).toBeVisible();
  await expect(frame.locator("#out")).toHaveText("alpha,beta,gamma");

  // The dropdown lists the saved dashboard.
  await expect(page.getByTestId("dashboard-select")).toContainText("sales");
  await shot("reopened from store");
});

test("dashboard runqueries error shows banner", async ({ page, seeds, baseURL, shot }) => {
  // A dashboard whose query is invalid opens on a fail-fast error banner
  // instead of rendering the iframe.
  await connect(page, DUCK, await seeds.duckdb());
  await api(`${baseURL}/api/dashboards`, {
    json: { name: "broken", html: DASHBOARD_HTML, queries: { items: "SELECT name FROM no_such_table" } },
  });

  await page.goto("/dashboard?name=broken", { waitUntil: "networkidle" });
  await expect(page.getByTestId("dashboard-error")).toBeVisible();
  await expect(page.getByTestId("dashboard-error")).toContainText("items");
  await expect(page.getByTestId("dashboard-frame")).toHaveCount(0);
  await shot("fail-fast error banner");
});

test("a dashboard runs on the viewing sessions connection", async ({ page, seeds, baseURL }) => {
  // A saved dashboard names no connection: a disconnected session is told to
  // connect rather than failing on some connection the dashboard remembers.
  await connect(page, DUCK, await seeds.duckdb());
  await api(`${baseURL}/api/dashboards`, {
    json: { name: "portable", html: DASHBOARD_HTML, queries: { items: "SELECT name FROM items ORDER BY id" } },
  });

  await page.getByTestId("session-switcher").click();
  await page.getByTestId("session-new").click();
  // The switch lands on the new session's page (disconnected: Connect); wait
  // for it, or it would navigate away from a dashboard opened too early.
  await expect(page.getByTestId("connect-page")).toBeVisible();
  // Navigate inside the app: a reload would re-run the fixture's init script
  // and put the tab back on the original (connected) session.
  await page.getByTestId("nav-dashboard").click();
  await page.getByTestId("dashboard-select").selectOption("portable");

  await expect(page.getByTestId("dashboard-error")).toContainText("Connect to a database");
});

// Draws its own selector from window.params and re-runs via setParams; the
// results come back through onQueryResults without reloading the frame.
const PARAMS_HTML =
  "<button id='go' onclick=\"window.setParams({n: 'beta'})\">beta</button>" +
  "<div id='out'></div><div id='pick'></div>" +
  "<script>" +
  "function show(q){document.getElementById('out').textContent = q.items ? q.items.name.join(',') : 'NO DATA';}" +
  "show(window.queries);" +
  "document.getElementById('pick').textContent = window.params[0].options.join('|');" +
  "window.onQueryResults = function(q){show(q);};" +
  "</script>";

test("dashboard params resolve and rerun through setParams", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await api(`${baseURL}/api/dashboards`, {
    json: {
      name: "picker",
      html: PARAMS_HTML,
      queries: { items: "SELECT name FROM items WHERE name = {n}" },
      params: [{ name: "n", options_sql: "SELECT name FROM items ORDER BY id" }],
    },
  });

  await page.getByTestId("nav-dashboard").click();
  await page.getByTestId("dashboard-select").selectOption("picker");
  const frame = page.frameLocator('[data-testid="dashboard-frame"]');
  // options_sql ran on the session; the first option is the default.
  await expect(frame.locator("#pick")).toHaveText("alpha|beta|gamma");
  await expect(frame.locator("#out")).toHaveText("alpha");

  await frame.locator("#go").click(); // the page calls setParams({n: 'beta'})
  await expect(frame.locator("#out")).toHaveText("beta");
});

test("rename and delete a saved dashboard", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const tag = crypto.randomUUID().slice(0, 6);
  const [name, renamed] = [`ren ${tag}`, `ren ${tag} 2026`];
  await openDashboard(page, baseURL, { name, html: DASHBOARD_HTML, queries: { items: "SELECT name FROM items ORDER BY id" } });
  await expect(dashboardFrame(page).locator("#out")).toHaveText("alpha,beta,gamma");

  // An unsaved SQL-panel edit survives the rename.
  await page.getByTestId("dashboard-edit-queries").click();
  await page.getByTestId("dash-sql").fill("SELECT name FROM items WHERE id = 1");
  await closeQueries(page);
  page.once("dialog", (d) => d.accept(renamed));
  await page.getByTestId("dashboard-rename").click();
  const options = page.getByTestId("dashboard-select").locator("option");
  await expect.poll(() => new URL(page.url()).searchParams.get("name")).toBe(renamed);
  await expect.poll(() => options.allTextContents()).toContain(renamed);
  expect(await options.allTextContents()).not.toContain(name);
  await page.getByTestId("dashboard-edit-queries").click();
  await expect(page.getByTestId("dash-sql")).toHaveValue("SELECT name FROM items WHERE id = 1");
  expect((await api(`${baseURL}/api/dashboards/${encodeURIComponent(name)}`, { ok: false })).status).toBe(404);

  // Reloading opens the renamed dashboard from the store.
  await page.goto(`/dashboard?name=${encodeURIComponent(renamed)}`);
  await expect(dashboardFrame(page).locator("#out")).toHaveText("alpha,beta,gamma");

  page.once("dialog", (d) => d.accept());
  await page.getByTestId("dashboard-delete").click();
  await expect(page.getByTestId("dashboard-empty")).toBeVisible();
  expect(await options.allTextContents()).not.toContain(renamed);
  expect((await api(`${baseURL}/api/dashboards/${encodeURIComponent(renamed)}`, { ok: false })).status).toBe(404);
});

test("Snapshot downloads the dashboard as a static file", async ({ page, seeds, baseURL, browser }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "snap",
    html:
      '<qv-param name="pick"></qv-param><b id="v" data-qv-query="q" data-qv-column="name"></b>' +
      '<canvas id="c" width="40" height="20"></canvas>' +
      "<script>const x = document.getElementById('c').getContext('2d'); x.fillStyle = 'red'; x.fillRect(0, 0, 40, 20);</script>" +
      '<qv-select-view query="rows" limit="200" order-by="n desc" fields="n,p"></qv-select-view>',
    queries: { rows: "SELECT range AS n, range * 2 AS m, {pick} AS p FROM range(200)", q: "SELECT name FROM items WHERE name = {pick}" },
    params: [{ name: "pick", options_sql: "SELECT name FROM items ORDER BY id" }],
  });
  await expect(frame.getByTestId("qv-results").locator("tbody tr")).toHaveCount(200);
  await frame.getByTestId("qv-param").selectOption("beta");
  await expect(frame.locator("#v")).toHaveText("beta"); // the re-run landed
  // So did the widget's own: a snapshot taken while it is still querying is refused.
  await expect(frame.getByTestId("qv-results").locator("tbody tr").first()).toContainText("beta");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("dashboard-snapshot").click()]);
  expect(download.suggestedFilename()).toBe("snap.html");
  const path = test.info().outputPath("snap.html");
  await download.saveAs(path);

  // The live page is as it was: its canvas back in place, the widget still interactive.
  await expect(frame.locator("canvas#c")).toHaveCount(1);
  await expect(frame.getByTestId("qv-limit")).toBeVisible();
  await expect(frame.getByTestId("qv-caption")).toBeHidden();
  await expect(frame.getByTestId("qv-param")).toHaveValue("beta");

  // The file, in a browser that runs no JavaScript.
  const text = readFileSync(path, "utf-8");
  expect(text).not.toContain("<script");
  expect(text).not.toContain("window.queries");
  const context = await browser.newContext({ javaScriptEnabled: false });
  const still = await context.newPage();
  await still.goto(`file://${path}`);
  await expect(still.getByTestId("qv-results").locator("tbody tr")).toHaveCount(200);
  await expect(still.getByTestId("qv-limit")).toBeHidden();
  // In place of the controls, what they were set to.
  await expect(still.getByTestId("qv-caption")).toHaveText("200 rows · limit 200 · ordered by n desc");
  await expect(still.locator("img#c")).toBeVisible();
  await expect(still.locator("canvas")).toHaveCount(0);
  // A dropdown is its chosen value, not a list to pick from.
  await expect(still.getByTestId("qv-param")).toHaveText("beta");
  await expect(still.locator("select")).toHaveCount(0);
  // Every row laid out: no height cap, no scroll box.
  expect((await still.getByTestId("qv-results").boundingBox())!.height).toBeGreaterThan(3000);
  await context.close();
});

test("Snapshot is refused while a widget is loading", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  let release = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route("**/api/db/query", async (route) => {
    await held;
    await route.continue();
  });
  const frame = await openDashboard(page, baseURL, {
    name: "loading",
    html: '<qv-select-view query="rows"></qv-select-view>',
    queries: { rows: "SELECT name FROM items ORDER BY id" },
  });
  await expect(frame.getByTestId("qv-select-view")).toBeVisible();
  await page.getByTestId("dashboard-snapshot").click();
  await expect(page.getByTestId("dashboard-error")).toContainText("The dashboard is still loading");

  release();
  await expect(frame.getByTestId("qv-results").locator("tbody tr")).toHaveCount(3);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("dashboard-snapshot").click()]);
  expect(download.suggestedFilename()).toBe("loading.html");
  await expect(page.getByTestId("dashboard-error")).toHaveCount(0); // the refusal is cleared
});

test("Snapshot is not held up by a qv- tag the bundle does not know", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "unknown-tag",
    html: '<qv-nope></qv-nope><b id="v" data-qv-query="q"></b>',
    queries: { q: "SELECT name FROM items ORDER BY id" },
  });
  await expect(frame.locator("#v")).toHaveText("alpha");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("dashboard-snapshot").click()]);
  expect(download.suggestedFilename()).toBe("unknown-tag.html");
});

test("the dashboard's name can be copied", async ({ page, context, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await expect(page.getByTestId("dashboard-copy")).toHaveCount(0); // nothing open: nothing to copy
  await openDashboard(page, baseURL, { name: "copy me", html: "<p>hi</p>", queries: {} });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByTestId("dashboard-copy").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("copy me");
});
