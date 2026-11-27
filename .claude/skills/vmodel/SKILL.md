---
name: vmodel
description: Use when a change alters behavior in this repo, before writing its doc, test or code; when adding, changing or running a test (backend pytest, frontend vitest or Playwright e2e); and when adding or editing a page under docs/.
---

# V-model

Extends the `devpowers:vmodel` skill: load it first for the method (markers,
the steps down and up the V, where a decision goes). This skill holds only
what is particular to QueryView. When a `docs/superpowers/` plan splits the
work into tasks, each task follows both.

| Doc layer | Doc of record | Test layer | Proved in |
|---|---|---|---|
| User | `docs/user_guide/` | Acceptance | any `e2e/*.spec.ts`, by convention `e2e/<feature>.spec.ts` |
| Architecture | `docs/architecture/` | System | `backend/queryview/**/test_*.py`, `frontend/src/**/*.test.ts(x)` naming an `architecture/` ID |
| Design | `docs/designs/` | Integration | the same locations, naming a `designs/` ID |
| Implementation | the module's docstring (Python) or leading comment (TypeScript) | Unit | the test file beside the module, named after it, no ID |

The docs root is `docs/`: `user_guide/query/run-sql` is defined in
`docs/user_guide/query.md` as `<!-- req: run-sql -->`, and named by a test as
`// req: user_guide/query/run-sql` (`#` in Python). `e2e/acceptance.spec.ts`
holds one journey per user goal a guide page opens with.

## Tests on two layers

Architecture and designs share tests: they have one "Proved in" location, so a
test may name IDs from both. A browser test proves no architecture or design
statement.

## Steps

- **Entry layer.** A contract between components here is an API route, an MCP
  tool, a store or a driver. Example: raising the maximum query timeout enters
  at user (`docs/user_guide/queryview.md`, "Query timeout"); the bound check
  inside the module that applies it is unit. On a guide page, give IDs to
  what a user can see.
- **Go up.** The suites are independent, so run them side by side:
  - the touched unit and integration test files first, as a quick check;
  - `uv run --group test pytest backend/queryview scripts` and
    `npm test -w frontend`;
  - the touched `e2e/<feature>.spec.ts` and `e2e/acceptance.spec.ts`, also
    when untouched;
  - `uv run python scripts/vmodel_check.py --strict` (also the pre-commit
    hook). It must exit 0: an untagged page or test file fails like an error.
- **A failure that starts lower** than the browser test showing it (a driver,
  a client-side race) is stated on its `architecture/` or `designs/` page, or
  in the module's docstring or leading comment at implementation.

## Every file is tagged

Every layer page defines at least one ID and every test file names one. The
exceptions: a `decisions.md` page, and a unit test file, which pairs with its
module by name (`test_main.py` also with `__main__.py`).
`docs/user_guide/creds.md` "Why" is the example of a decision beside its
statement.

## Writing a doc

Every docs edit ends with the `devpowers:shortify` checklist on the pages you
touched; it owns brevity, heading depth and link hygiene. The house style on
top of it:

- A change to an existing feature is a section on its page.
- A guide page holds no architecture or design: it keeps one line on what the
  user sees and links down to the page that explains it.
- Proposals go in `future.md` and move into the feature's page when they ship.
- On a guide page, the opening paragraph names the route (`/dashboard`,
  `/explorer`, …) and links the neighboring pages a reader may have meant
  instead.
- UI labels are **bold**, exactly as the screen shows them. A page about a
  screen may open with a layout sketch; the `devpowers:ascii-sketch` skill draws it.
- `docs/architecture/api.md` is the endpoint reference. A feature page's
  `## API` section names its endpoints and links there, as `scripts.md` does;
  bodies and responses are not repeated.
- Links are relative, `./page.md#anchor`. Code is named only when the reader
  must open it, as a module or package path. Code and docstrings that back-link
  a heading quote it word for word, so grep for the old text when renaming one.
- End with `## Related docs`: a bullet per linked page with a short phrase.
- Example names are invented (`sales_reporting`, `example.internal`), per the
  root `AGENTS.md` privacy rule.

## Writing a test

- Frontend unit tests cover pure TypeScript logic, with no React rendering.
- Backend tests ship in the wheel and run from the installed package in the
  release workflow, so a test may import only from `queryview` and its own
  directory — never from `e2e/`.
- Example data follows the root `AGENTS.md` privacy rule: invented names only.

Run backend tests with `uv run --group test pytest` (its `testpaths` cover
`backend/queryview` and `scripts`), frontend ones with `npm test -w frontend`,
and the browser suite with `npm run e2e`. `CONTRIBUTING.md` covers installing
the tooling and the full command set.

## Backend tests

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

## Browser tests

- Needs ClickHouse on `:8123`, Postgres on `:5432`, MySQL on `:3306` and a built SPA
  (`npm run build:e2e`, a 2s session heartbeat). In the Claude Code web
  container, the `claudeai-run` skill starts the databases.
- `e2e/fixtures.ts` holds the navigation helpers, seeds and MCP client; extend
  them before writing a new click sequence.
- Locate elements by `data-testid` (`page.getByTestId(...)`), adding a
  kebab-case attribute in the component when missing (`db-picker`,
  `ch-connect`). Assert with `expect` (15 s default), not sleeps.
- Every test gets its own backend session (the `context` fixture). Seed data
  with the worker-scoped `seeds` fixture (`await seeds.duckdb()`); each worker
  has its own ClickHouse/Postgres/MySQL database, `chDb()` — never hard-code `qvtest`.
- `shot(label)` saves a screenshot only under `E2E_SHOTS=1`.
- `BASE_URL=http://localhost:5173 npx playwright test` runs against a server
  you started, on one worker. Start that server with `DATA_DIR` set to a
  scratch folder; the suite refuses one on the default `~/.queryview`.
