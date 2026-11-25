---
name: vmodel
description: Use when a change alters behavior in this repo, before writing its doc, test or code — walks the change down the docs and up the tests so every test names the doc statement it proves.
---

# V-model

Every behavior has a statement in a doc of record, and a test that names the
statement's ID (at unit, a test beside the module). A change walks down the
docs, writing a failing test at each layer, then up the tests. When a
`docs/superpowers/` plan splits the work into tasks, each task follows this
skill.

| Layer | Doc of record | Proved in |
|---|---|---|
| User | `docs/requirements/` | `e2e/acceptance.spec.ts` |
| System | `docs/system/` | any `e2e/*.spec.ts` |
| Integration | `docs/architecture/` | `backend/queryview/**/test_*.py`, `frontend/src/**/*.test.ts(x)` naming an `architecture/` ID |
| Unit | the module's docstring (Python) or leading comment (TypeScript) | the test file beside the module, named after it, no ID |

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

A test may name two IDs: an acceptance test that also proves a system
statement names both, so no second browser test repeats it. Never reword a
slug a test names. A marker outside the layer's "Proved in"
location is support, not proof.

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
   - write or edit the statement in its doc of record (load `docs-writing`);
   - give it an ID, or keep its existing one. How fine an ID is, is a
     judgment: give one per behavior a reader would call a separate promise.
     On a system page, give IDs to what a user can see; test an edge case of
     one behavior under the same ID, or at integration or unit;
   - write a test that names the ID and fails now (load `testing`). A changed
     number or default is a changed statement: its test asserts the new value.
     The failing test may be an existing one whose assertion changes.

   At unit: edit the module's docstring or leading comment and the test beside
   the module; no ID, no marker (`docs-writing` does not apply).

   For a layer the change does not alter, write one line: `Skipping <layer>:
   <why>.`
3. **Build.** Write the code that makes the tests pass.
4. **Go up.** Run each only after the one before passes:
   1. the unit test files touched;
   2. the integration test files touched;
   3. `uv run --group test pytest backend/queryview scripts`;
   4. `npm test -w frontend`;
   5. the touched `e2e/<feature>.spec.ts`;
   6. `e2e/acceptance.spec.ts`;
   7. `uv run python scripts/vmodel_check.py` (also a pre-commit hook). It must
      exit 0; `--strict` also fails on the untagged pages and tests it lists.
      Once the report shows no gaps, `--strict` goes into the pre-commit hook.
5. **A failure goes across before it goes down.** Read the failing test's
   paired statement first: is the statement wrong, or the code? Fix that one.

## Tagging on touch

Most pages and test files carry no IDs yet. The statement a change edits gets
its ID in that change, and so does each test file it edits (unit test files
excepted), even when the rest of the page stays untagged. "It had no marker
before" is not a reason to leave it without one.

## Not covered

A pure refactor, a comment, or a docs wording fix that changes no behavior
skips this skill; `testing` and `docs-writing` still apply.
