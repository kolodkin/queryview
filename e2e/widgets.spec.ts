// Dashboard widgets: the <qv-*> tags an agent drops into dashboard HTML. They
// run through the same query path as Studio, so once on DuckDB (no service).
import { DUCK, api, connect, expect, test } from "./fixtures";
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
