# V-model Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every test is tied by a named ID to the doc statement it proves, in four layers (user, system, integration, unit), and a project skill walks each change down the docs and up the tests.

**Architecture:** `docs/` gets one folder per layer, so a page's path gives its layer and the prefix of its IDs. A grep-only script, `scripts/vmodel_check.py`, reads `req:` comments in docs and tests, fails on a broken tie and reports a missing one. The skill is prose that tells an agent which doc and test to write at each layer and in what order.

**Tech Stack:** Python 3.11 standard library, pytest; Markdown; Playwright for the acceptance file; pre-commit.

**Spec:** `docs/superpowers/specs/2026-11-24-vmodel-skill-design.md`. Read it first; this plan argues from it.

## Global Constraints

- Folder names are exactly `docs/requirements/` (user), `docs/system/` (system), `docs/architecture/` (integration). Pages at the root of `docs/` and everything under `docs/superpowers/` have no layer.
- An ID is the page's path under `docs/` without `.md`, a slash, and a kebab-case slug: `system/dashboard/param-rerun`. Valid IDs match `^(requirements|system|architecture)(/[a-z0-9_-]+)+$`.
- A doc defines an ID with `<!-- req: <id> -->` on the line above the statement. A test names it with `// req: <id>` or `# req: <id>` directly above the test or group. Several IDs are comma-separated.
- Proof location: a `requirements/` ID in `e2e/acceptance.spec.ts`; a `system/` ID in any other `e2e/*.spec.ts`; an `architecture/` ID in a `test_*.py` or `*.test.ts(x)` file. A marker elsewhere is support, not proof.
- The check script parses no test code and never fails on a gap unless `--strict` is passed.
- A docs section moves with `git mv` or cut and paste; it is never copied. The page it left links to its new home.
- No test file is renamed or moved, except tests that move into `e2e/acceptance.spec.ts`.
- Repo rules: `uv run`, imports at file top, no `__all__`, invented example names only, no AI attribution in commits. Load the project `testing` skill before adding a test and `docs-writing` before editing docs; finish each docs edit with `devpowers:shortify`.
- e2e needs the databases up; in the Claude Code web container the `claudeai-run` skill starts them.

## Link check

Tasks 2 and 3 move pages; this throwaway command proves no link broke. Run it from the repo root. It passes when it prints `links ok`.

```bash
uv run python - <<'EOF'
import pathlib
import re
import subprocess

root = pathlib.Path.cwd()
files = [pathlib.Path(f) for f in subprocess.check_output(["git", "ls-files"], text=True).split("\n") if f]


def slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(page: pathlib.Path) -> set[str]:
    return {slug(line.lstrip("#")) for line in page.read_text().splitlines() if line.startswith("#")}


bad = []
for f in files:
    if f.suffix not in {".md", ".py", ".ts", ".tsx"} or str(f).startswith("docs/superpowers/") or not f.exists():
        continue
    text = f.read_text(errors="replace")
    refs = []
    if f.suffix == ".md":
        for target, anchor in re.findall(r"\]\((?!https?:)([^)#\s]*\.md)?(#[^)\s]+)?\)", text):
            refs.append(((f.parent / target).resolve() if target else f.resolve(), anchor))
    if not str(f).startswith("docs/"):
        for target, anchor in re.findall(r"(?<![\w/.])(docs/[\w/.-]+\.md)(#[\w-]+)?", text):
            refs.append(((root / target).resolve(), anchor))
    for page, anchor in refs:
        if not page.exists():
            bad.append(f"{f}: no page {page.relative_to(root)}")
        elif anchor and anchor[1:] not in anchors(page):
            bad.append(f"{f}: no heading {anchor} in {page.relative_to(root)}")
print("\n".join(sorted(set(bad))) or "links ok")
EOF
```

Before any change it prints one line, a dead anchor that predates this work; Task 2 fixes it:

```
backend/queryview/migrations/versions/c5d6e7f8a9b0_agent_session.py: no heading #the-agent-session in docs/session.md
```

It does not see a heading quoted as text (`See docs/session.md, "How it is stored"`). For each heading a task moves, also run `git grep -n "<heading text>" -- backend frontend e2e` and update the hits.

