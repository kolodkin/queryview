// Saved cards edit and delete, and passphrase-locked connections: the tab that
// knows the passphrase keeps working, the agent is refused on every path, and a
// lock survives a reload but asks again in a fresh tab
// (docs/connect.md#locked-connections).
import type { Page } from "@playwright/test";
import { DUCK, api, armRemote, connCard as card, connect, expect, mcpCall, openConnect, openQueryPanel, test } from "./fixtures";

const PASSPHRASE = "open sesame";

async function answerPrompt(page: Page, passphrase: string): Promise<void> {
  await expect(page.getByTestId("passphrase-prompt")).toBeVisible();
  await page.getByTestId("passphrase-input").fill(passphrase);
  await page.getByTestId("passphrase-submit").click();
}

test("edit reopens the form on the saved values", async ({ page, seeds }) => {
  const seed = await seeds.duckdb();
  await connect(page, DUCK, seed);
  await openConnect(page);
  await card(page, DUCK.id).getByTestId("conn-edit").click();
  await expect(page.getByTestId("duckdb-form")).toContainText("Edit DuckDB connection");
  await expect(page.getByTestId("duck-name")).toHaveValue(DUCK.id);
  await expect(page.getByTestId("duck-name")).toHaveAttribute("readonly", "");
  await expect(page.getByTestId("duck-path")).toHaveValue(seed);
  await expect(page.getByTestId("conn-session-only")).toHaveCount(0);

  // Re-saving under the same name replaces the config: the explorer now
  // lists the other file's extra tables.
  await page.getByTestId("duck-path").fill(await seeds.duckdbLongNames());
  await page.getByTestId("duck-connect").click();
  await page.waitForURL("**/explorer");
  await expect(page.getByTestId("explorer-table")).toHaveCount(3);
  await openConnect(page);
  await expect(card(page, DUCK.id)).toHaveCount(1);
});

test("delete drops the card and disconnects", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openConnect(page);
  page.once("dialog", (d) => d.dismiss());
  await card(page, DUCK.id).getByTestId("conn-delete").click();
  await expect(card(page, DUCK.id)).toHaveCount(1);
  page.once("dialog", (d) => d.accept());
  await card(page, DUCK.id).getByTestId("conn-delete").click();
  await expect(card(page, DUCK.id)).toHaveCount(0);
  await expect(page.getByTestId("connection-status")).toHaveCount(0);
});

test("a locked connection edits and deletes with its passphrase", async ({ page, seeds }) => {
  await connect(page, DUCK, await seeds.duckdb());
  await openConnect(page);
  const c = card(page, DUCK.id);
  await c.getByTestId("conn-lock").click();
  await answerPrompt(page, PASSPHRASE);
  await expect(c).toHaveAttribute("data-locked", "true");

  // Off the connection and without its token, the tab is asked before the
  // form opens.
  await page.getByTestId("connection-status").click();
  await page.getByTestId("disconnect").click();
  await expect(page.getByTestId("connection-status")).toHaveCount(0);
  await page.evaluate(() => sessionStorage.removeItem("qv_token"));
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByTestId("connect-page")).toBeVisible();
  await c.getByTestId("conn-edit").click();
  await answerPrompt(page, "wrong");
  await expect(page.getByTestId("passphrase-error")).toContainText("wrong passphrase");
  await answerPrompt(page, PASSPHRASE);
  await expect(page.getByTestId("duckdb-form")).toContainText("Edit DuckDB connection");
  await page.getByTestId("form-back").click();

  // Deleting takes the passphrase in place of the confirm.
  await c.getByTestId("conn-delete").click();
  await expect(page.getByTestId("passphrase-prompt")).toContainText(`Delete ${DUCK.id}?`);
  await answerPrompt(page, PASSPHRASE);
  await expect(c).toHaveCount(0);
});

test("locked connection keeps the agent out", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const sessionId = await armRemote(page);
  const mcp = (tool: string, args: Record<string, unknown>) => mcpCall(baseURL!, tool, { session_id: sessionId, ...args });
  expect((await mcp("run_sql", { sql: "SELECT count(*) FROM items" })).ok).toBeTruthy();

  // Lock the connection from its card. The locking tab stays unlocked.
  await openConnect(page);
  let c = page.getByTestId("conn-card").filter({ hasText: DUCK.id }).first();
  await c.getByTestId("conn-lock").click();
  await answerPrompt(page, PASSPHRASE);
  await expect(c).toHaveAttribute("data-locked", "true");

  // The agent: MCP tools and the REST surface alike, with the session id only.
  expect(await mcp("run_sql", { sql: "SELECT 1" })).toEqual({ ok: false, message: "connection is locked" });
  expect(await mcp("push_studio", { query: "SELECT 1" })).toMatchObject({ ok: false, message: "connection is locked" });
  expect(await mcp("session_info", {})).toMatchObject({ locked: true, tables: [] });
  const r = await api(`${baseURL}/api/db/query`, {
    json: { query: "SELECT 1" },
    headers: { "X-QV-Session": sessionId },
    ok: false,
  });
  expect(r.status).toBe(403);
  expect(r.body.message).toBe("connection is locked");

  // This tab holds the token: reopening asks nothing, querying works, and a
  // reload keeps it.
  await c.click();
  await page.waitForURL("**/explorer"); // a ready DuckDB connection lands there
  await expect(page.getByTestId("passphrase-prompt")).toHaveCount(0);
  await openQueryPanel(page);
  await page.getByTestId("query-input").fill("SELECT count(*) AS n FROM items");
  await page.getByTestId("query-run").click();
  await expect(page.getByTestId("query-output").locator("table thead th")).toContainText(["n"]);
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByTestId("passphrase-prompt")).toHaveCount(0);
  await expect(page.getByTestId("connection-status")).toContainText(DUCK.id);

  // A tab without the token is asked; a wrong passphrase is refused.
  await page.evaluate(() => sessionStorage.removeItem("qv_token"));
  await page.reload({ waitUntil: "networkidle" });
  await answerPrompt(page, "wrong");
  await expect(page.getByTestId("passphrase-error")).toContainText("wrong passphrase");
  await answerPrompt(page, PASSPHRASE);
  await expect(page.getByTestId("passphrase-prompt")).toHaveCount(0);
  await expect(page.getByTestId("connection-status")).toContainText(DUCK.id);

  // Removing the lock lets the agent back in.
  await openConnect(page);
  c = page.getByTestId("conn-card").filter({ hasText: DUCK.id }).first();
  await c.getByTestId("conn-lock").click();
  await answerPrompt(page, PASSPHRASE);
  await expect(c).toHaveAttribute("data-locked", "false");
  expect((await mcp("run_sql", { sql: "SELECT 1" })).ok).toBeTruthy();
});
