# Dashboard Rename & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename and Delete saved dashboards; in a git-synced workspace a user's Save, Rename or Delete is itself one commit and push, and the separate Commit is removed.

**Architecture:** `dashboards.py` gains plain DB rename/delete. `gitsync.py` gains three user-action operations — `save`, `rename`, `delete` — that do the git side first (under the workspace lock, reset → merge → change → commit → push, retried once on a rejected push) and touch the DB only after the push succeeds; a failure resets the clone to the remote head and leaves the DB as it was. Unsynced workspaces skip git. REST routes call these; `POST /api/git/store` and MCP `git_store` go away.

**Tech Stack:** FastAPI + SQLModel (backend), git CLI via `gitsync._git`, React + TS (frontend), pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-15-dashboard-rename-delete-design.md`

## Global Constraints

- Commit messages: `store dashboard <name>`, `rename dashboard <old> → <new>`, `delete dashboard <name>`.
- Only user actions commit: `push_dashboard`, Import and Restore never commit.
- Rename to a taken name → 409. Unknown dashboard → 404.
- No MCP rename/delete tools; MCP `git_store` and `POST /api/git/store` removed.
- Run everything with `uv run` (`uv run --group test pytest backend/queryview`).
- Example data uses invented names only (`sales`, `ops overview`).
- Commit messages carry no `Co-Authored-By: Claude` trailer (AGENTS.md).

## Review Focus

- Rename when the repo already holds a folder for the new name (e.g. left by a hand edit) → 409, nothing committed, DB unchanged. Test in Task 2.
- Push refused by the remote (not a race) → error surfaced, DB unchanged, clone HEAD equals `origin/<branch>`. Test in Task 2 for each of save/rename/delete.
- Rename or delete of a dashboard never committed → DB change only, no commit, no error. Test in Task 2.
- Rename of a dashboard with an open conflict → conflict entry now names the new name. Test in Task 2.
- Rename/delete with unsaved SQL-panel edits open → rename keeps the edits under the new name; delete discards them after confirm. Covered by Task 4's e2e for rename.

---

### Task 1: DB rename and delete

**Files:**
- Modify: `backend/queryview/dashboards.py`
- Test: `backend/queryview/test_dashboards.py`

**Interfaces:**
- Produces: `async def rename_dashboard(old: str, new: str, *, workspace_id: int) -> None` — raises `KeyError` when `old` is missing, `ValueError` when `new` exists; bumps `updated_at`.
- Produces: `async def delete_dashboard(name: str, *, workspace_id: int) -> bool` — False when missing.

- [ ] **Step 1: Write failing tests**

```python
def test_rename_dashboard_moves_the_row(default_ws_id):
    _run(upsert_dashboard("sales", "<p>s</p>", {"q": "SELECT 1"}, workspace_id=default_ws_id))
    _run(rename_dashboard("sales", "sales 2026", workspace_id=default_ws_id))
    assert _run(get_dashboard("sales", default_ws_id)) is None
    assert _run(get_dashboard("sales 2026", default_ws_id))["queries"] == {"q": "SELECT 1"}

