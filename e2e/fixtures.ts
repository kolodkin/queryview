import { execFileSync, spawn } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { test as base, expect, type Page } from "@playwright/test";

export { expect };

// The backend's virtualenv (`uv sync`): its server, and the Python that seeds
// DuckDB/SQLite/Postgres with the drivers the backend already depends on. In
// the release gate the installed wheel's server is what lives there.
const VENV_BIN = resolve(import.meta.dirname, "..", ".venv", "bin");

// Coordinates default to the connection-form defaults the suite uses.
export const CH_HOST = process.env.CLICKHOUSE_HOST ?? "localhost";
export const CH_PORT = process.env.CLICKHOUSE_PORT ?? "8123";
export const CH_USER = process.env.CLICKHOUSE_USER ?? "default";
export const CH_PASSWORD = process.env.CLICKHOUSE_PASSWORD ?? "";
export const PG_HOST = process.env.PG_HOST ?? "localhost";
export const PG_PORT = process.env.PG_PORT ?? "5432";
export const PG_USER = process.env.PG_USER ?? "postgres";
export const PG_PASSWORD = process.env.PG_PASSWORD ?? "";

// Not `test`: a name that generic may already hold someone's data, and the
// seeding drops it. Each worker seeds (and drops) its own database, so one
// worker's teardown can't pull the table out from under another's test.
// Postgres uses the same name. Read in a test, never at import time.
export const chDb = () => `qvtest_${test.info().parallelIndex}`;

// --- HTTP ------------------------------------------------------------------

type Json = Record<string, any>;

/** Call the app's REST API; throws on a non-2xx unless `ok: false` is passed. */
export async function api(
  url: string,
  opts: { method?: string; json?: unknown; headers?: Record<string, string>; ok?: false } = {},
): Promise<{ status: number; body: any }> {
  const method = opts.method ?? (opts.json === undefined ? "GET" : "POST");
  const res = await fetch(url, {
    method,
    headers: { "content-type": "application/json", ...opts.headers },
    body: opts.json === undefined ? undefined : JSON.stringify(opts.json),
    signal: AbortSignal.timeout(10_000),
  });
  const text = await res.text();
  if (opts.ok !== false && !res.ok) throw new Error(`${method} ${url} -> ${res.status}: ${text}`);
  let body: any = text;
  try {
    body = JSON.parse(text);
  } catch {
    // not JSON
  }
  return { status: res.status, body };
}

/** Call one tool over the real MCP endpoint (stateless streamable HTTP), the
 * way an agent does, and return its JSON result. */
export async function mcpCall(baseURL: string, tool: string, args: Json): Promise<Json> {
  const res = await fetch(`${baseURL}/mcp/`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool, arguments: args } }),
    signal: AbortSignal.timeout(30_000),
  });
  const text = await res.text();
  // An SSE reply carries the JSON-RPC message on its `data:` line.
  const data = text.startsWith("{") ? text : text.split("\n").find((l) => l.startsWith("data:"))?.slice(5);
  if (!res.ok || !data) throw new Error(`MCP ${tool} -> ${res.status}: ${text}`);
  const msg = JSON.parse(data);
  expect(msg.error, JSON.stringify(msg)).toBeUndefined();
  expect(msg.result.isError, JSON.stringify(msg)).toBeFalsy();
  return JSON.parse(msg.result.content[0].text);
}

/** Run a statement against ClickHouse over HTTP. POST allows writes (the GET
 * interface is read-only by default), so seeding/teardown go through here. */
