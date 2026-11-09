---
name: testing
description: Use when adding, changing or running tests in this repo — backend pytest, frontend vitest or Playwright e2e — to pick the right layer, place the file and reuse the shared fixtures.
---

# Testing

Three layers. Put a test in the lowest one that can observe the behavior,
and start from the nearest existing test file: it shows the call shapes.

| Layer | Tests | Lives | Run |
|---|---|---|---|
| Backend unit | stores, drivers, API routes, MCP tools via `TestClient` | beside the module: `backend/queryview/test_<module>.py`, `backend/queryview/drivers/test_<driver>.py` | `uv run --group test pytest backend/queryview` |
| Frontend unit | pure TS logic in `frontend/src` (no React rendering) | beside the module: `<module>.test.ts` | `npm test -w frontend` |
| e2e | user flows through the browser and the real `/mcp/` endpoint | `e2e/<feature>.spec.ts` | `npm run e2e` |

Backend tests ship in the wheel and run from the installed package in the
release workflow, so a test may import only from `queryview` and its own
directory — never from `e2e/`. Example data follows the root `AGENTS.md`
privacy rule: invented names only.

## Backend

- `backend/queryview/conftest.py` already isolates `DATA_DIR` per session
  (autouse). Reuse its fixtures instead of building your own: `default_ws_id`,
  `clone_base`, `git_env` (a bare remote wired to the default workspace),
  `wipe_workspace_entities`.
- Async store functions are called with `asyncio.run(...)`; a module-level
  `_run` helper is the pattern.
- Driver behavior that every driver must share goes in
  `drivers/test_contract.py`, parameterized over `DRIVERS`; a new driver only
  needs a `SAMPLES` entry there. Dialect SQL and real-database checks go in
  that driver's own `test_<driver>.py`.

## e2e

- Needs ClickHouse on `:8123`, Postgres on `:5432` and a built SPA
  (`npm run build:e2e`, a 2s session heartbeat). In the Claude Code web
  container, the `claudeai-run` skill starts the databases.
- `e2e/fixtures.ts` holds the navigation helpers, seeds and MCP client; extend
  them before writing a new click sequence.
- Locate elements by `data-testid` (`page.getByTestId(...)`), adding a
  kebab-case attribute in the component when missing (`db-picker`,
  `ch-connect`). Assert with `expect` (15 s default), not sleeps.
- Every test gets its own backend session (the `context` fixture). Seed data
  with the worker-scoped `seeds` fixture (`await seeds.duckdb()`); each worker
  has its own ClickHouse/Postgres database, `chDb()` — never hard-code `qvtest`.
- `shot(label)` saves a screenshot only under `E2E_SHOTS=1`.
- `BASE_URL=http://localhost:5173 npx playwright test` runs against a server
  you started, on one worker.

`CONTRIBUTING.md` covers installing the tooling and the full command set.
