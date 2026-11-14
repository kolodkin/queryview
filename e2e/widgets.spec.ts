// Dashboard widgets: the <qv-*> tags an agent drops into dashboard HTML. They
// run through the same query path as Studio, so once on DuckDB (no service).
import { DUCK, api, armRemote, connect, expect, mcpCall, test } from "./fixtures";
import type { Page } from "@playwright/test";

type Dash = { name: string; html: string; queries: Record<string, string>; params?: unknown[] };

// Save a dashboard through the REST mirror and open it; returns its frame.
async function openDashboard(page: Page, baseURL: string | undefined, dash: Dash) {
  await api(`${baseURL}/api/dashboards`, { json: dash });
  await page.getByTestId("nav-dashboard").click();
  await page.getByTestId("dashboard-select").selectOption(dash.name);
  return page.frameLocator('[data-testid="dashboard-frame"]');
}

test("qv-param reruns the dashboard", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "param-widget",
    html:
      '<qv-param name="pick"></qv-param><div id="out"></div><script>' +
      "const show = () => { document.getElementById('out').textContent = window.queries.q.name.join(','); };" +
      "show(); window.onQueryResults = show;</script>",
    queries: { q: "SELECT name FROM items WHERE name = {pick}" },
    params: [{ name: "pick", options_sql: "SELECT name FROM items ORDER BY id" }],
  });
  await expect(frame.locator("#out")).toHaveText("alpha");
  await frame.getByTestId("qv-param").selectOption("beta");
  await expect(frame.locator("#out")).toHaveText("beta");
});

const VIEW = '<qv-select-view query="q" limit="2" order-by="id"></qv-select-view>';
const ITEMS = { q: "SELECT id, name FROM items" };

test("qv-select-view pages a query", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, { name: "paging", html: VIEW, queries: ITEMS });
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("alpha");
  await expect(frame.getByTestId("qv-prev")).toBeDisabled();
  await frame.getByTestId("qv-next").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("gamma");
  await frame.getByTestId("qv-prev").click();
  await expect(rows.first()).toContainText("alpha");
});

test("a cell template designs a column", async ({ page, seeds, baseURL, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "templated",
    html:
      '<qv-select-view query="q" order-by="id">' +
      '<template column="name"><a href="https://example.internal/i/{row.id}" target="_blank">{cell}</a></template>' +
      "</qv-select-view>",
    queries: ITEMS,
  });
  const link = frame.getByTestId("cell-name").first().locator("a");
  await expect(link).toHaveText("alpha");
  await expect(link).toHaveAttribute("href", "https://example.internal/i/1");
  await shot("select view with a cell template");
});

test("a widget query error stays in the widget", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "typo",
    html: VIEW,
    queries: { q: "SELECT * FROM no_such_table" },
  });
  await expect(frame.getByTestId("qv-error")).toContainText("no_such_table");
  await expect(page.getByTestId("dashboard-error")).toHaveCount(0);
});

test("an unknown query name runs nothing", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "unknown",
    html: '<qv-select-view query="missing"></qv-select-view>',
    queries: ITEMS,
  });
  await expect(frame.getByTestId("qv-error")).toHaveText("Unknown query “missing”");
});

test("the fields picker stays open on an inside click", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, { name: "fields", html: VIEW, queries: ITEMS });
  await expect(frame.getByTestId("qv-results").locator("th")).toHaveCount(2);
  await frame.getByTestId("qv-fields").click();
  await frame.getByTestId("fields-menu").click();
  const toggle = frame.locator('[data-testid="field-toggle"][data-col="id"]');
  await toggle.click();
  await expect(toggle).toBeVisible();
  await expect(frame.getByTestId("qv-results").locator("th")).toHaveCount(1);
});

test("a widget query is not in window.queries", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "owned",
    html:
      VIEW +
      '<div id="keys"></div><script>' +
      "document.getElementById('keys').textContent = Object.keys(window.queries).join(',');</script>",
    queries: { ...ITEMS, other: "SELECT 1 AS one" },
  });
  await expect(frame.locator("#keys")).toHaveText("other");
  await expect(frame.getByTestId("qv-results").locator("tbody tr")).toHaveCount(2);
});

