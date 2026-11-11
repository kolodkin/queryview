// Workspaces, YAML export/import, git sync and popovers: none needs a database.
import { readFileSync } from "node:fs";
import { api, expect, sessionId, switchWorkspace, test } from "./fixtures";

test("switcher isolates dashboards", async ({ page, baseURL }) => {
  // Uses a uniquely-named workspace and cleans it up so reruns are idempotent.
  const ws = `e2e-${crypto.randomUUID().slice(0, 6)}`;
  const dash = `ws dash ${ws}`;
  await api(`${baseURL}/api/workspaces`, { json: { name: ws } });
  await api(`${baseURL}/api/dashboards`, {
    json: { name: dash, connection: "prod", html: "<html><body>ws</body></html>", queries: {}, workspace: ws },
  });

  try {
    // Default workspace: the dashboard is absent from its list.
    await page.goto("/dashboard");
    await expect(page.getByTestId("workspace-switcher")).toContainText("default");
    const { body } = await api(`${baseURL}/api/dashboards`);
    expect(body.dashboards.map((d: { name: string }) => d.name)).not.toContain(dash);

    // Switch: the page views remount and the dashboard resolves in that workspace.
    await switchWorkspace(page, ws);
    await page.goto(`/dashboard?name=${encodeURIComponent(dash)}`);
    await expect(page.locator("body")).not.toContainText("not found");
  } finally {
    // Reset this session's workspace. Workspace deletion is best-effort (it
    // still owns the dashboard, so the API returns 409 — there is no
    // dashboard-delete endpoint yet; see docs/future.md).
    const sid = await sessionId(page);
    if (sid) await api(`${baseURL}/api/sessions/${sid}`, { method: "PATCH", json: { workspace: "default" } });
    await api(`${baseURL}/api/workspaces/${ws}`, { method: "DELETE", ok: false });
  }
});

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

// Git sync: in CI a loopback git daemon (start-git-daemon action) serves a
// remote the backend fixture points the default workspace at, so the full UI
// save-commits/restore round trip runs; on an unconfigured stack that test skips and
// the controls render disabled.
const gitConfigured = async (baseURL: string) => Boolean((await api(`${baseURL}/api/git/status`)).body.configured);

test("git controls disabled when unconfigured", async ({ page, baseURL }) => {
  test.skip(await gitConfigured(baseURL!), "git sync is configured; disabled-state not applicable");
  await page.goto("/dashboard");
  await expect(page.getByTestId("git-restore-toggle")).toBeDisabled();
  await expect(page.getByTestId("git-sync-badge")).toHaveCount(0);
});

test("saves commit and restore dashboard round trip", async ({ page, baseURL }) => {
  test.skip(!(await gitConfigured(baseURL!)), "git sync is not configured for this stack");
  // Unique per attempt, in case a retry lands on a worker whose repo keeps the first
  // attempt's commit.
  const name = `gs e2e ${crypto.randomUUID().slice(0, 6)}`;
  const save = (v: number) =>
    api(`${baseURL}/api/dashboards`, {
      json: { name, html: `<html><body>v${v}</body></html>`, queries: { q: `SELECT ${v}` } },
    });

  // Each save commits: v1, then v2. The heading's badge says so.
  await save(1);
  await save(2);
  await page.goto(`/dashboard?name=${encodeURIComponent(name)}`);
  await expect(page.getByTestId("git-sync-badge")).toBeVisible();

  // Restore v1, the older revision.
  page.on("dialog", (d) => d.accept());
  await page.getByTestId("git-restore-toggle").click();
  const rows = page.getByTestId("git-revision-row");
  await expect(rows).toHaveCount(2);
  await rows.last().getByTestId("git-revision-restore").click();
  // The picker closes on a successful restore; only then check the store.
  await expect(page.getByTestId("git-revisions")).toBeHidden();
  const { body } = await api(`${baseURL}/api/dashboards/${encodeURIComponent(name)}`);
  expect(body.html).toContain("v1");
  expect(body.queries).toEqual({ q: "SELECT 1" });
});

test("popovers close on outside click and escape", async ({ page }) => {
  // The header dropdowns close when the click (or Escape) lands outside them,
  // not only on their own trigger.
  await page.goto("/connect", { waitUntil: "networkidle" });
  const switcher = page.getByTestId("workspace-switcher");
  const option = page.getByTestId("workspace-option").first();
  // The page's empty left edge: the header popovers open on the right.
  const clickOutside = () => page.mouse.click(5, 400);

  // Workspace dropdown: a click elsewhere on the page closes it...
  await switcher.click();
  await expect(option).toBeVisible();
  await clickOutside();
  await expect(option).toHaveCount(0);

  // ...and so does Escape.
  await switcher.click();
  await expect(option).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(option).toHaveCount(0);

  // The manage panel dismisses the same way while untouched...
  await switcher.click();
  await page.getByTestId("workspace-manage").click();
  const nameInput = page.getByTestId("workspace-name-input");
  await expect(nameInput).toBeVisible();
  await clickOutside();
  await expect(nameInput).toHaveCount(0);

  // ...but once it holds unsaved input, an outside click and Escape both
  // leave it alone; its own Close dismisses it.
  await switcher.click();
  await page.getByTestId("workspace-manage").click();
  await page.getByTestId("workspace-branch-input").fill("draft");
  await clickOutside();
  await page.keyboard.press("Escape");
  await expect(nameInput).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(nameInput).toHaveCount(0);
});
