import { type Download, type Page } from "@playwright/test";
import { dashboardFrame, expect, holdRoute, startViewer, test, type Dash, type Viewer } from "./fixtures";

// The viewer server (docs/user_guide/viewer_server.md): display only, on its own entrypoint.

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

// req: user_guide/viewer_server/same-rendering
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

// req: user_guide/viewer_server/same-rendering
test("a widget pages through the server", async ({ page }) => {
  const frame = await open(page, "?connection=local&name=items");
  const rows = frame.getByTestId("qv-results").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("alpha");
  await frame.getByTestId("qv-next").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("gamma");
});

// req: user_guide/viewer_server/shareable
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

// req: user_guide/viewer_server/display-only
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

// req: user_guide/viewer_server/sync
test("a push to the repo shows after the sync interval", async ({ page }) => {
  await viewer.push([{ ...ITEMS, name: "fresh" }]);
  await expect(async () => {
    await open(page);
    await expect(page.getByTestId("viewer-dashboard").locator("option", { hasText: "fresh" })).toHaveCount(1, {
      timeout: 500,
    });
  }).toPass();
});

test("leaving a dashboard while it loads clears the loading line", async ({ page }) => {
  await open(page);
  const release = await holdRoute(page, "**/api/run");
  await page.getByTestId("viewer-dashboard").selectOption("items");
  await expect(page.getByTestId("viewer-loading")).toBeVisible();
  await page.getByTestId("viewer-dashboard").selectOption("");
  await expect(page.getByTestId("viewer-loading")).toHaveCount(0);
  release();
});

test("a dashboard that is gone says so", async ({ page }) => {
  await open(page, "?connection=local&name=gone");
  await expect(page.getByTestId("viewer-error")).toHaveText("Dashboard “gone” not found.");
  await expect(page.getByTestId("dashboard-frame")).toHaveCount(0);
});

test("a dashboard deleted while open says so on the next param change", async ({ page }) => {
  const listed = async (status: number) =>
    expect(async () => {
      expect((await page.request.get(`${viewer.url}/api/dashboards/doomed`)).status()).toBe(status);
    }).toPass();
  await viewer.push([{ ...ITEMS, name: "doomed" }]);
  await listed(200);
  const frame = await open(page, "?connection=local&name=doomed");
  await expect(frame.locator("#v")).toHaveText("alpha");

  await viewer.push([], ["doomed"]);
  await listed(404);
  await frame.getByTestId("qv-param").selectOption("beta");
  await expect(page.getByTestId("viewer-error")).toHaveText("Dashboard “doomed” not found.");
});

// req: user_guide/viewer_server/same-rendering
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

// req: user_guide/viewer_server/federated
test("a federated dashboard runs on the configured connections it names", async ({ page }) => {
  const v = await startViewer([
    {
      name: "pair",
      html: '<b id="a" data-qv-query="a" data-qv-column="name"></b><b id="b" data-qv-query="b" data-qv-column="name"></b>',
      queries: {
        a: { connection: "local", sql: "SELECT name FROM items WHERE id = 1" },
        b: { connection: "other", sql: "SELECT name FROM items" },
      },
    },
  ]);
  try {
    await page.goto(`${v.url}/?name=pair`);
    const frame = dashboardFrame(page);
    await expect(frame.locator("#a")).toHaveText("alpha");
    await expect(frame.locator("#b")).toHaveText("omega");
    await expect(page.getByTestId("viewer-connection")).toHaveCount(0);
    await page.getByTestId("federated-pill").click();
    const rows = page.getByTestId("federated-pill-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: "local" })).toContainText("🟢");
    await expect(rows.filter({ hasText: "other" })).toContainText("🟢");
    await expect(page.getByTestId("federated-unlock")).toHaveCount(0);
  } finally {
    await v.stop();
  }
});