test("New query runs ad-hoc SQL and saves as a dashboard", async ({ page, seeds, shot }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await page.getByTestId("nav-dashboard").click();
  await page.getByTestId("dashboard-new-query").click();
  const frame = page.frameLocator('[data-testid="dashboard-frame"]');
  await expect(frame.getByTestId("qv-error")).toHaveText("Enter a query.");

  await page.getByTestId("dash-sql").fill("SELECT name FROM items ORDER BY id");
  await page.getByTestId("dash-sql-execute").click();
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await shot("new query draft");

  // Saving a draft asks for its name; the saved dashboard carries the SQL.
  page.once("dialog", (d) => d.accept("scratch"));
  await page.getByTestId("dashboard-save").click();
  await expect(page.getByTestId("dashboard-select")).toHaveValue("scratch");
  await page.reload();
  await expect(rows).toHaveCount(3);
});

test("Execute keeps the page state", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "stateful",
    html: '<input id="keep">' + VIEW,
    queries: ITEMS,
  });
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await frame.locator("#keep").fill("x");

  await page.getByTestId("dashboard-edit-queries").click();
  await expect(page.getByTestId("dash-sql")).toHaveValue(ITEMS.q);
  await page.getByTestId("dash-sql").fill("SELECT id, name FROM items WHERE id = 3");
  await page.getByTestId("dash-sql-execute").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("gamma");
  await expect(frame.locator("#keep")).toHaveValue("x");
});

test("an agent push is blocked while the SQL panel has focus", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const sid = await armRemote(page);
  await openDashboard(page, baseURL, { name: "locked", html: VIEW, queries: ITEMS });
  await page.getByTestId("dashboard-edit-queries").click();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/remote/lock")), // focus takes the lock
    page.getByTestId("dash-sql").click(),
  ]);
  const out = await mcpCall(baseURL!, "push_dashboard", {
    session_id: sid,
    html: "<p>agent</p>",
    queries: { q: "SELECT 1" },
  });
  expect(out).toMatchObject({ pushed: false, message: "blocked, user editing" });
  await expect(page.getByTestId("dash-sql")).toHaveValue(ITEMS.q);
});

test("Execute reports a failing chart query", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "chart",
    html: '<div id="out"></div><script>document.getElementById("out").textContent = window.queries.q.name[0];</script>',
    queries: { q: "SELECT name FROM items ORDER BY id" },
  });
  await expect(frame.locator("#out")).toHaveText("alpha");
  await page.getByTestId("dashboard-edit-queries").click();
  await page.getByTestId("dash-sql").fill("SELECT * FROM no_such_table");
  await page.getByTestId("dash-sql-execute").click();
  await expect(page.getByTestId("dashboard-error")).toContainText("no_such_table");
  await expect(frame.locator("#out")).toHaveText("alpha"); // the page stays up
});

test("a query named like an object builtin is unknown", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "builtin",
    html: '<qv-select-view query="constructor"></qv-select-view>',
    queries: ITEMS,
  });
  await expect(frame.getByTestId("qv-error")).toHaveText("Unknown query “constructor”");
});

test("limit and offset apply on Enter", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, { name: "limits", html: VIEW, queries: ITEMS });
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  const limit = frame.getByTestId("qv-limit");
  await limit.fill(""); // clearing must not snap to 1 and prefix what is typed next
  await limit.pressSequentially("1.5");
  await limit.press("Enter");
  await expect(rows).toHaveCount(1);
  await expect(limit).toHaveValue("1");
});

test("a slow page does not overwrite a later one", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, { name: "slow", html: VIEW, queries: ITEMS });
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows.first()).toContainText("alpha");
  // Hold back the offset-2 page until after the offset-0 page has landed.
  await page.route("**/api/db/query", async (route) => {
    if (route.request().postDataJSON().offset === 2) await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  const offset = frame.getByTestId("qv-offset");
  await offset.fill("2");
  await offset.press("Enter");
  await offset.fill("0");
  await offset.press("Enter");
  await page.waitForTimeout(2500); // past the held-back reply
  await expect(rows.first()).toContainText("alpha");
  await expect(rows).toHaveCount(2);
});

test("a widget pages the executed SQL, not a half-typed edit", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, { name: "draft-sql", html: VIEW, queries: ITEMS });
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await page.getByTestId("dashboard-edit-queries").click();
  await page.getByTestId("dash-sql").fill("SELECT id, name FROM items WHERE id = 1"); // not executed
  await frame.getByTestId("qv-next").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("gamma");
});