def test_rename_dashboard_to_taken_name_raises(default_ws_id):  # ValueError, both rows unchanged
def test_rename_missing_dashboard_raises(default_ws_id):          # KeyError
def test_delete_dashboard(default_ws_id):                         # True, then get is None, then delete -> False
```

- [ ] **Step 2: Run** `uv run --group test pytest backend/queryview/test_dashboards.py -k "rename or delete" -v` — FAIL (ImportError).
- [ ] **Step 3: Implement** both functions in `dashboards.py`, one `AsyncSession` each, the same `select(...).where(name, workspace_id)` lookup `get_dashboard` uses.
- [ ] **Step 4: Run** the same command — PASS.
- [ ] **Step 5: Commit** `git commit -m "Dashboards: DB rename and delete"`

### Task 2: Git-synced save / rename / delete

**Files:**
- Modify: `backend/queryview/gitsync.py` (beside `store`/`_store_once`)
- Test: `backend/queryview/test_gitsync.py`

**Interfaces:**
- Consumes: Task 1's `rename_dashboard`, `delete_dashboard`; existing `upsert_dashboard`, `get_dashboard`.
- Produces (all return `{committed: bool, sha: str | None, imported, conflicts}`, raise `GitSyncError`):
  - `async def save(ws, d: dict[str, Any]) -> dict` — `d` in `get_dashboard` shape (`name, html, queries, params`).
  - `async def rename(ws, old: str, new: str) -> dict` — `GitSyncError(status=404)` when `old` missing locally, `status=409` when `new` exists locally or `dashboard_reldir(new)` exists in the repo head.
  - `async def delete(ws, name: str) -> dict` — `GitSyncError(status=404)` when missing locally.

Each one: when `not configured(ws)`, do only the DB call and return `committed=False, sha=None, imported=[], conflicts=[]`. Otherwise, under `_lock(ws)` and via `_retry_if_rejected`: `_ensure_repo`, `_origin_head`, `reset --hard` + `_merge` (as `_store_once`), make the git change, commit with the Global Constraints message, push, then the DB call, then fix sync state. Wrap the git part in `try/except GitSyncError: reset --hard origin/<branch> (or the pre-op head); raise`.

- `save`: refactor `_store_once(ws, name, message, entity=None)` so it writes `entity` when given instead of `_load_entity`; `save` passes `d`, then `upsert_dashboard(...)` after the push. "no changes" still upserts the DB.
- `rename`: if the repo head has `dashboard_reldir(old)`, `git mv` it to `dashboard_reldir(new)` and rewrite `meta.yaml` there via `dashboard_to_files` with the repo copy's content and `name=new` (the canonical name lives in meta.yaml), commit, push. Then `rename_dashboard`. State: move `agreed[_key(old)]` → `_agree(ws, wd, "HEAD", new)`; rename a matching conflict entry's `name`.
- `delete`: if the repo head has the folder, `git rm -r` it, commit, push. Then `delete_dashboard`. State: drop `agreed[_key(name)]` and its conflict.

- [ ] **Step 1: Write failing tests** (reuse `git_env`, `_remote_log`; a refusing remote = write `git_env / "hooks" / "pre-receive"` containing `#!/bin/sh\nexit 1`, chmod 755)

```python
def test_save_commits_current_content(git_env)            # remote log has "store dashboard sales"; DB has the html
def test_save_unconfigured_only_writes_db()               # committed False, row exists
def test_save_push_refused_leaves_db_and_clone(git_env)   # GitSyncError; get_dashboard is None (or old html); clone HEAD == origin/main
def test_rename_moves_folder_in_one_commit(git_env)       # one new commit "rename dashboard sales → sales 2026"; repo has dashboards/sales 2026/meta.yaml with name: sales 2026, no dashboards/sales
def test_rename_never_committed_makes_no_commit(git_env)  # committed False; DB renamed
def test_rename_to_taken_name_is_409(git_env)             # local clash and repo-folder clash; DB unchanged
def test_rename_push_refused_rolls_back(git_env)          # DB still has old name
def test_rename_moves_conflict_and_agreement(git_env)     # conflicts() lists the new name, not the old
def test_delete_removes_folder_in_one_commit(git_env)     # "delete dashboard sales"; folder gone; row gone; a later sync() doesn't re-import
def test_delete_push_refused_keeps_row(git_env)
def test_delete_missing_is_404(git_env)
```

