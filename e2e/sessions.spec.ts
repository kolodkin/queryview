// Sessions survive a refresh, are one-per-tab, and are switchable. Uses DuckDB
// throughout: it needs no server, so these run anywhere the SPA does.
import { DUCK, api, connect, expect, openQueryPanel, sessionId, test as base } from "./fixtures";

/** An earlier test's session: named, state saved, then released by its closing
 * tab, so it is the most recently active unheld named session — what a new tab
 * resumes. Listed before `page`, so it exists when `context` seeds this test's. */
const test = base.extend<{ leftBehind: string }>({
  leftBehind: async ({ baseURL }, use) => {
    const tab = `e2e-${crypto.randomUUID()}`;
    const sid = (await api(`${baseURL}/api/sessions/attach`, { json: { tab } })).body.session.id;
    await api(`${baseURL}/api/sessions/${sid}`, { method: "PATCH", json: { label: "left behind" } });
    const ui = { query: { sql: "SELECT 'left behind'" } };
    await api(`${baseURL}/api/sessions/release`, { json: { tab, session_id: sid, ui } });
    await use(sid);
    await api(`${baseURL}/api/sessions/${sid}`, { method: "DELETE", ok: false });
  },
});

test("refresh keeps the query and the connection", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openQueryPanel(page);
  await page.getByTestId("query-input").fill("SELECT 1 -- remembered");

  // No focus-out happened, so the reload's pagehide beacon is what carries it.
  await page.reload({ waitUntil: "networkidle" });

  await expect(page.getByTestId("query-input")).toHaveValue("SELECT 1 -- remembered");
  await expect(page.getByTestId("connection-status")).toContainText("duckdb");
});

test("refresh keeps the page you were on", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await page.getByTestId("nav-explorer").click();
  await expect(page).toHaveURL(/\/explorer/);
  await page.waitForTimeout(600);

  await page.reload({ waitUntil: "networkidle" });

  await expect(page).toHaveURL(/\/explorer/);
});

test("a second tab gets its own session", async ({ page, context, seeds }) => {
  // The first tab holds its session, so a new tab starts a fresh one rather
  // than showing the same state twice.
  await connect(page, DUCK, await seeds.duckdb());
  const first = await sessionId(page);

  const second = await context.newPage();
  try {
    await second.goto("/", { waitUntil: "networkidle" });
    expect(await sessionId(second)).not.toBe(first);
  } finally {
    await second.close();
  }
});

test("a tab whose session is taken greys out until it takes it back", async ({ page, seeds, baseURL }) => {
  // A backgrounded tab's claim can lapse and another tab take its session.
  // The tab must say so instead of silently moving to some other session.
  await connect(page, DUCK, await seeds.duckdb());
  const sid = await sessionId(page);
  const other = `e2e-thief-${crypto.randomUUID()}`;
  await api(`${baseURL}/api/sessions/select`, { json: { tab: other, id: sid, force: true } });
  try {
    // The next heartbeat finds it taken.
    await expect(page.getByTestId("session-taken")).toBeVisible();

    await page.getByTestId("session-take-over").click();

    await expect(page.getByTestId("session-taken")).toHaveCount(0);
    await expect(page.getByTestId("connection-status")).toContainText("duckdb");
    expect(await sessionId(page)).toBe(sid);
  } finally {
    await api(`${baseURL}/api/sessions/release`, { json: { tab: other }, ok: false });
  }
});

test("the switcher opens a new session", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await page.getByTestId("session-switcher").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();

  await page.getByTestId("session-new").click();

  // A brand-new session is disconnected, so it lands on Connect.
  await expect(page.getByTestId("connect-page")).toBeVisible();
  await expect(page.getByTestId("connection-status")).toHaveCount(0);
});

test("a renamed session keeps its name", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await page.getByTestId("session-switcher").click();
  await page.getByTestId("session-rename").click();
  await page.getByTestId("session-rename-input").fill("nightly audit");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("session-switcher")).toContainText("nightly audit");

  await page.reload({ waitUntil: "networkidle" });

  await expect(page.getByTestId("session-switcher")).toContainText("nightly audit");
});

test("a restored panel does not page a new query into nothing", async ({ page, seeds }) => {
  // The page you were on is not restored: an offset is a cursor into a result
  // set, and results are not restored either (docs/session.md).
  await connect(page, DUCK, await seeds.duckdb());
  await openQueryPanel(page);
  await page.getByTestId("query-input").fill("SELECT name FROM items ORDER BY id");
  await page.getByTestId("query-limit").fill("1");
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-output")).toContainText("alpha");
  await page.getByTestId("query-next").click();
  await expect(page.getByTestId("query-output")).toContainText("beta");

  await page.reload({ waitUntil: "networkidle" });

  // The SQL comes back; the cursor does not...
  await expect(page.getByTestId("query-input")).toHaveValue("SELECT name FROM items ORDER BY id");
  await expect(page.getByTestId("query-offset")).toHaveValue("0");
  // ...so a re-run starts at the first page rather than past the end of a
  // fresh result set.
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-output")).toContainText("alpha");
});

test("each test starts on a fresh session", async ({ leftBehind, page }) => {
  // `context` must seed a brand-new session, not resume the last one another
  // test released along with its saved panel state.
  await page.goto("/", { waitUntil: "networkidle" });
  expect(await sessionId(page)).not.toBe(leftBehind);
});

test("a switch made elsewhere names the new connection", async ({ page, seeds, baseURL }) => {
  // A session connection opened outside this tab (the agent's path) shows in
  // the pill and the pill's connection list (no badge: the user added it);
  // only the agent's use_connection toasts.
  const seed = await seeds.duckdb();
  await connect(page, DUCK, seed);
  const r = await api(`${baseURL}/api/db/connect`, {
    json: { type: "duckdb", path: seed, name: "side-duck", session: true },
    headers: { "X-QV-Session": await sessionId(page) },
  });
  expect(r.body.ok).toBe(true);

  const status = page.getByTestId("connection-status");
  await expect(status).toContainText("side-duck");
  await expect(page.getByTestId("agent-toast")).toHaveCount(0);
  await status.click();
  const entry = page.locator('[data-testid="pill-conn"][data-conn="side-duck"]');
  await expect(entry).toHaveAttribute("data-active", "true");
  await expect(entry.getByTestId("conn-agent-badge")).toHaveCount(0);
  await expect(page.locator('[data-testid="pill-conn"][data-conn="duckdb"]')).toHaveAttribute("data-active", "false");
});