## Review Focus

1. **A `req:` comment shown inside a fenced code block of a layer page** (a page that explains the marker) defines no ID. Test in Task 1.
2. **A file in a test tree that is not valid UTF-8** does not crash the script. Test in Task 1.
3. **The repo as it is today**, with no layer folders and no markers, exits 0. Test in Task 1.
4. **A marker whose text is not a valid ID** (`// req: Dashboard Params`, `# req: dashboard/x`) is an error, not silently skipped. Test in Task 1.
5. **A backend test that names only a `system/` ID** stays a unit file and proves nothing: the ID still fails for lack of a browser test. Test in Task 1.

---

### Task 1: The check script

**Files:**
- Create: `scripts/vmodel_check.py`
- Test: `scripts/test_vmodel_check.py`
- Modify: `pyproject.toml` (`testpaths = ["backend/queryview", "scripts"]`)
- Modify: `.github/workflows/ci.yml` (`test-backend` runs `uv run --frozen pytest backend/queryview scripts`)
- Modify: `CONTRIBUTING.md:86` (same command)
- Modify: `.pre-commit-config.yaml` (local hook)

**Interfaces:**
- Produces, in `scripts/vmodel_check.py`:

```python
LAYER_DIRS = {"requirements": "user", "system": "system", "architecture": "integration"}

@dataclass
class Report:
    errors: list[str]
    gaps: list[str]
    matrix: dict[str, dict[str, list[str]]]  # layer -> ID -> test files naming it, repo-relative

def parse_ids(line: str) -> list[str]       # IDs of one line's req: comment; [] when it has none
def check(root: Path) -> Report
def main(argv: list[str] | None = None) -> int   # 0, or 1 on errors, or 1 on gaps with --strict
```

- CLI: `uv run python scripts/vmodel_check.py [--strict]` prints the matrix, then errors, then gaps.

- [ ] **Step 1: Write the failing tests**

A `repo(tmp_path, files: dict[str, str]) -> Path` helper writes each path. Shared snippets: `PAGE = "<!-- req: system/dash/rerun -->\nA param change re-runs.\n"`, `SPEC = "// req: system/dash/rerun\ntest('x', () => {})\n"`.

```python
def test_parse_ids():
    assert parse_ids("<!-- req: system/a/x, system/a/y -->") == ["system/a/x", "system/a/y"]
    assert parse_ids("  // req: system/a/x") == ["system/a/x"]
    assert parse_ids("# req: architecture/b/z") == ["architecture/b/z"]
    assert parse_ids("# required: nothing") == []

def test_tied_repo_is_clean(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": PAGE, "e2e/dash.spec.ts": SPEC}))
    assert r.errors == [] and r.matrix["system"] == {"system/dash/rerun": ["e2e/dash.spec.ts"]}

def test_duplicate_id(tmp_path):            # PAGE twice in one page -> "defined twice" in an error
def test_unknown_id_in_test(tmp_path):      # SPEC alone -> "no doc defines" in an error
def test_prefix_must_match_page(tmp_path):  # PAGE saved as docs/system/other.md -> "prefix" in an error
def test_malformed_marker(tmp_path):        # "// req: Dashboard Params" and "# req: dashboard/x" -> one error each
def test_fenced_marker_defines_nothing(tmp_path):   # PAGE inside ``` fences -> no error, empty matrix
def test_non_utf8_file_does_not_crash(tmp_path):    # e2e/bad.spec.ts written as b"\xff\xfe" -> check() returns

def test_system_id_needs_a_browser_test(tmp_path):
    r = check(repo(tmp_path, {"docs/system/dash.md": PAGE,
                              "backend/queryview/dash.py": '"""Doc."""\n',
                              "backend/queryview/test_dash.py": "# req: system/dash/rerun\n"}))
    assert any("no test in e2e/" in e for e in r.errors)

def test_layer_proof_locations(tmp_path):
    # requirements/ ID named only in e2e/dash.spec.ts -> error; named in e2e/acceptance.spec.ts -> clean.
    # architecture/ ID named in backend/queryview/test_api_db.py -> clean, and that file is not a gap.
    # architecture/ ID named in frontend/src/core/x.test.ts -> clean.

