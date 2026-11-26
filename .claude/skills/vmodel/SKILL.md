---
name: vmodel
description: Use when a change alters behavior in this repo, before writing its doc, test or code; when adding, changing or running a test (backend pytest, frontend vitest or Playwright e2e); and when adding or editing a page under docs/.
---

# V-model

Every behavior has a statement in a doc of record, and a test that names the
statement's ID (at unit, a test beside the module). A change walks down the
docs, writing a failing test at each layer, then up the tests. When a
`docs/superpowers/` plan splits the work into tasks, each task follows this
skill.

| Layer | Doc of record | A test covers | Proved in |
|---|---|---|---|
| User | `docs/requirements/` | a user requirement end to end | `e2e/acceptance.spec.ts` |
| System | `docs/system/` | one feature through the browser | any `e2e/*.spec.ts`, by convention `e2e/<feature>.spec.ts` |
| Integration | `docs/architecture/` | routes, stores, MCP tools, drivers working together | `backend/queryview/**/test_*.py`, `frontend/src/**/*.test.ts(x)` naming an `architecture/` ID |
| Unit | the module's docstring (Python) or leading comment (TypeScript) | one module's logic | the test file beside the module, named after it, no ID |

## Markers

An ID is the page's path under `docs/` without `.md`, then a kebab-case slug.
The doc defines it on the line above the statement:

```md
<!-- req: requirements/queryview/run-sql -->
A user can run SQL, page through the rows, pick columns, and download CSV.
```

A test names it directly above the test or group (`#` in Python; several IDs
comma-separated):

```ts
// req: requirements/queryview/run-sql
test("run SQL, pick columns, page and download CSV", async ({ page, seeds }) => {
```

Never reword a slug a test names. A marker outside the layer's "Proved in"
location is support, not proof.

## Tests on two layers

A browser test may belong to two layers, user and system. It lives in
`e2e/acceptance.spec.ts` and names both IDs:

```ts
// req: requirements/queryview/browse-tables, system/explorer/browse
```

When an acceptance test already walks a system statement, add the
statement's ID to that test's marker; do not write a second browser test for
it. A user requirement is still proved only in `e2e/acceptance.spec.ts`.

Only this pair shares tests, for now: the line between a user journey and a
feature's behavior is the least sharp one. Every other test has one layer.
An integration test proves no system statement, and a unit test names no ID.

## Steps

1. **Name the entry layer: the highest one the change touches.** A new or
   changed user need: user. Anything a user can see or set in the app (a
   screen, a label, an error, a limit, a default): system. A contract between
   components (an API route, an MCP tool, a store, a driver): integration.
   Logic inside one module: unit. Example: raising the maximum query timeout
   enters at system (`docs/system/queryview.md`, "Query timeout"); the bound
   check inside the module that applies it is unit.
2. **Go down, one layer at a time, from the entry to unit.** At each layer
   above unit:
   - write or edit the statement in its doc of record (see [Writing a doc](#writing-a-doc));
   - give it an ID, or keep its existing one. How fine an ID is, is a
     judgment: give one per behavior a reader would call a separate promise.
     On a system page, give IDs to what a user can see; test an edge case of
     one behavior under the same ID, or at integration or unit;
   - write a test that names the ID and fails now (see
     [Writing a test](#writing-a-test)). A changed number or default is a
     changed statement: its test asserts the new value. The failing test may
     be an existing one whose assertion changes.

   At unit: edit the module's docstring or leading comment and the test beside
   the module; no ID, no marker.

   For a layer the change does not alter, write one line: `Skipping <layer>:
   <why>.`
3. **Build.** Write the code that makes the tests pass.
4. **Go up.** Run every layer's tests; the suites are independent, so run them
   side by side:
   - the touched unit and integration test files first, as a quick check;
   - `uv run --group test pytest backend/queryview scripts` and
     `npm test -w frontend`;
   - the touched `e2e/<feature>.spec.ts` and `e2e/acceptance.spec.ts`, also
     when untouched: a change below it can break a journey;
   - `uv run python scripts/vmodel_check.py` (also a pre-commit hook). It must
     exit 0; `--strict` also fails on the untagged pages and tests it lists.
     Once the report shows no gaps, `--strict` goes into the pre-commit hook.
5. **A failure goes back down the V to where it started.** Read the failing
   test's paired statement first: is the statement wrong, or the code? A
   failure seen at one layer often starts lower: a browser test can fail on a
   driver or a client-side race. The layer where it starts is the one whose
   statement and test were missing, so walk step 2 at that layer:
   - state the behavior there: the module's docstring or leading comment at
     unit, the architecture page at integration;
   - write the test at that layer that fails for the cause, and see it fail;
   - fix the code there, then go up again from that layer.

   A test that passes on retry ("flaky") still has a cause; never retry or skip
   it away.

## Tagging on touch

Most pages and test files carry no IDs yet. The statement a change edits gets
its ID in that change, and so does each test file it edits (unit test files
excepted), even when the rest of the page stays untagged. "It had no marker
before" is not a reason to leave it without one.

## Not covered

A pure refactor, a comment, or a docs wording fix that changes no behavior
skips the steps above; the test and doc rules below still apply.

## Writing a doc

Every docs edit ends with the `devpowers:shortify` checklist on the pages you
touched; it owns brevity, heading depth and link hygiene. The house style on
top of it:

- A page holds one layer's content; a change to an existing feature is a
  section on its page. Copy the shape of the nearest page.
- A requirements page has no design and no screen detail.
- Present tense, describing current behavior.
  No history ("now", "previously", "since vX"); proposals go in `future.md`
  and move into the feature's page when they ship.
- On a system page, the opening paragraph names the route (`/dashboard`,
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

## Where a decision goes

A design decision (why this solution or technology) carries no ID: it explains
a statement, and no test proves it.

- It sits beside what it explains, as a `## Why` section on that page, at that
  page's layer: a product choice on its `docs/system/` page, a build or
  technology choice on its `docs/architecture/` page. `docs/system/creds.md`
  "Why" is the example.
- A choice that spans several pages goes in that layer folder's
  `decisions.md`.

## Writing a test

Put a test in the lowest layer that can observe the behavior, and start from
the nearest existing test file: it shows the call shapes.

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
