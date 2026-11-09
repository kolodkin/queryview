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
  openQueryPanel,
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
});

test("mcp push to live session", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openQueryPanel(page);
  const sid = await armRemote(page);

  // Push a query the way an MCP client would (via the REST surface).
  const { body } = await api(`${baseURL}/api/remote/push`, {
    json: {
      session_id: sid,
      query: "SELECT id, name FROM items",
      limit: 10,
      order_by: [{ name: "id", dir: "DESC" }],
      fields: ["name"],
    },
  });
  expect(body.ok).toBe(true);

  // The browser filled the SQL box and auto-ran; only the pushed field shows.
  await expect(page.getByTestId("query-input")).toHaveValue("SELECT id, name FROM items");
  const output = page.getByTestId("query-output");
  await expect(output).toBeVisible();
  await expect(output.locator("table thead th")).toHaveCount(1);
  await expect(output.locator("table thead th")).toContainText("name");
  await expect(output).toContainText("gamma"); // id DESC -> gamma first

  // Disarm: the popover no longer exposes the session id...
  await page.getByTestId("agent-toggle").click();
  await page.getByTestId("remote-arm").uncheck();
  await expect(page.getByTestId("remote-session-id")).toHaveCount(0);

  // ...and a push to an unknown/inactive id is reported as not delivered.
  const r2 = await api(`${baseURL}/api/remote/push`, {
    json: { session_id: "deadbeef", query: "SELECT 1" },
    ok: false,
  });
  expect(r2.body.ok).toBe(false);
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
  await openQueryPanel(page);
  const sid = await armRemote(page);

  const out = await mcpCall(baseURL!, "open_explorer", { session_id: sid, database: chDb(), table: "items" });
  expect(out.ok).toBe(true);

  // The browser left the query panel for the Explorer, browsing the table.
  await expect(page).toHaveURL(/\/explorer\?table=items$/);
  await expect(page.getByTestId("agent-toast")).toContainText("Agent opened the Explorer");
  await expect(page.getByTestId("explorer-output")).toContainText("gamma");

  // A table the database doesn't list is refused before anything is pushed.
  const missing = await mcpCall(baseURL!, "open_explorer", { session_id: sid, database: chDb(), table: "nope" });
  expect(missing).toEqual({ ok: false, message: `no table "nope" in ${chDb()}`, database: chDb() });
});
