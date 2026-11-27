# User Guide Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move QueryView's docs onto the `devpowers:vmodel` 1.20.3 layout: `user_guide/`, `architecture/`, `designs/`.

**Architecture:** Docs-only restructure in five commits, each leaving the
checker and test suites green. The checker (`scripts/vmodel_check.py`) learns
the new layers first, in the same commit that renames the folders and IDs.

**Tech Stack:** Markdown, Python 3 standard library (checker), pytest, Playwright markers in TypeScript comments.

**Spec:** `docs/superpowers/specs/2026-11-27-user-guide-layout-design.md`

## Global Constraints

- No product behavior change; MCP tool descriptions in `backend/queryview/mcp_server.py` change only the doc paths they name.
- Slugs never change; an ID changes only its prefix (`system/query/fields` → `user_guide/query/fields`).
- No new `req:` IDs and no new tests, except where a moved ID would lose its only proof.
- Every docs edit ends with the `devpowers:shortify` checklist on touched pages.
- Invented example names only (root `AGENTS.md` privacy rule). No AI attribution trailers in commits.
- Each task ends green on all of:
  - `uv run python scripts/vmodel_check.py --strict` → exit 0
  - `uv run --group test pytest backend/queryview scripts -q` → all pass
  - `npm test -w frontend` → all pass
  - the link check below → no output
  - `grep -rnE 'docs/(system|requirements)/|\.\./(system|requirements)/|decisions\.md' --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.venv . | grep -v 'docs/superpowers/[a-z]*/2026-11-27'` → no output (from Task 2 on; Task 1 allows `decisions.md`)

Link check (relative `.md` links and their anchors, GitHub slug rules):

```bash
uv run python - <<'EOF'
import re, pathlib
slug = lambda h: re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
heads = {p: {slug(m) for m in re.findall(r"^#+ (.+)$", p.read_text(), re.M)} for p in pathlib.Path(".").glob("**/*.md") if "node_modules" not in p.parts and ".venv" not in p.parts}
for p in heads:
    for target, anchor in re.findall(r"\]\(([^)#\s]*\.md)?(?:#([^)\s]+))?\)", p.read_text()):
        if not target and not anchor: continue
        t = (p.parent / target).resolve() if target else p.resolve()
        rel = next((q for q in heads if q.resolve() == t), None)
        if rel is None: print(f"{p}: missing {target}")
        elif anchor and anchor not in heads[rel]: print(f"{p}: missing #{anchor} in {target or p.name}")
EOF
```

## Review Focus

- A heading renamed in Tasks 3–5 that a code comment or docstring quotes word for word: the comment must follow (grep the old heading text before each rename).
- An e2e marker that still names a folded requirement's old prefix: the checker fails with "no doc defines"; fix the marker, never the slug.
- An `architecture/` or `designs/` ID whose only test is under `e2e/`: the checker fails with "has no test in backend/ or frontend/"; keep the statement in the guide instead of adding a test.
- A page left with no `req:` marker after its sections move out: fold it into a neighbour rather than exempting it.
- `docs/superpowers/` spec and plan for `one-run-per-page`: their paths and IDs follow every move (the link check and grep cover them).

---

### Task 0: Remove shipped 2026-11-15 plans and specs

**Files:**
- Delete: `docs/superpowers/plans/2026-11-15-dashboard-rename-delete.md`, `docs/superpowers/plans/2026-11-15-not-in-git-marker.md`, `docs/superpowers/specs/2026-11-15-dashboard-rename-delete-design.md`, `docs/superpowers/specs/2026-11-15-not-in-git-marker-design.md`

- [ ] **Step 1:** Confirm shipped: `grep -n 'req: rename-delete\|req: not-in-git' docs/system/*.md` shows both IDs.
- [ ] **Step 2:** `git rm` the four files; run the link check → no output.
- [ ] **Step 3:** Commit `Docs: remove shipped rename-delete and not-in-git plans`.

### Task 1: Checker learns the new layers; fold requirements; rename `system/` → `user_guide/`

**Files:**
- Modify: `scripts/vmodel_check.py`, `scripts/test_vmodel_check.py`
- Move: `docs/system/` → `docs/user_guide/`; `docs/docker.md`, `docs/viewer_server_docker.md` → `docs/user_guide/`
- Delete: `docs/requirements/queryview.md` (after folding)
- Modify: every file the grep in Global Constraints lists (e2e markers, ~60 code comments/docstrings, `mcp_server.py` tool descriptions, `README.md`, `CONTRIBUTING.md`, `docs/AGENTS.md`, `.claude/skills/vmodel/SKILL.md`, docs links, the `one-run-per-page` spec and plan)