def test_unit_file_pairs_by_name(tmp_path):
    # test_sessions.py beside sessions.py with a docstring -> no error, no gap.
    # sessions.py without a docstring -> error naming sessions.py.
    # rows.test.ts beside rows.tsx whose first line is a comment -> clean; without it -> error.
    # test_api_db.py with no marker and no api_db.py -> a gap, not an error.

def test_gaps(tmp_path):
    # docs/system/empty.md with no marker -> gap; e2e/x.spec.ts with no marker -> gap.
    # docs/future.md and docs/superpowers/specs/x.md with any text -> neither gap nor error.

def test_untagged_repo_exits_zero(tmp_path, capsys):
    root = repo(tmp_path, {"docs/dashboard.md": "text\n", "e2e/app.spec.ts": "test('x', () => {})\n"})
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--strict"]) == 1
```

Write a body for every commented test from its comment.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --group test pytest scripts -q`
Expected: collection error, `No module named 'vmodel_check'`.

- [ ] **Step 3: Implement `scripts/vmodel_check.py`**

Standard library only, with a module docstring that names the spec's successor, `.claude/skills/vmodel/SKILL.md`. `main` takes `--root` (default: the repo root, the parent of `scripts/`) and `--strict`. Walk `docs/requirements`, `docs/system`, `docs/architecture` for definitions, skipping fenced blocks. Test files are `e2e/*.spec.ts`, `test_*.py` under `backend/queryview` and `scripts`, and `*.test.ts`/`*.test.tsx` under `frontend/src`. Read every file with `errors="replace"`. A Python module's docstring is checked with `ast.get_docstring`; a TypeScript module passes when its first non-blank line starts with `//` or `/*`.

- [ ] **Step 4: Run the tests and the script**

Run: `uv run --group test pytest scripts -q` and `uv run python scripts/vmodel_check.py`
Expected: all pass; the script exits 0 and lists every current test file that has no paired module as a gap.

- [ ] **Step 5: Wire the hook and CI**

Add to the `local` repo in `.pre-commit-config.yaml`:

```yaml
      - id: vmodel-check
        name: vmodel check
        language: system
        entry: uv run python scripts/vmodel_check.py
        pass_filenames: false
        always_run: true
```

Run: `uv run pre-commit run vmodel-check --all-files`
Expected: `Passed`.

- [ ] **Step 6: Commit**

```bash
git add scripts pyproject.toml .pre-commit-config.yaml .github/workflows/ci.yml CONTRIBUTING.md
git commit -m "Add vmodel_check: ties tests to doc statements by req: IDs"
```

### Task 2: Move the pages into layer folders

**Files:**
- Move to `docs/system/`: `connect.md`, `creds.md`, `dashboard.md`, `explorer.md`, `export-import.md`, `gitsync.md`, `mcp.md`, `query.md`, `queryview.md`, `scripts.md`, `session.md`, `workspace.md`
- Move: `docs/viewer_server/README.md` to `docs/system/viewer_server.md`
- Move: `docs/api.md` to `docs/architecture/api.md`; `docs/viewer_server/api.md` to `docs/architecture/viewer_server_api.md`
- Move: `docs/viewer_server/docker.md` to `docs/viewer_server_docker.md`
- Stay: `docs/AGENTS.md`, `docs/future.md`, `docs/docker.md`
- Modify: every file that links a moved page (about 200 links in `docs/`, about 100 references in 50 files outside it), `README.md` docs list, `docs/AGENTS.md`, `.claude/skills/docs-writing/SKILL.md`, `CONTRIBUTING.md:15`

**Interfaces:**
- Produces: the page paths above, which Tasks 3 to 6 edit and which fix the ID prefixes (`system/dashboard/…`, `architecture/api/…`).

- [ ] **Step 1: Move the files with `git mv`** as listed. `docs/viewer_server/` no longer exists afterwards.

