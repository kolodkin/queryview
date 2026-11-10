// Dashboards run their queries through the same path as Studio, which
// drivers.spec.ts covers per driver, so these run once on DuckDB (no service).
import { DUCK, api, armRemote, connect, expect, test } from "./fixtures";

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
