// Workspace autosave: no Save buttons, and a named query persists after each
// successful run (never a failed one). Agent-push persistence is covered in the
// backend tests (test_dashboards.py). Uses a uniquely-named workspace per run.
import type { Page } from "@playwright/test";
import { DUCK, api, armRemote, connect, expect, mcpCall, openQueryPanel, switchWorkspace, test } from "./fixtures";

const newWorkspace = () => `e2e-auto-${crypto.randomUUID().slice(0, 6)}`;

async function storedSql(baseURL: string, ws: string, name: string): Promise<string | undefined> {
  const q = new URLSearchParams({ type: "duckdb", workspace: ws });
  const { body } = await api(`${baseURL}/api/predefined-queries?${q}`);
  return body.queries.find((x: { query_name: string }) => x.query_name === name)?.query;
}

async function setAutosave(page: Page, on: boolean): Promise<void> {
  await page.getByTestId("workspace-switcher").click();
  await page.getByTestId("workspace-manage").click();
  await page.getByTestId("workspace-autosave-input").setChecked(on);
  await page.getByTestId("workspace-save").click();
}

test("autosave saves successful runs and hides save", async ({ page, seeds, baseURL, shot }) => {
  const ws = newWorkspace();
  await api(`${baseURL}/api/workspaces`, { json: { name: ws, autosave: true } });

  await connect(page, DUCK, await seeds.duckdb());
  await switchWorkspace(page, ws);

  await openQueryPanel(page);
  await expect(page.getByTestId("query-save")).toHaveCount(0);

  page.once("dialog", (d) => d.accept("auto q"));
  await page.getByTestId("query-predefined-select").selectOption("::new::");
  await page.getByTestId("query-input").fill("SELECT id, name FROM items ORDER BY id");
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-output")).toBeVisible();
  // The save lands after the run renders.
  await expect.poll(() => storedSql(baseURL!, ws, "auto q")).toBe("SELECT id, name FROM items ORDER BY id");
  await shot("autosave: saved after a successful run");

  // A failing run leaves the stored SQL alone.
  await page.getByTestId("query-input").fill("SELEC nope");
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-error")).toBeVisible();
  expect(await storedSql(baseURL!, ws, "auto q")).toBe("SELECT id, name FROM items ORDER BY id");

  // An unnamed agent push runs but never overwrites the selected query; a
  // named one saves under its name.
  const sessionId = await armRemote(page);
  const push = { session_id: sessionId, query: "SELECT name FROM items" };
  await api(`${baseURL}/api/remote/push`, { json: push });
  await expect(page.getByTestId("query-input")).toHaveValue("SELECT name FROM items");
  await expect(page.getByTestId("query-output")).toBeVisible();
  await api(`${baseURL}/api/remote/push`, { json: { ...push, name: "pushed q" } });
  await expect.poll(() => storedSql(baseURL!, ws, "pushed q")).toBe("SELECT name FROM items");
  expect(await storedSql(baseURL!, ws, "auto q")).toBe("SELECT id, name FROM items ORDER BY id");

  await page.getByTestId("nav-dashboard").click();
  await expect(page.getByTestId("dashboard-view")).toBeVisible();
  await expect(page.getByTestId("dashboard-save")).toHaveCount(0);

  // Turning it off in Manage workspaces brings Save back without a reload.
  await page.getByTestId("workspace-switcher").click();
  await page.getByTestId("workspace-manage").click();
  const autosave = page.getByTestId("workspace-autosave-input");
  await expect(autosave).toBeChecked();
  await autosave.uncheck();
  await page.getByTestId("workspace-save").click();
  await expect(page.getByTestId("dashboard-save")).toBeVisible();
});

test("turning autosave on saves open drafts", async ({ page, seeds, baseURL }) => {
  // With autosave off nothing persists until Save; turning it on saves the
  // open view's unsaved work before its Save button disappears.
  const ws = newWorkspace();
  await api(`${baseURL}/api/workspaces`, { json: { name: ws } });

  await connect(page, DUCK, await seeds.duckdb());
  await switchWorkspace(page, ws);

  // Studio: a named, successful run isn't saved until autosave goes on.
  await openQueryPanel(page);
  page.once("dialog", (d) => d.accept("draft q"));
  await page.getByTestId("query-predefined-select").selectOption("::new::");
  await page.getByTestId("query-input").fill("SELECT id FROM items");
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-output")).toBeVisible();
  expect(await storedSql(baseURL!, ws, "draft q")).toBeUndefined();
  await setAutosave(page, true);
  await expect(page.getByTestId("query-save")).toHaveCount(0);
  await expect.poll(() => storedSql(baseURL!, ws, "draft q")).toBe("SELECT id FROM items");

  // Dashboards: an agent draft arrives unnamed, so autosave has nothing to
  // save it under: Save stays, and the user names it.
  await api(`${baseURL}/api/workspaces/${ws}`, { method: "PATCH", json: { autosave: false } });
  await page.reload();
  const sessionId = await armRemote(page);
  // Through the real MCP endpoint: there's no REST route that drafts without persisting.
  const args = { session_id: sessionId, html: "<p>draft</p>", queries: {} };
  expect((await mcpCall(baseURL!, "push_dashboard", { ...args, name: "agent dash" })).ok).toBeFalsy();
  expect((await mcpCall(baseURL!, "push_dashboard", args)).ok).toBeTruthy();
  await expect(page.getByTestId("dashboard-save")).toBeEnabled();

  const storedDashboards = async (): Promise<string[]> =>
    (await api(`${baseURL}/api/dashboards?workspace=${ws}`)).body.dashboards.map((d: { name: string }) => d.name);

  await setAutosave(page, true);
  expect(await storedDashboards()).toEqual([]);
  page.once("dialog", (d) => d.accept("draft dash"));
  await page.getByTestId("dashboard-save").click();
  await expect.poll(storedDashboards).toContain("draft dash");
  await expect(page.getByTestId("dashboard-select")).toHaveValue("draft dash");
  await expect(page.getByTestId("dashboard-save")).toHaveCount(0);
});
