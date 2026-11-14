import {
  CH,
  CH_HOST,
  CH_PASSWORD,
  CH_PORT,
  CH_USER,
  DUCK,
  api,
  armRemote,
  chDb,
  connect,
  expect,
  mcpCall,
  openNewQuery,
  sessionId,
  test,
} from "./fixtures";

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

test("agent switch names the connection and toasts", async ({ page, seeds, baseURL }) => {
  // use_connection reaches an unarmed tab by heartbeat: the pill names the
  // agent's connection, a toast says the agent switched, the menu badges it.
  await seeds.testDb();
  await connect(page, CH, chDb());
  const sid = await sessionId(page);
  const name = `agent-ch-${crypto.randomUUID().slice(0, 6)}`;
  const config = { host: CH_HOST, port: Number(CH_PORT), username: CH_USER, password: CH_PASSWORD };
  expect((await mcpCall(baseURL!, "add_connection", { session_id: sid, name, type: "clickhouse", config })).ok).toBeTruthy();
  expect((await mcpCall(baseURL!, "use_connection", { session_id: sid, name, database: chDb() })).ok).toBeTruthy();

  await expect(page.getByTestId("connection-status")).toContainText(`${name} · ${chDb()}`);
  await expect(page.getByTestId("agent-toast")).toContainText(`Agent switched to ${name}`);
  await page.getByTestId("connection-status").click();
  const entry = page.locator(`[data-testid="pill-conn"][data-conn="${name}"]`);
  await expect(entry).toHaveAttribute("data-active", "true");
  await expect(entry.getByTestId("conn-agent-badge")).toHaveText("agent");
});

test("mcp open_explorer browses the table", async ({ page, seeds, baseURL }) => {
  await seeds.testDb();
  await connect(page, CH, chDb());
  await openNewQuery(page);
  const sid = await armRemote(page);

  const out = await mcpCall(baseURL!, "open_explorer", { session_id: sid, database: chDb(), table: "items" });
  expect(out.ok).toBe(true);

  // The browser left the dashboard for the Explorer, browsing the table.
  await expect(page).toHaveURL(/\/explorer\?table=items$/);
  await expect(page.getByTestId("agent-toast")).toContainText("Agent opened the Explorer");
  await expect(page.getByTestId("explorer-output")).toContainText("gamma");

  // A table the database doesn't list is refused before anything is pushed.
  const missing = await mcpCall(baseURL!, "open_explorer", { session_id: sid, database: chDb(), table: "nope" });
  expect(missing).toEqual({ ok: false, message: `no table "nope" in ${chDb()}`, database: chDb() });
});

test("mcp new_tab opens a session of the agent's own at its link", async ({ page, context, seeds, baseURL }) => {
  await seeds.testDb();
  await connect(page, CH, chDb()); // the user's own tab, untouched below
  const mine = await sessionId(page);

  const made = await mcpCall(baseURL!, "new_tab", { name: "orders" });
  expect(made).toMatchObject({ ok: true, url: `${baseURL}/?session=${made.session_id}` });
  const sid = made.session_id as string;
  expect(sid).not.toBe(mine);
  // The agent connects the tab and pushes before anyone has opened the link.
  const name = `tab-ch-${crypto.randomUUID().slice(0, 6)}`;
  const config = { host: CH_HOST, port: Number(CH_PORT), username: CH_USER, password: CH_PASSWORD };
  expect((await mcpCall(baseURL!, "add_connection", { session_id: sid, name, type: "clickhouse", config })).ok).toBeTruthy();
  expect((await mcpCall(baseURL!, "use_connection", { session_id: sid, name, database: chDb() })).ok).toBeTruthy();
  const queued = await mcpCall(baseURL!, "push_script", { session_id: sid, sql: "SELECT 42 AS answer", run: true });
  expect(queued).toMatchObject({ ok: true, message: "queued for the tab", url: made.url });

  // Opening the link shows the tab, armed, with the script run.
  const tab = await context.newPage();
  await tab.goto(made.url as string);
  await expect(tab.getByTestId("scripts-input")).toHaveValue("SELECT 42 AS answer");
  await expect(tab.getByTestId("scripts-output")).toContainText("42");
  await expect(tab).toHaveURL(/\/scripts$/); // the link's parameter is gone
  expect(await sessionId(tab)).toBe(sid);
  await expect(tab.getByTestId("session-switcher")).toContainText("Agent › orders");
  await expect(tab).toHaveTitle(/Agent › orders/);

  // A later push lands in the open tab; the user's own editor was never touched.
  const again = await mcpCall(baseURL!, "push_script", { session_id: sid, sql: "SELECT 7 AS answer" });
  expect(again).toMatchObject({ ok: true, message: "delivered" });
  await expect(tab.getByTestId("scripts-input")).toHaveValue("SELECT 7 AS answer");
  await page.getByTestId("nav-scripts").click();
  await expect(page.getByTestId("scripts-input")).toHaveValue("");
});