**Interfaces:**
- Produces: checker constants `LAYER_DIRS = {"user_guide": "acceptance", "architecture": "system", "designs": "integration"}`, `ID_RE` matching `^(user_guide|architecture|designs)(/[a-z0-9_-]+)+$`, `PROOF` = user_guide → any `e2e/` file; architecture and designs → any non-`e2e/` test; `UNTESTED = {"docker.md", "viewer_server_docker.md"}` exempt from the untagged-page gap. `ACCEPTANCE` is removed. A non-e2e test is integration when it names an `architecture/` or `designs/` ID.
- `decisions.md` exemption stays until Task 2.

- [ ] **Step 1: Rewrite the checker tests for the new layers** in `scripts/test_vmodel_check.py`:
  - every `system/` fixture path and ID → `user_guide/`; `test_system_id_needs_a_browser_test` → `test_user_guide_id_needs_a_browser_test`;
  - replace `test_an_acceptance_test_may_also_prove_a_system_id` and `test_layer_proof_locations` with `test_layer_proof_locations`: a `user_guide/` ID proved by `e2e/dash.spec.ts` has no error; an `architecture/` ID and a `designs/` ID each proved only by `e2e/` error with "has no test in backend/ or frontend/"; each proved by `backend/queryview/test_x.py` has none;
  - `test_a_designs_id_marks_an_integration_test`: `backend/queryview/test_x.py` naming only `designs/d/x` is not reported as an unpaired unit test;
  - `test_deployment_pages_need_no_id`: `docs/user_guide/docker.md` with no marker → `gaps == []`.
- [ ] **Step 2:** `uv run --group test pytest scripts -q` → the new tests FAIL.
- [ ] **Step 3:** Change the checker constants per Interfaces; update its docstring's layer wording.
- [ ] **Step 4:** `uv run --group test pytest scripts -q` → PASS.
- [ ] **Step 5: Fold requirements.** Move each requirement section, with its `<!-- req: <slug> -->`, into the target page given in the spec's Step 1 list, as that page's opening task section; drop its "See …" line. "Design principles" becomes `## Why` at the end of `queryview.md` (before `## Related docs`), replacing its stub. A slug collision on the target page: keep both, suffix the folded one `-need`.
- [ ] **Step 6:** `git mv docs/system docs/user_guide`, move the two deployment pages, `git rm docs/requirements/queryview.md`.
- [ ] **Step 7: Rewrite references.** e2e markers `requirements/queryview/<slug>` → `user_guide/<page>/<slug>` and `system/` → `user_guide/`; all `docs/system/`, `../system/`, `../requirements/`, `docs/docker.md` paths. Run the grep → only `decisions.md` hits remain.
- [ ] **Step 8: Instructions and index.**
  - `.claude/skills/vmodel/SKILL.md`: replace the layer table with the spec's "Layers" table; delete the mapping paragraph and "Tests on two layers"; add "Architecture and designs share tests: a test may name IDs from both."; examples use `user_guide/`.
  - `docs/AGENTS.md`: the three folders with one line each (spec "Goals"); a guide page joins `README.md`, any other page joins `CONTRIBUTING.md`.
  - `README.md` "Documentation": one "User guide" list (former System list plus the two deployment pages); drop the Requirements, Architecture and Deployment headings.
  - `CONTRIBUTING.md`: its tree comment names `user_guide, architecture, designs`; add a "Design docs" list of the `architecture/` pages.
- [ ] **Step 9:** Run every Global Constraints check, plus `npm run build:e2e && npm run e2e -- e2e/acceptance.spec.ts --trace off` (markers only changed; the `claudeai-run` skill starts the databases) → all pass.
- [ ] **Step 10:** Commit `Docs: user guide layer replaces requirements and system`.

### Task 2: Decisions become `## Why` sections

**Files:**
- Delete: `docs/architecture/decisions.md`
- Modify: `docs/architecture/mcp.md`, `docs/architecture/api.md`, `docs/architecture/viewer_server_api.md`, `scripts/vmodel_check.py`, `scripts/test_vmodel_check.py`, `.claude/skills/vmodel/SKILL.md`, `CONTRIBUTING.md`