export async function chExec(sql: string): Promise<void> {
  const auth = Buffer.from(`${CH_USER}:${CH_PASSWORD}`).toString("base64");
  const res = await fetch(`http://${CH_HOST}:${CH_PORT}/`, {
    method: "POST",
    body: sql,
    headers: { authorization: `Basic ${auth}` },
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) throw new Error(`ClickHouse: ${await res.text()}`);
}

// --- Seeding through the backend's Python ----------------------------------

const PY_EXEC = `
import sys
kind, target, *stmts = sys.argv[1:]
if kind == "pg":
    import asyncio, os, asyncpg
    async def go():
        c = await asyncpg.connect(host=os.environ["PG_HOST"], port=int(os.environ["PG_PORT"]),
            user=os.environ["PG_USER"], password=os.environ["PG_PASSWORD"] or None, database=target)
        try:
            for s in stmts:
                await c.execute(s)
        finally:
            await c.close()
    asyncio.run(go())
else:
    import duckdb, sqlite3
    con = (duckdb if kind == "duckdb" else sqlite3).connect(target)
    for s in stmts:
        con.execute(s)
    con.commit()
    con.close()
`;

/** Run statements on Postgres database `db`, or a DuckDB/SQLite file. */
export function dbExec(kind: "pg" | "duckdb" | "sqlite", target: string, ...stmts: string[]): void {
  execFileSync(join(VENV_BIN, "python"), ["-c", PY_EXEC, kind, target, ...stmts], {
    env: { ...process.env, PG_HOST, PG_PORT, PG_USER, PG_PASSWORD },
    stdio: ["ignore", "ignore", "inherit"],
  });
}

const ITEMS_DDL = (t: string) => `CREATE TABLE ${t} (id INTEGER, name TEXT)`;
const ITEMS_ROWS = (t: string) => `INSERT INTO ${t} VALUES (1,'alpha'),(2,'beta'),(3,'gamma')`;

// --- Navigation helpers ----------------------------------------------------

/** Open the app on the Connect page. A previous test's connection can resume
 * on load, so connect flows navigate there explicitly. */
export async function openConnect(page: Page): Promise<void> {
  // No networkidle: the nav renders only once the session is attached.
  await page.goto("/");
  await page.getByTestId("nav-connect").click();
  await expect(page.getByTestId("connect-page")).toBeVisible();
}

/** Open a driver's connection form through the Connect page's "+ New" menu and
 * point it at the suite's server: the form defaults are a passwordless
 * localhost login. */
export async function startNewConnection(page: Page, driver: string): Promise<void> {
  await page.getByTestId("new-menu-toggle").click();
  await page.getByTestId("new-menu").getByTestId(`new-conn-${driver}`).click();
  const servers: Record<string, [string, string[]]> = {
    clickhouse: ["ch", [CH_HOST, CH_PORT, CH_USER, CH_PASSWORD]],
    postgres: ["pg", [PG_HOST, PG_PORT, PG_USER, PG_PASSWORD]],
  };
  if (driver in servers) {
    const [prefix, values] = servers[driver];
    const fields = ["host", "port", "username", "password"];
    for (const [i, field] of fields.entries()) await page.getByTestId(`${prefix}-${field}`).fill(values[i]);
  }
}

/** Connect to ClickHouse and stop on the database picker. */
export async function openClickhousePicker(page: Page): Promise<void> {
  await openConnect(page);
  await startNewConnection(page, "clickhouse");
  await expect(page.getByTestId("clickhouse-form")).toBeVisible();
  await page.getByTestId("ch-connect").click();
  await expect(page.getByTestId("db-picker")).toBeVisible();
}

/** Connect to ClickHouse and select the seeded database; ends on the explorer. */
export async function connectClickhouseTestDb(page: Page): Promise<void> {
  await openClickhousePicker(page);
  await page.locator(`[data-db="${chDb()}"]`).click();
  await expect(page.getByTestId("connection-status")).toContainText(`· ${chDb()}`);
}

/** Fill the SQL, name the query, and author a `params:` block via the
 * cell-view modal, then Save. */
export async function authorParamsYaml(page: Page, name: string, sql: string, paramsYaml: string): Promise<void> {
  await page.getByTestId("query-input").fill(sql);
  page.once("dialog", (d) => d.accept(name));
  await page.getByTestId("query-predefined-select").selectOption("::new::");
  await page.getByTestId("cell-view-toggle").click();
  await expect(page.getByTestId("cell-view-modal")).toBeVisible();
  await page.getByTestId("cell-view-input").fill(paramsYaml);
  await page.getByTestId("cell-view-save").click();
  await expect(page.getByTestId("cell-view-modal")).not.toBeVisible();
}

/** Open the query panel from wherever the test is, via the Studio page. */
export async function openQueryPanel(page: Page): Promise<void> {
  await page.getByTestId("nav-studio").click();
  await expect(page.getByTestId("query-panel")).toBeVisible();
}

/** Arm remote control via the agent popover and return the session id the
 * popover shows; leaves the popover closed. */
export async function armRemote(page: Page): Promise<string> {
  await page.getByTestId("agent-toggle").click();
  await page.getByTestId("remote-arm").check();
  const sidEl = page.getByTestId("remote-session-id");
  await expect(sidEl).toBeVisible();
  const sessionId = (await sidEl.innerText()).trim();
  expect(sessionId).toBeTruthy();
  await page.getByTestId("agent-toggle").click();
  return sessionId;
}

export const sessionId = (page: Page): Promise<string> =>
  page.evaluate(() => sessionStorage.getItem("qv_session")!);

// --- Drivers ---------------------------------------------------------------

export type SeedName = "testDb" | "pgDb" | "duckdb" | "sqlite";

export type DriverCase = {
  id: string;
  formTestid: string; // connection form testid
  connectTestid: string; // the Connect button testid
  seed: SeedName; // the `seeds` entry that seeds an `items` table
  status: () => string; // expected connection-status text after connecting
  pathField?: string; // a file-path field to fill with the seed value
  hasPicker?: boolean; // picks the seeded database from a picker
};

// Every case seeds the same `items(id, name)` table with alpha/beta/gamma.
export const CASES: DriverCase[] = [
  {
    id: "clickhouse",
    formTestid: "clickhouse-form",
    connectTestid: "ch-connect",
    seed: "testDb",
    status: () => `· ${chDb()}`,
    hasPicker: true,
  },
  {
    id: "postgres",
    formTestid: "postgres-form",
    connectTestid: "pg-connect",
    seed: "pgDb",
    status: () => `· ${chDb()}`,
    hasPicker: true,
  },
  {
    id: "duckdb",
    formTestid: "duckdb-form",
    connectTestid: "duck-connect",
    seed: "duckdb",
    status: () => "duckdb",
    pathField: "duck-path",
  },
  {
    id: "sqlite",
    formTestid: "sqlite-form",
    connectTestid: "sq-connect",
    seed: "sqlite",
    status: () => "sqlite",
    pathField: "sq-path",
  },
];
export const caseById = (id: string) => CASES.find((c) => c.id === id)!;
export const DUCK = caseById("duckdb");

export async function connect(page: Page, c: DriverCase, seed: string): Promise<void> {
  await openConnect(page);
  await startNewConnection(page, c.id);
  await expect(page.getByTestId(c.formTestid)).toBeVisible();
  if (c.pathField) await page.getByTestId(c.pathField).fill(seed);
  await page.getByTestId(c.connectTestid).click();
  // The status pill can already read "connected" from the session the shell
  // auto-resumed on load, so wait for the form to close: only the connect
  // response's handler dismisses it, and that handler moves on to the picker
  // or the explorer.
  await expect(page.getByTestId(c.formTestid)).toHaveCount(0);
  if (c.hasPicker) {
    await expect(page.getByTestId("db-picker")).toBeVisible();
    await page.locator(`[data-db="${chDb()}"]`).click();
  } else {
    // Picker-less driver (DuckDB, SQLite): connecting goes straight to ready.
    await expect(page.getByTestId("db-picker")).toHaveCount(0);
  }
  await expect(page.getByTestId("connection-status")).toContainText(c.status());
}

/** Start `queryview-backend` on a free port and a throwaway DATA_DIR. */
async function startBackend(): Promise<{ url: string; stop: () => Promise<void> }> {
  const bin = join(VENV_BIN, "queryview-backend");
  if (!existsSync(bin)) throw new Error(`${bin} not found: run \`uv sync\` first`);
  const port = await new Promise<number>((ok) => {
    const srv = createServer().listen(0, () => {
      const p = (srv.address() as { port: number }).port;
      srv.close(() => ok(p));
    });
  });
  const dataDir = mkdtempSync(join(tmpdir(), "qv-e2e-data-"));
  const logPath = join(dataDir, "backend.log");
  const log = createWriteStream(logPath);
  const proc = spawn(bin, [], {
    env: { ...process.env, SERVE_STATIC: "1", PORT: String(port), DATA_DIR: dataDir },
    stdio: ["ignore", "pipe", "pipe"],
  });
  proc.stdout.pipe(log);
  proc.stderr.pipe(log);
  const exited = new Promise((r) => proc.once("exit", r));
  const stop = async () => {
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill();
      await Promise.race([exited, new Promise((r) => setTimeout(r, 10_000))]);
      if (proc.exitCode === null && proc.signalCode === null) proc.kill("SIGKILL");
    }
    log.end();
    rmSync(dataDir, { recursive: true, force: true });
  };
  const url = `http://localhost:${port}`;
  const deadline = Date.now() + 60_000;
  for (;;) {
    const up = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1000) }).then(
      (r) => r.ok,
      () => false,
    );
    if (up) return { url, stop };
    if (proc.exitCode !== null || Date.now() > deadline) {
      const output = readFileSync(logPath, "utf-8");
      await stop();
      throw new Error(`backend did not come up:\n${output}`);
    }
    await new Promise((r) => setTimeout(r, 100));
  }
}