- [ ] **Step 2: Rewrite the links.** Relative links inside `docs/`, `docs/<page>.md` references in code comments and docstrings, and `README.md`. Regroup the README docs list under three headings: Requirements, System, Architecture; pages with no layer go last. Point the migration comment's `#the-agent-session` at `docs/system/session.md#sessions-and-the-agent`.

- [ ] **Step 3: Rewrite the docs rules.** In `docs/AGENTS.md` and `.claude/skills/docs-writing/SKILL.md`, replace "one page per feature" and the `docs/viewer_server/` rule with:
  - `docs/requirements/`: what a user needs; no design, no screen detail.
  - `docs/system/`: one page per feature, what a user can see or do.
  - `docs/architecture/`: components, contracts between them, storage, interface references.
  - A page holds one layer's content. A statement a test proves carries a `<!-- req: <id> -->` comment on the line above it; the project `vmodel` skill says how.
  - The `## API` rule points at `docs/architecture/api.md`.

- [ ] **Step 4: Verify**

Run: the [Link check](#link-check), `uv run python scripts/vmodel_check.py`, `uv run --group test pytest backend/queryview -q`, `npm test -w frontend`
Expected: `links ok`; exit 0; all tests pass (comments only changed).

- [ ] **Step 5: Commit**

```bash
git add -A docs README.md CONTRIBUTING.md .claude backend frontend e2e
git commit -m "Docs: one folder per V-model layer"
```

### Task 3: Slice the mixed pages

**Files:**
- Create: `docs/architecture/storage.md`, `sessions.md`, `mcp.md`, `dashboards.md`, `decisions.md`
- Modify: `docs/system/connect.md`, `session.md`, `mcp.md`, `dashboard.md`, `creds.md`, `explorer.md`, `README.md` docs list, and code comments that quote a moved heading

**Interfaces:**
- Consumes: the page paths of Task 2.
- Produces: the architecture pages Task 5 links from the overview.

| Section, cut from `docs/system/` | Pasted into `docs/architecture/` |
|---|---|
| `connect.md`: "Storage & migrations", "Persistence (SQLite)", "Config encryption", "CI" | `storage.md` |
| `session.md`: "How it is stored" | `sessions.md` |
| `mcp.md`: "Tools", "How it works" | `mcp.md` |
| `dashboard.md`: "Running the queries: `/api/runqueries`", "Isolation & security" | `dashboards.md` |
| `creds.md`: "Design decisions"; `explorer.md`: "Why folder mode lists one level at a time" | `decisions.md` |

- [ ] **Step 1: Create each architecture page** in the house style: a title, one opening sentence that links the system page it came from, the moved sections unchanged, `## Related docs`.

- [ ] **Step 2: Replace each cut section** on its system page with one sentence linking the new page. If a remaining section still explains storage, an endpoint body or another mechanism a user cannot see, move it the same way and add the row to the commit message.

- [ ] **Step 3: Update the quoted headings.** For each moved heading run `git grep -n "<heading text>" -- backend frontend e2e` and repoint the hit, for example `backend/queryview/sessions.py:41` to `docs/architecture/sessions.md, "How it is stored"`.

- [ ] **Step 4: Verify**

Run: the [Link check](#link-check) and `uv run python scripts/vmodel_check.py`
Expected: `links ok`; exit 0.

- [ ] **Step 5: Commit**

```bash
git add -A docs README.md backend frontend e2e
git commit -m "Docs: move how-it-is-built sections to docs/architecture"
```

### Task 4: User requirements and the acceptance file

**Files:**
- Create: `docs/requirements/queryview.md`
- Create: `e2e/acceptance.spec.ts`
- Modify: `docs/system/queryview.md` (its "Design principles" section moves into the new page), the `e2e/*.spec.ts` files a test leaves, `e2e/fixtures.ts` (a helper a moved test shares with tests that stay), `README.md` docs list

**Interfaces:**
- Produces: the nine IDs below; Task 6's skill cites `requirements/queryview/run-sql` as its example.

| ID `requirements/queryview/…` | The user can | Start from this test |
|---|---|---|
| `add-connection` | save a connection to a ClickHouse, Postgres, MySQL, DuckDB or SQLite database | `app.spec.ts` "queryview e2e" |
| `open-database` | open a saved connection, pick a database, and find it reconnected next time | `app.spec.ts` "queryview e2e" (one test, both IDs) |
| `run-sql` | run SQL, page through the rows, pick columns, download CSV | `drivers.spec.ts` "connect, query, paginate, csv" |
| `run-script` | run a multi-statement script, writes included, that stops at the first error | `scripts.spec.ts` "run all writes and shows the last select" |
| `browse-tables` | browse tables and page through rows without typing SQL | `explorer.spec.ts` "explorer browse, order, fields, paginate" |
| `live-dashboard` | open a saved dashboard that re-runs its queries against live data | `dashboard.spec.ts` "dashboard push and reopen" |
| `workspace-git` | back a workspace up to a git remote and restore a dashboard from it | `workspaces.spec.ts` "git save and restore dashboard round trip" |
| `yaml-export-import` | move a dashboard between instances as YAML | `workspaces.spec.ts` "dashboard export import round trip" |
| `agent-drives` | have an agent run a query in the user's open tab over MCP | `remote.spec.ts` "mcp push_script fills and runs the scripts editor" |

- [ ] **Step 1: Write `docs/requirements/queryview.md`.** One `##` section per row: the `<!-- req: … -->` comment, the statement "A user can …", a short list of acceptance criteria taken from what the start-from test asserts, and a link to the system page. Then the moved "Design principles" section, untagged. End with `## Related docs`.

- [ ] **Step 2: Run the check to see it fail**

Run: `uv run python scripts/vmodel_check.py`
Expected: exit 1, nine errors `no test in e2e/acceptance.spec.ts`.

- [ ] **Step 3: Build `e2e/acceptance.spec.ts`.** Move each start-from test, with `// req: <id>` above it. Move a test only when its body covers every acceptance criterion; otherwise write a new test from `e2e/fixtures.ts` helpers and leave the old one. A file-local helper that a staying test also uses moves to `e2e/fixtures.ts`.

- [ ] **Step 4: Verify**

Run: `uv run python scripts/vmodel_check.py`, then `npm run build:e2e -w frontend && npx playwright test e2e/acceptance.spec.ts --trace off`, then `npx playwright test --trace off`
Expected: exit 0 with nine IDs under `user` in the matrix; the acceptance file passes; the whole suite passes with the same test count as before plus any new tests.

- [ ] **Step 5: Commit**

```bash
git add docs e2e README.md
git commit -m "Add user requirements and their acceptance tests"
```

### Task 5: Architecture overview and its integration tests

**Files:**
- Create: `docs/architecture/overview.md`
- Modify: the seven backend test files below (one comment each), `README.md` docs list

**Interfaces:**
- Consumes: the architecture pages of Tasks 2 and 3.
- Produces: seven `architecture/overview/…` IDs.

| ID `architecture/overview/…` | Contract | Proved by, in `backend/queryview/` |
|---|---|---|
| `session-scoped-api` | a data request names a session; the backend takes the connection and database from that session's row | `test_session_api.py` |
| `driver-contract` | every driver answers the shared operations the same way | `drivers/test_contract.py` |
| `mcp-mount` | the MCP server is mounted at `/mcp/` in the same app | `test_mcp_mount.py` |
| `remote-channel` | an agent push reaches the tab through that session's channel | `test_remote.py` |
| `locked-refuses-both` | a locked connection refuses MCP tools and REST calls alike | `test_locked_connections.py` |
| `data-dir` | all state lives under `DATA_DIR` | `test_data_dir.py` |
| `static-spa` | the backend serves the built SPA beside `/api` | `test_static.py` |

- [ ] **Step 1: Write `docs/architecture/overview.md`.** A component sketch (the `devpowers:ascii-sketch` skill) of SPA, FastAPI app, session store, drivers, MCP server, remote channel, git sync and viewer server. Then one tagged statement per row. Read the proving file first and word the statement to what it asserts; the slug does not change. A contract another architecture page states is a link, with no ID here.

- [ ] **Step 2: Run the check to see it fail**

Run: `uv run python scripts/vmodel_check.py`
Expected: exit 1, seven errors naming the IDs.

- [ ] **Step 3: Add `# req: architecture/overview/<slug>`** at the top of each proving file, under its docstring.

- [ ] **Step 4: Verify**

Run: `uv run python scripts/vmodel_check.py` and `uv run --group test pytest backend/queryview -q`
Expected: exit 0, seven IDs under `integration`, and none of the seven files listed as a gap; tests pass.

- [ ] **Step 5: Commit**

```bash
git add docs backend README.md
git commit -m "Add the architecture overview and tie its integration tests"
```

### Task 6: The skill and the rule files

**Files:**
- Create: `.claude/skills/vmodel/SKILL.md`
- Modify: `.claude/skills/testing/SKILL.md`, `AGENTS.md`
- Delete: `docs/superpowers/specs/2026-11-24-vmodel-skill-design.md`, `docs/superpowers/plans/2026-11-24-vmodel-skill.md`

**Interfaces:**
- Consumes: the folders, the marker syntax, `scripts/vmodel_check.py`, `requirements/queryview/run-sql`.

- [ ] **Step 1: Load `superpowers:writing-skills`** and follow it, including its baseline test: give a fresh subagent a small behavior change in this repo without the skill and note which layers and markers it skips.

- [ ] **Step 2: Write `.claude/skills/vmodel/SKILL.md`.**
  - Frontmatter: `name: vmodel`; `description: Use when a change alters behavior in this repo, before writing its doc, test or code — walks the change down the docs and up the tests so every test names the doc statement it proves.`
  - The four-layer table from the spec's Intent section, with the proof location of each.
  - The marker syntax, with one doc example and one test example.
  - The five steps from the spec's "The skill" section, each as an imperative: enter at the highest layer touched; go down writing statement, ID and failing test per layer, saying in one line which layers are skipped; build; go up; a failure goes to its paired doc first.
  - Going up, in this order: the unit files touched, the integration files touched, `uv run --group test pytest backend/queryview scripts`, `npm test -w frontend`, the touched `e2e/<feature>.spec.ts`, `e2e/acceptance.spec.ts`, then `uv run python scripts/vmodel_check.py`.
  - Tagging on touch: an untagged statement or test file the change edits gets its ID in the same change.
  - What it does not cover: a pure refactor, a comment, a docs wording fix. It points at `testing` and `docs-writing` and repeats neither.

- [ ] **Step 3: Update `.claude/skills/testing/SKILL.md`.** Replace the three-layer table with:

| Layer | Tests | Lives | Proves |
|---|---|---|---|
| Unit | one module's logic | beside the module, named after it | the module's docstring |
| Integration | routes, stores, MCP tools, drivers working together | `backend/queryview/test_*.py`, `frontend/src/**/*.test.ts`, naming an `architecture/` ID | `docs/architecture/` |
| System | one feature through the browser | `e2e/<feature>.spec.ts` | `docs/system/` |
| User | a user requirement end to end | `e2e/acceptance.spec.ts` | `docs/requirements/` |

Keep the Run commands and the Backend and e2e sections. Add one line: the `vmodel` skill says which layers a change needs.

- [ ] **Step 4: Add to root `AGENTS.md` under "Tests":** `Before a change that alters behavior, load the project `vmodel` skill: it ties each test to the doc statement it proves.`

- [ ] **Step 5: Re-run the baseline scenario with the skill** and confirm the subagent names the entry layer, writes the tagged statement and failing test at each layer, and ends on the check script.

- [ ] **Step 6: Verify the whole branch**

Run: `uv run pre-commit run --all-files`, `uv run --group test pytest backend/queryview scripts -q`, `npm test -w frontend`, `npx playwright test --trace off`
Expected: all pass.

- [ ] **Step 7: Delete the spec and this plan, then commit**

```bash
git rm docs/superpowers/specs/2026-11-24-vmodel-skill-design.md docs/superpowers/plans/2026-11-24-vmodel-skill.md
git add .claude AGENTS.md
git commit -m "Add the vmodel skill and the four-layer test rules"
```
