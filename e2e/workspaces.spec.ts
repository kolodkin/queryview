// Workspaces, git sync controls and popovers: none needs a database. The YAML
// and git round trips are in acceptance.spec.ts.
import { api, expect, gitConfigured, sessionId, switchWorkspace, test } from "./fixtures";

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

// Git sync: in CI a loopback git daemon (start-git-daemon action) serves a
// remote the backend fixture points the default workspace at, so the
// save/restore round trip (acceptance.spec.ts) runs; on an unconfigured stack
// that test skips and Restore renders disabled.
test("git controls disabled when unconfigured", async ({ page, baseURL }) => {
  test.skip(await gitConfigured(baseURL!), "git sync is configured; disabled-state not applicable");
  await page.goto("/dashboard");
  await expect(page.getByTestId("git-restore-toggle")).toBeDisabled();
  await expect(page.getByTestId("git-commit")).toHaveCount(0); // Save commits
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