- [ ] **Step 2: Run** `uv run --group test pytest backend/queryview/test_gitsync.py -k "save or rename or delete" -v` — FAIL.
- [ ] **Step 3: Implement** `save`, `rename`, `delete` as above.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview/test_gitsync.py -v` — all PASS, including the existing `store` tests.
- [ ] **Step 5: Commit** `git commit -m "Git sync: Save, Rename and Delete commit in one step, rolled back on failure"`

### Task 3: REST routes; drop git_store

**Files:**
- Modify: `backend/queryview/main.py` (`dashboards_upsert` ~579, new routes after `dashboards_get`, delete `git_store` ~673), `backend/queryview/dashboards.py` (`_upsert_and_push` → persists via `gitsync.save`), `backend/queryview/mcp_server.py` (delete `git_store` ~504; fix the docstring mention ~362)
- Test: `backend/queryview/test_main.py`, `backend/queryview/test_api_gitsync.py`, `backend/queryview/test_mcp_gitsync.py`

**Interfaces:**
- Consumes: Task 2's `gitsync.save/rename/delete`.
- Produces:
  - `POST /api/dashboards` — unchanged body; now `{ok, persisted, pushed, committed, message}`; a `GitSyncError` → `_status_error(e)`.
  - `POST /api/dashboards/{name}/rename` `{new_name, workspace?}` → `{ok, committed}`; 400 when `new_name` blank, 404/409 from `GitSyncError.status`.
  - `DELETE /api/dashboards/{name}?workspace=` → `{ok, committed}`; 404 when missing.

- [ ] **Step 1: Write failing tests** in `test_main.py`: rename then GET old → 404, GET new → 200; rename blank → 400; rename onto existing → 409; DELETE → 200 then GET → 404; DELETE missing → 404. In `test_api_gitsync.py`: POST `/api/dashboards` under `git_env` → remote log has `store dashboard`; `POST /api/git/store` → 404/405. In `test_mcp_gitsync.py`: `git_store` not in the tool names; delete the `git_store` tests, keeping the `git_history`/`git_restore` ones.
- [ ] **Step 2: Run** `uv run --group test pytest backend/queryview -k "dashboards or gitsync" -v` — FAIL.
- [ ] **Step 3: Implement** the routes (reuse `_clean_str`, `_resolve_workspace`, `_read_json`, `_status_error`), change `_upsert_and_push(..., *, workspace_id)` to `_upsert_and_push(..., *, ws: WorkspaceRec)` (the record `_resolve_workspace` returns) and persist with `await gitsync.save(ws, {...})` instead of `upsert_dashboard`; delete `/api/git/store` and MCP `git_store`.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview` — all PASS.
- [ ] **Step 5: Commit** `git commit -m "API: rename and delete dashboards; Save commits; drop git_store"`

### Task 4: Frontend buttons; drop Commit

**Files:**
- Modify: `frontend/src/app/DashboardView.tsx` (toolbar ~484), `frontend/src/app/controls/GitSyncControls.tsx` (remove `commit`, the `git-commit` button and its state), `frontend/src/app/gitsync.ts` (remove `gitStore`, `GitStoreResult`)
- Test: `e2e/dashboard.spec.ts`, `e2e/workspaces.spec.ts` (lines 74–95 use `git-commit`)

**Interfaces:**
- Consumes: Task 3's routes.
- Produces: buttons `data-testid="dashboard-rename"` and `data-testid="dashboard-delete"`, after Save, disabled when `!active?.name || saving`.

Rename: `window.prompt('Rename dashboard to:', name)?.trim()`; skip if empty or unchanged; refuse locally if in `dashboards` (same message as Save's clash); POST; on success `loadDashboards()`, keep unsaved SQL-panel edits by renaming `editedRef.current`/`localPush` to the new name, `setSearchParams({ name: newName })`. Delete: `window.confirm(\`Delete dashboard “${name}”?\`)`; DELETE; on success `loadDashboards()`, `reopen(null)`, `setSearchParams({})`. Errors go to `setError` like Save.

- [ ] **Step 1: Write failing e2e tests** in `dashboard.spec.ts`: seed a dashboard; Rename → dropdown shows the new name, URL has `?name=<new>`, reload still opens it; edit SQL in the panel, Rename, the edit is still in the panel; Delete (accept dialog) → dropdown lacks it, `dashboard-empty` shows. In `workspaces.spec.ts` replace the `git-commit` checks with: Save under a configured remote succeeds and Restore lists a `store dashboard` revision.
- [ ] **Step 2: Run** `npm run build:e2e && npx playwright test e2e/dashboard.spec.ts e2e/workspaces.spec.ts --trace off` (databases up via the `claudeai-run` skill) — FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run** the same, plus `npm test -w frontend` and `npm run lint -w frontend` if defined — PASS.
- [ ] **Step 5: Commit** `git commit -m "Dashboard page: Rename and Delete; Commit folds into Save"`

### Task 5: Docs

**Files:**
- Modify: `docs/dashboard.md` (page bullets + sketch toolbar), `docs/gitsync.md` (UI, API, MCP list; add "Only a user's Save, Rename or Delete commits; agent pushes, Import and Restore never do"), `docs/api.md` (routes table, drop `/api/git/store`), `docs/mcp.md:108` (drop `git_store`), `docs/future.md` (remove the Rename and delete bullet)

- [ ] **Step 1:** Load the `docs-writing` skill, then edit.
- [ ] **Step 2: Verify** `grep -rn "git_store\|api/git/store\|git-commit" docs frontend/src backend e2e` → no hits outside `docs/superpowers/`.
- [ ] **Step 3: Commit** `git commit -m "Docs: dashboard rename/delete; only user actions commit"`
