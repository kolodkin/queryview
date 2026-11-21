import { type Download, type Page } from "@playwright/test";
import { dashboardFrame, expect, startViewer, test, type Dash, type Viewer } from "./fixtures";

// The viewer server (docs/server.md): display only, on its own entrypoint.

const ITEMS: Dash = {
  name: "items",
  html:
    '<qv-param name="pick"></qv-param><b id="v" data-qv-query="one" data-qv-column="name"></b>' +
    '<qv-select-view query="rows" limit="2"></qv-select-view>',
  queries: {
    one: "SELECT id, name FROM items WHERE name = {pick}",
    rows: "SELECT id, name FROM items ORDER BY id",
  },
  params: [{ name: "pick", options_sql: "SELECT name FROM items ORDER BY id" }],
};

let viewer: Viewer;
test.beforeAll(async () => {
  viewer = await startViewer([ITEMS]);
});
test.afterAll(async () => {
  await viewer?.stop();
});

const open = async (page: Page, search = "") => {
  await page.goto(`${viewer.url}/${search}`);
  await expect(page.getByTestId("viewer")).toBeVisible();
  return dashboardFrame(page);
};

test("shows a dashboard from the repo, and a param re-runs its query", async ({ page, shot }) => {
  const frame = await open(page);
  await expect(page.getByTestId("viewer-connection")).toHaveValue("local");
  await page.getByTestId("viewer-dashboard").selectOption("items");
  await expect(frame.locator("#v")).toHaveText("alpha");
  await frame.getByTestId("qv-param").selectOption("beta");
  await expect(frame.locator("#v")).toHaveText("beta");
  await expect(page).toHaveURL(/\?connection=local&name=items$/);
  await shot("viewer server");
});

test("a widget pages and sorts through the server", async ({ page }) => {
  const frame = await open(page, "?connection=local&name=items");
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("alpha");
  await frame.getByTestId("qv-next").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("gamma");
});

test("a link opens directly, the last pick reopens, and the connection can change", async ({ page }) => {
  const frame = await open(page, "?connection=other&name=items");
  await expect(page.getByTestId("viewer-connection")).toHaveValue("other");
  await expect(frame.locator("#v")).toHaveText("omega");

  // A pick is remembered in the browser: no query string reopens it.
  await page.getByTestId("viewer-connection").selectOption("local");
  await expect(dashboardFrame(page).locator("#v")).toHaveText("alpha");
  await open(page);
  await expect(page.getByTestId("viewer-connection")).toHaveValue("local");
  await expect(page.getByTestId("viewer-dashboard")).toHaveValue("items");
  await expect(dashboardFrame(page).locator("#v")).toHaveText("alpha");
});

test("there is nothing to edit with, and the app's API is absent", async ({ page }) => {
  await open(page, "?connection=local&name=items");
  for (const id of ["dashboard-save", "dashboard-edit-queries", "dashboard-new-query", "dash-sql", "connection-status"]) {
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  const sql = { query: "SELECT 1", queries: { q: "SELECT 1" }, sql: "SELECT 1" };
  for (const path of ["/api/db/query", "/api/runqueries", "/api/db/execute", "/api/dashboards"]) {
    const r = await page.request.post(`${viewer.url}${path}`, { data: sql });
    expect([404, 405], path).toContain(r.status());
  }
  const shown = await (await page.request.get(`${viewer.url}/api/dashboards/items`)).text();
  expect(shown).not.toContain("SELECT");
});

test("a push to the repo shows after the sync interval", async ({ page }) => {
  await viewer.push([{ ...ITEMS, name: "fresh" }]);
  await expect(async () => {
    await open(page);
    await expect(page.getByTestId("viewer-dashboard").locator("option", { hasText: "fresh" })).toHaveCount(1, {
      timeout: 500,
    });
  }).toPass();
});

test("a dashboard that is gone says so", async ({ page }) => {
  await open(page, "?connection=local&name=gone");
  await expect(page.getByTestId("viewer-error")).toHaveText("Dashboard “gone” not found.");
  await expect(page.getByTestId("dashboard-frame")).toHaveCount(0);
});

test("Snapshot downloads the dashboard as a static file", async ({ page }) => {
  const frame = await open(page, "?connection=local&name=items");
  await expect(frame.locator("#v")).toHaveText("alpha");
  // A widget still loading refuses the snapshot: wait for its rows.
  await expect(frame.getByTestId("qv-results").locator("tbody tr")).toHaveCount(2);
  const [download]: [Download, void] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("viewer-snapshot").click(),
  ]);
  expect(download.suggestedFilename()).toBe("items.html");
});
