# User guide layout — design

## Intent

Bring QueryView's docs onto the layout `devpowers:vmodel` 1.20.2 recommends,
so the project's layers match the generic skill instead of being mapped onto
it. The user layer becomes a real, published user guide; everything that is
not guide material is architecture or design.

## Goals

- `docs/user_guide/`: one guide page per feature, written as a guide (task
  sections, second person), proved by browser tests.
- `docs/architecture/`: topology, data model, wire contracts, security model.
- `docs/designs/`: how components work together inside the system.
- `README.md` links only to user guide pages; `CONTRIBUTING.md` indexes
  `architecture/` and `designs/`.
- `scripts/vmodel_check.py --strict` passes at every step.

## Non-goals

- No product behavior change. No new tests, except where a statement moved
  down the V loses its only proof (see Risks).
- No slug renames: an ID changes only its prefix (`system/query/fields` →
  `user_guide/query/fields`).

## Anti-goals

- A statement that ends up with no test, or a test that names a dead ID.
- A fact stated in two layers (generic "one fact, one layer").
- Broken links or back-links (docs, code comments, MCP tool descriptions).

## Approaches

1. **Staged (picked).** Four commits, each leaving the checker and all suites
   green: rename and fold, then split architecture/designs, then move
   non-guide sections down, then rewrite the guide voice. Each step is
   reviewable on its own and a regression points at one step.
2. **One big change.** Same end state in one commit. Faster to write, but the
   rename noise (≈60 back-linking files) hides the content moves in review.
3. **Rename only** `requirements/` → `user_guide/`. Rejected: the
   requirements page is a needs checklist, not a guide; the system pages are
   the guide.

## Layers (replaces the project skill's table)

| Doc layer | Doc of record | Test layer | Proved in |
|---|---|---|---|
| User | `docs/user_guide/` | Acceptance | any `e2e/*.spec.ts` |
| Architecture | `docs/architecture/` | System | `backend/queryview/**/test_*.py`, `frontend/src/**/*.test.ts(x)` naming an `architecture/` ID |
| Design | `docs/designs/` | Integration | the same locations, naming a `designs/` ID |
| Implementation | module docstring / leading comment | Unit | the test file beside the module, no ID |

Decided: architecture and design statements share one "Proved in" rule; the
layers differ in what the doc states, not in where the test lives. A test may
name architecture and design IDs together (the project's one shared pair).
`e2e/acceptance.spec.ts` keeps its tests; it is no longer a special location.

## Step 1 — fold requirements, rename `system/` → `user_guide/`

- Each requirement in `docs/requirements/queryview.md` moves, with its slug,
  into the page its "See" line names: `add-connection`, `open-database` →
  `connect.md`; `run-sql` → `query.md`; `run-script` → `scripts.md`;
  `browse-tables` → `explorer.md`; `live-dashboard`,
  `dashboard-many-connections` → `dashboard.md`; `workspace-git` →
  `gitsync.md`; `yaml-export-import` → `export-import.md`; `agent-drives` →
  `mcp.md`. A slug that collides with one on the target page is the builder's
  to resolve (keep both statements, suffix the newer slug).
- "Design principles" goes to `docs/designs/decisions.md` (no ID, exempt).
- `git mv docs/system docs/user_guide`; delete `docs/requirements/`.
- Move `docs/docker.md` and `docs/viewer_server_docker.md` into
  `user_guide/`; the checker exempts them by name, like `decisions.md`
  (decided: running the image is a user task, but no test can prove it here).
- Rewrite every marker and link: e2e markers, `../system/` and
  `../requirements/` links, code comments and docstrings that name
  `docs/system/...`, and the MCP tool descriptions in
  `backend/queryview/mcp_server.py` (agent-visible text).
- Checker: `LAYER_DIRS`, `ID_RE`, `PROOF` and the exemption list follow the
  layer table; `ACCEPTANCE` goes. `scripts/test_vmodel_check.py` follows.

## Step 2 — split `architecture/` into `architecture/` and `designs/`

Builder's call per section; the starting split:

- Stay in `architecture/`: `overview.md`, `api.md`, `viewer_server_api.md`,
  `storage.md` (data directory, schema, encryption), the "Tools" contract in
  `mcp.md` with its IDs. "Isolation & security" (no ID, no test) folds into
  `overview.md`, since `dashboards.md` is left with nothing else (my call).
- Move to `designs/`: `sessions.md`; "Running the queries" and "Which
  connection, which database" from `dashboards.md`; "Federated drafts" and
  "How it works" from `mcp.md`; the folder-mode "Why" (into
  `designs/decisions.md`).
- `storage.md` "CI" moves to a contributor page at the `docs/` root (no
  layer).
- An ID moves with its statement and gets the new prefix.

## Step 3 — move non-guide sections out of `user_guide/`

Out (to the layer they belong to, merged with what is already there):
`## API` sections (into `api.md`, keeping one guide line where the user calls
the endpoint), `connect.md` "Storage & migrations", "Persistence (SQLite)",
"Config encryption", "Flow", "CI"; `session.md` "How it is stored";
`mcp.md` "How it works"; `dashboard.md` "Running the queries" and
"Isolation & security". Where the user sees an effect, the guide keeps one
line and links down ("Saved passwords are encrypted" → `storage.md`).

Stay: the guide's short list of what you can ask your agent, linking to the
tool contract in `architecture/mcp.md` (my call: moving the contract up would
need about 7 new browser tests), "The `window.queries` contract for HTML
authors", the viewer server's config file, git-sync's repository layout, and
the user-facing "Why" in `creds.md`.

## Step 4 — guide voice

Each page opens with what the feature is for, then task sections ("Create a
connection", "Edit or delete a connection"), each led by its statement, then
what the screen shows. Second person. Heading renames require grepping code
comments that quote them (project skill rule). A rewording pass: untagged
prose stays untagged and gets no new ID (my call; the generic skill's "Not
covered" lets a wording change that alters no behavior skip the steps).

## Published

"Published" means linked from `README.md` (my call). No docs site; the
README's relative links breaking on PyPI is outside this change.

## Index and instructions

- `README.md` "Documentation": the user guide pages only (deployment pages
  included, now in `user_guide/`).
- `CONTRIBUTING.md`: lists `architecture/` and `designs/` pages; its tree
  comment names the new folders.
- `docs/AGENTS.md`: one folder per layer as above; a guide page joins
  `README.md`, any other page joins `CONTRIBUTING.md`.
- `.claude/skills/vmodel/SKILL.md`: the layer table above; the mapping
  paragraph and the "Tests on two layers" section are rewritten (user and
  system no longer share tests; architecture and designs do).

## Risks

- No current `system/` ID sits in a section that moves down in step 3, so no
  statement loses its browser proof. If step 2 or 3 moves an ID whose only
  test is in `e2e/`, the builder either adds a backend test or keeps the
  statement in the guide.
- Three e2e tests name architecture IDs as support; they keep the new prefix.

## Left to the builder

The exact section split in steps 2 and 3, slug collisions in step 1, and
guide wording in step 4.