// --- Fixtures --------------------------------------------------------------

type Seeds = {
  /** ClickHouse database `chDb()` with an `items` table; returns its name. */
  testDb(): Promise<string>;
  /** Postgres database `chDb()` with an `items` table; returns its name. */
  pgDb(): Promise<string>;
  /** A DuckDB file with an `items` table; returns its path. */
  duckdb(): Promise<string>;
  /** A SQLite file with the same `items` table. */
  sqlite(): Promise<string>;
  /** As duckdb, plus invented names too long for the sidebar's default width. */
  duckdbLongNames(): Promise<string>;
  /** Two CSVs at the root (alpha/beta/gamma plus one delta row) and a gzipped CSV in `sub/`. */
  folder(): Promise<string>;
  /** Two CSVs sharing `id` and `name` in a different order, one with an extra `city`. */
  mixedFolder(): Promise<string>;
  /** Twelve CSVs and twelve subfolders, two past an Explorer Max entries of 10. */
  wideFolder(): Promise<string>;
};

export const test = base.extend<
  { shot: (label: string) => Promise<void> },
  { backendURL: string; seeds: Seeds }
>({
  /** The app under test. BASE_URL points at one started separately (then run
   * with --workers 1). Unset, each worker starts its own backend on a free
   * port and a throwaway DATA_DIR, so workers never see each other's
   * connections, workspaces or sessions; only the database servers are shared. */
  backendURL: [
    async ({}, use) => {
      const backend = process.env.BASE_URL ? { url: process.env.BASE_URL, stop: async () => {} } : await startBackend();
      try {
        // Point the default workspace at the remote CI stood up, through the
        // same API a user would. Unset locally: git sync stays disabled.
        const remote = process.env.E2E_GIT_REMOTE;
        if (remote) await api(`${backend.url}/api/workspaces/default`, { method: "PATCH", json: { remote } });
        await use(backend.url);
      } finally {
        await backend.stop();
      }
    },
    { scope: "worker", timeout: 90_000 },
  ],

  baseURL: async ({ backendURL }, use) => use(backendURL),

  /** Seeded databases, created on first use in a worker and dropped when it
   * ends. Each drops its target up front too, so a run left behind by a
   * crashed worker never leaks rows into this one. */
  seeds: [
    async ({}, use) => {
      const tmp = mkdtempSync(join(tmpdir(), "qv-e2e-seed-"));
      const db = chDb();
      const memo = new Map<string, Promise<string>>();
      const once = (key: string, make: () => Promise<string> | string) => () => {
        if (!memo.has(key)) memo.set(key, Promise.resolve(make()));
        return memo.get(key)!;
      };
      const duck = (name: string, ...tables: string[]) => {
        const path = join(tmp, `${name}.duckdb`);
        dbExec("duckdb", path, ...tables.flatMap((t) => [ITEMS_DDL(t), ITEMS_ROWS(t)]));
        return path;
      };
      const dir = (name: string, files: Record<string, string | Buffer>) => {
        const root = join(tmp, name);
        for (const [rel, body] of Object.entries(files)) {
          mkdirSync(join(root, rel, ".."), { recursive: true });
          writeFileSync(join(root, rel), body);
        }
        return root;
      };
      const rows = "id,name\n1,alpha\n2,beta\n3,gamma\n";
      const seeds: Seeds = {
        testDb: once("testDb", async () => {
          await chExec(`DROP DATABASE IF EXISTS ${db}`);
          await chExec(`CREATE DATABASE ${db}`);
          await chExec(`CREATE TABLE ${db}.items (id UInt32, name String) ENGINE = MergeTree ORDER BY id`);
          await chExec(`INSERT INTO ${db}.items (id, name) VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')`);
          return db;
        }),
        pgDb: once("pgDb", () => {
          dbExec("pg", "postgres", `DROP DATABASE IF EXISTS ${db} WITH (FORCE)`, `CREATE DATABASE ${db}`);
          dbExec("pg", db, "CREATE TABLE items (id int, name text)", ITEMS_ROWS("items"));
          return db;
        }),
        duckdb: once("duckdb", () => duck("qv", "items")),
        sqlite: once("sqlite", () => {
          const path = join(tmp, "qv.sqlite");
          dbExec("sqlite", path, ITEMS_DDL("items"), ITEMS_ROWS("items"));
          return path;
        }),
        duckdbLongNames: once("duckdbLongNames", () =>
          duck("long", "items", "sales_reporting_monthly_rollup", "warehouse_shipment_reconciliation_log"),
        ),
        folder: once("folder", () =>
          dir("duck_folder", {
            "items.csv": rows,
            "extra.csv": "id,name\n4,delta\n",
            "sub/nested.csv.gz": gzipSync(rows),
          }),
        ),
        mixedFolder: once("mixedFolder", () =>
          dir("duck_mixed", { "a.csv": "id,name\n1,alpha\n2,beta\n", "b.csv": "name,id,city\ngamma,3,lisbon\n" }),
        ),
        wideFolder: once("wideFolder", () => {
          const files: Record<string, string> = {};
          for (let i = 1; i <= 12; i++) {
            const n = String(i).padStart(2, "0");
            files[`f${n}.csv`] = `id\n${i}\n`;
            mkdirSync(join(tmp, "duck_wide", `d${n}`), { recursive: true });
          }
          return dir("duck_wide", files);
        }),
      };
      await use(seeds);
      if (memo.has("testDb")) await chExec(`DROP DATABASE IF EXISTS ${db}`);
      if (memo.has("pgDb")) dbExec("pg", "postgres", `DROP DATABASE IF EXISTS ${db} WITH (FORCE)`);
      rmSync(tmp, { recursive: true, force: true });
    },
    { scope: "worker" },
  ],

  /** Give every test its own session. Session state lives on the server, so a
   * fresh browser context is not fresh state: without this a test would resume
   * the previous one's remembered SQL, sidebar width and workspace. Seeds
   * `qv_session` but never `qv_tab`, so each page still mints its own tab token
   * and a second tab opened inside a test starts its own session. */
  context: async ({ context, baseURL }, use) => {
    const tab = `e2e-${crypto.randomUUID()}`;
    // `select` with no id always creates a session; `attach` would resume the
    // most recent unheld one — the previous test's, once its tab has released.
    const { body } = await api(`${baseURL}/api/sessions/select`, { json: { tab } });
    expect(body.session.ui, "the context fixture resumed a used session").toEqual({});
    // Release it so the page's own tab token can claim it on load.
    await api(`${baseURL}/api/sessions/release`, { json: { tab } });
    await context.addInitScript((sid) => sessionStorage.setItem("qv_session", sid), body.session.id);
    await use(context);
  },

  /** Save labeled, numbered screenshots into the test's output directory, so
   * an e2e screenshot report can keep call order. Off unless E2E_SHOTS=1:
   * full-page captures cost CI time nobody looks at. */
  shot: async ({ page }, use, testInfo) => {
    let n = 0;
    await use(async (label) => {
      if (process.env.E2E_SHOTS !== "1") return;
      n += 1;
      const safe = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "shot";
      await page.screenshot({ path: testInfo.outputPath(`${String(n).padStart(2, "0")}-${safe}.png`), fullPage: true });
    });
  },
});
