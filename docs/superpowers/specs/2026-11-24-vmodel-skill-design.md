# A V-model skill

## Intent

A change today goes plan, tests, code, feature page. Nothing says which doc a
test proves, and the test layers carry the wrong names: the `testing` skill
calls every backend test "unit" and the browser suite "e2e".

The V-model fixes both. Each of four layers has one doc of record and one kind
of test, and every test is tied to the doc statement it proves. A project
skill drives each change down the docs and back up the tests.

| Layer | Doc of record | Tests |
|---|---|---|
| User | `docs/requirements.md` | `e2e/acceptance.spec.ts` |
| System | the feature pages | the other `e2e/*.spec.ts` |
| Integration | `docs/architecture.md` and the interface pages | backend and frontend test files that name an integration ID |
| Unit | the module's docstring or header comment | the test file beside the module |

## Goals

- A statement in a doc of record carries a named ID, and at least one test in
  the paired location names that ID.
- Every test file belongs to exactly one layer, and a script can tell which.
- One check script reports the whole coupling and fails on a broken one.
- A skill, `.claude/skills/vmodel/SKILL.md`, walks a change down and up the V.
- The two missing docs of record exist: `docs/requirements.md` and
  `docs/architecture.md`.

## Non-goals

- No numbered IDs and no tool that hands IDs out.
- No committed traceability matrix; the script prints it.
- No per-module doc pages and no IDs inside docstrings.
- No tagging of the existing docs and tests in one sweep; see
  [Migration](#migration).
- No renaming or moving of test files, except tests that move into
  `e2e/acceptance.spec.ts`.
- `docs/superpowers/` plans stay as they are: transitional, deleted when the
  work ships. They are not a V layer.

## Anti-goals

- A reader of the rendered docs sees an ID.
- The check blocks a change that touches nothing tagged.
- The slow browser suite grows a test per sentence of a feature page.
- A second source of truth: a doc statement repeated in another layer's doc.

## Which layer a doc is in

Every page under `docs/`, outside `docs/superpowers/`, opens with a comment
that declares its layer:

```md
<!-- layer: system -->
```

- `user`: `requirements.md`.
- `system`: a feature page.
- `integration`: `architecture.md` and the interface pages `api.md`,
  `viewer_server/api.md` and `mcp.md`. The REST API and the MCP tools are the
  contracts between the browser app, the agent and the backend, so backend
  tests prove them. *(Decided by the user.)*
- `none`: a page that states no behavior a test in the repo can prove:
  `future.md`, `AGENTS.md`, the `viewer_server/README.md` index, and the two
  Docker pages, which the release workflow's image smoke test covers.

## IDs and markers

An ID is the doc's path under `docs/` without `.md`, a slash, and a short
kebab-case slug: `dashboard/param-rerun`, `requirements/run-sql`,
`viewer_server/api/no-sql-accepted`, `architecture/session-channel`. The
page's declared layer is the ID's layer; the slug names the statement. An ID
is never renamed once a test names it.

A doc defines an ID with an HTML comment on the line above the statement:

```md
<!-- req: dashboard/param-rerun -->
A param change re-runs only the queries that use it.
```

A test names it in a comment directly above the test or group it covers:

```ts
// req: dashboard/param-rerun
test("a param change re-runs its query", ...)
```

```python
# req: architecture/session-channel
def test_push_reaches_the_armed_session(): ...
```

A comment may name several IDs, comma-separated. Many tests may name one ID.
A test may also name an ID of another layer as extra support, but only a test
in the ID's paired location proves it.

How fine an ID is, is a judgment: one per behavior a reader would call a
separate promise. A feature page gets IDs for what a user can see; edge cases
of one behavior are tests under the same ID, or integration and unit tests.

## Which layer a test file is in

- `e2e/acceptance.spec.ts` is user.
- Any other `e2e/*.spec.ts` is system.
- A backend or frontend test file that names an ID of an integration page is
  integration. A support marker for another layer's ID does not count.
- Any other backend or frontend test file is unit, and must sit beside the
  module it is named after: `test_sessions.py` beside `sessions.py`,
  `rows.test.ts` beside `rows.ts` or `rows.tsx`.

Today 20 of the 40 backend test files and 24 of the 25 frontend ones pair by
name. The other 21 are integration tests waiting for an ID, or need a rename
or a split; the builder decides per file as it is tagged.

## The check script

`scripts/vmodel_check.py`, run as `uv run python scripts/vmodel_check.py`. It
greps `req:` markers in `docs/` and the three test trees; it parses no test
code.

It fails on:

- an ID defined twice;
- a marker in a test that names an ID no doc defines;
- an ID with no test file naming it in its paired location;
- a unit test file whose paired module has no docstring (Python) or leading
  comment (TypeScript).

It reports, without failing:

- pages with no layer declaration;
- pages with a layer other than `none` that define no ID;
- test files in `e2e/` that name no ID;
- backend and frontend test files that neither name an integration ID nor
  pair with a module.

`--strict` turns the report into failures. The script prints the matrix: per
layer, each ID and the test files that name it.

It runs as a local pre-commit hook, so the CI `lint` job runs it too. The
script has its own small test for the marker parser and the layer rules.

## The skill

`.claude/skills/vmodel/SKILL.md`, written with `superpowers:writing-skills`.
It applies to any change that alters behavior. A pure refactor, a comment or a
docs wording fix skips it.

1. **Enter at the highest layer the change touches.** A new or changed user
   need enters at user; behavior a user can see, at system; a contract between
   components, at integration; anything inside one module, at unit.
2. **Go down.** At each layer from the entry down to unit: write or edit the
   statement in the doc of record, give it an ID, and write the failing test
   that names the ID. A layer the change does not alter is skipped, and the
   skill says so in one line.
3. **Build.** Write the code that makes the tests pass.
4. **Go up.** Run unit, integration, system, acceptance in that order, each
   only after the one below passes. Then run the check script.
5. **A failure goes across before it goes down.** A failing test sends the
   work to its paired doc first: is the statement wrong, or the code?

The skill layers on the current flow. A `docs/superpowers/` plan may still
split the work into tasks; each task follows the steps above. Because the docs
of record are edited on the way down, deleting the plan loses nothing.

It does not repeat the `testing` or `docs-writing` skills; it names them at
the step that needs them.

## The two new docs

- **`docs/requirements.md`**: what a user needs from QueryView, one ID each,
  each with its acceptance criteria. Seeded from the README's "What you can
  do" table and the three bullets under it, about nine requirements. No
  design, no screen detail; it links to the feature page that specifies each.
- **`docs/architecture.md`**: the components (SPA, FastAPI app, session store,
  drivers, MCP server, remote channel, git sync, viewer server) and the
  contract at each boundary, one ID per contract. A contract an interface
  page already states is linked, not restated; so are the "How it works" and
  "How it is stored" sections of the feature pages.

Both join the docs list at the end of `README.md`.

## Other files that change

- `.claude/skills/testing/SKILL.md`: the layer table becomes the four layers
  above, with the marker rule.
- `.claude/skills/docs-writing/SKILL.md` and `docs/AGENTS.md`: a statement a
  test proves carries a `req:` comment; the two new pages are docs of record
  that are not feature pages.
- Root `AGENTS.md`: one line under Tests pointing at the `vmodel` skill.
- `.pre-commit-config.yaml`: the local hook.
- `e2e/acceptance.spec.ts`: one test per seeded requirement. An existing e2e
  test that already is that journey moves here; it is not copied.

## Migration

The work ships with the two new pages fully tagged and their tests in place,
so the user and integration layers are coupled from day one for what those
pages state. The feature pages, the interface pages and the remaining test files start
untagged and show in the report. The skill tags a statement and its tests whenever a change
touches them. `--strict` goes into the hook once the report is empty.

## Approaches

- **Heading links.** A test names the doc heading it proves, as 7 test files
  do today. Cheapest, but the tie is per section and breaks when a heading is
  reworded.
- **Requirement IDs.** Every statement gets an ID and tests carry it: the
  textbook matrix. Numbered IDs collide across branches and need a tool to
  hand them out.
- **Pairing by file name.** A doc pairs with a test file by name. No markup,
  but it cannot say which test proves which behavior.

Chosen: requirement IDs with names in place of numbers, plus file pairing to
give the layer. Names need no allocation and do not collide; the file gives
the layer for free, so the ID only has to name the statement.

## Calls made in this design

These are the author's calls, not decisions the user made:

- Acceptance tests live in their own file, not behind a Playwright tag, so the
  layer is known from the path and the set runs alone by path.
- Unit tests pair by file name only, with no IDs.
- A feature-page ID must be proven by a browser test; a backend test under the
  same ID is support, not proof. This keeps the layers strict; ID granularity
  is what keeps the browser suite from growing.
- The check works per file, not per test: it does not verify that every single
  test has a marker above it.
- A page declares its own layer, and `none` is the one exemption; the script
  holds no list of pages.
- The Docker pages are `none`: their proof is the release workflow, outside
  the test trees.
- Broken couplings fail at once; missing ones only report until migration
  ends.

## Left to the builder

- The exact wording and count of the seeded requirements and contracts.
- Which existing e2e tests move into `e2e/acceptance.spec.ts`.
- Where the script's own test lives and how CI runs it.
- How the 21 unpaired test files are resolved as they are tagged.