- [ ] **Step 1:** Replace `test_a_decisions_page_needs_no_id` with `test_a_decisions_page_is_an_untagged_page`: `docs/architecture/decisions.md` with no marker → its path is in `gaps`. Run → FAIL.
- [ ] **Step 2:** Drop the `decisions.md` exemption in `_definitions`. Run → PASS.
- [ ] **Step 3:** Move "Why a param value is matched as the page's text" to a `## Why a param value is matched as the page's text` section in `architecture/mcp.md` before `## Related docs`; the `run_dashboard` entry links `#why-a-param-value-is-matched-as-the-pages-text`; `api.md` (`/api/runqueries` row) and `viewer_server_api.md` (the selectors paragraph) link to it. `git rm` `decisions.md`; drop it from `CONTRIBUTING.md` and the project skill's "Every file is tagged" exceptions.
- [ ] **Step 4:** Run every Global Constraints check (grep now with no `decisions.md` allowance) → clean.
- [ ] **Step 5:** Commit `Docs: decisions as ## Why sections`.

### Task 3: Split `architecture/` into `architecture/` and `designs/`

**Files:**
- Move: `docs/architecture/sessions.md` → `docs/designs/sessions.md`
- Create: `docs/designs/dashboards.md`, `docs/designs/mcp.md`, `docs/contributor.md` (CI, no layer)
- Modify: `docs/architecture/dashboards.md` (removed after its last section folds), `docs/architecture/mcp.md`, `docs/architecture/overview.md`, `docs/architecture/storage.md`, tests naming moved IDs, code comments linking moved headings, `CONTRIBUTING.md`

- [ ] **Step 1:** Move sections per the spec's Step 2 list: `sessions.md` whole; `dashboards.md` "Running the queries: `/api/runqueries`" and "Which connection, which database" → `designs/dashboards.md`; "Isolation & security" → a section of `architecture/overview.md`; `mcp.md` "Federated drafts" and "How it works" → `designs/mcp.md`; `storage.md` "CI" → `docs/contributor.md`. Each new page opens with one line on what it covers and ends with `## Related docs`.
- [ ] **Step 2:** Rewrite moved IDs' markers `architecture/<page>/<slug>` → `designs/<page>/<slug>` in tests (`runqueries`, `fail-fast`, `named-connection` under dashboards; the sessions IDs; any mcp IDs in the moved sections) and every link to moved headings.
- [ ] **Step 3:** `CONTRIBUTING.md` lists the `designs/` pages and `contributor.md`.
- [ ] **Step 4:** Run every Global Constraints check → clean.
- [ ] **Step 5:** Commit `Docs: designs layer splits from architecture`.

### Task 4: Move non-guide sections out of `user_guide/`

**Files:**
- Modify: `docs/user_guide/{connect,session,mcp,dashboard,query,scripts,gitsync,workspace,export-import}.md`, the `architecture/` and `designs/` pages they merge into, code comments linking moved headings

- [ ] **Step 1:** Move per the spec's Step 3 list. `## API` sections: endpoints not already in `api.md` go there; the guide section is removed. `connect.md` "Storage & migrations", "Persistence (SQLite)", "Config encryption" merge into `architecture/storage.md`; "CI" into `docs/contributor.md`; "Flow" into a new `designs/connect.md`; `session.md` "How it is stored" into `designs/sessions.md`; `mcp.md` "How it works" into `designs/mcp.md`; `dashboard.md` "Running the queries" into `designs/dashboards.md`, "Isolation & security" into `architecture/overview.md`. Where the user sees the effect, the guide keeps one line linking down. Merge, don't duplicate: one fact, one layer.
- [ ] **Step 2:** Before deleting a heading, grep its exact text across `backend/`, `frontend/src`, `e2e/`, `docs/` and repoint each hit.
- [ ] **Step 3:** Run every Global Constraints check → clean.
- [ ] **Step 4:** Commit `Docs: user guide holds only guide content`.

### Task 5: Guide voice

**Files:**
- Modify: every `docs/user_guide/*.md`; code comments quoting renamed headings

- [ ] **Step 1:** Per page: opening paragraph says what the feature is for, names its route and links neighbouring pages; sections are tasks ("Create a connection"), each led by its statement, second person. Markers stay on the line above their statement; slugs unchanged; untagged prose gets no new ID.
- [ ] **Step 2:** Grep each renamed heading's old text and repoint hits (Task 4 Step 2 rule).
- [ ] **Step 3:** Run every Global Constraints check, plus the full browser suite `npm run e2e -- --trace off` → all pass.
- [ ] **Step 4:** Commit `Docs: user guide written as a guide`.
