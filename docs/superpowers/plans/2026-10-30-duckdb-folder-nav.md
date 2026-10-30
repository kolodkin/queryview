# DuckDB Folder Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A DuckDB connection whose `path` is a directory gets a database picker (folders) and an Explorer table list (data files and `*.ext` globs), with a **Union by name** checkbox.

**Architecture:** The DuckDB driver gains a *folder mode* decided per call by `os.path.isdir(config.path)`: `list_databases` walks the root for relative folder paths (`.` first), `list_tables` lists a folder's data files with ready `read_*` queries, and every connection opens `:memory:` with `file_search_path` set to the selected folder. The session layer carries the root and defaults the selection to `.`, so the existing pill/picker/gate/Explorer work unchanged; the frontend only filters the folder list to one level at a time and adds the checkbox.

**Tech Stack:** Python 3 / FastAPI / `duckdb` (backend, `uv run`), React + TypeScript (frontend, vitest), Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-10-30-duckdb-folder-nav-design.md`

## Global Constraints

- Follow the root `AGENTS.md`: `uv run`, no `__all__`, invented names only in tests, no AI attribution trailers in commits.
- Folder paths are relative POSIX paths; the root is `"."`. Hidden entries (leading `.`) and symlinks (dirs and files) are skipped. Walk depth cap: `FOLDER_DEPTH = 4`.
- Readers: `.parquet` → `read_parquet`; `.csv`, `.tsv` → `read_csv`; `.json`, `.jsonl`, `.ndjson` → `read_json`; each non-parquet one also with a `.gz` or `.zst` suffix.
- A table entry is `{"name", "rows", "bytes", "query"}`; `rows` is `None` in folder mode; glob entries exist only for an extension with 2+ files and come after the files.
- File names go into SQL as single-quoted literals with `'` doubled. `union_by_name = true` is added only to glob queries, only when `union` is on.
- File mode (`:memory:` or a file path) behaves exactly as today.

## Review Focus

- A root containing only files and no subfolders: the picker must still show the full path and no `..`, and the Explorer must list the files (Task 4, 5).
- A folder whose only data files are compressed (`a.csv.gz`, `b.csv.gz`): two entries plus a `*.csv.gz` glob, each query opening (Task 2).
- A file name with a quote, e.g. `o'neil.csv`: the query must still parse (Task 2).
- The remembered folder of a restarted session no longer exists: rebuild falls back to `.` rather than null (Task 3).
- Switching the Union checkbox while a glob entry is selected: the rows reload with the new query (Task 6, via the existing `selected` effect; e2e in Task 7).

---

### Task 1: Folder mode detection and folder listing

**Files:**
- Modify: `backend/queryview/drivers/base.py` (`DatabasesResult`)
- Modify: `backend/queryview/drivers/duckdb.py`
- Test: `backend/queryview/drivers/test_duckdb.py`

**Interfaces:**
- Produces: `DatabasesResult(databases: list[str], root: str | None = None)` (new defaulted field on the existing frozen dataclass).
- Produces in `duckdb.py`: `FOLDER_DEPTH = 4`; `_is_folder(path: str) -> bool`; `_list_folders(root: str) -> list[str]`.
- `DuckDBDriver.list_databases` returns `DatabasesResult(folders, root=os.path.abspath(path))` in folder mode, `DatabasesResult([])` otherwise. `DuckDBDriver.test` succeeds on a directory.

- [ ] **Step 1: Write the failing tests** in `test_duckdb.py` (add a `folder` fixture building, under `tmp_path`, `items.csv`, `extra.csv`, `sub/nested.csv.gz`, `sub/deep1/deep2/deep3/deep4/x.csv`, `.hidden/h.csv`, and a symlink `link -> sub`):

```python
def test_list_databases_in_folder_mode_lists_root_and_subfolders(folder):
    r = _run(DuckDBDriver().list_databases(DuckConfig(folder)))
    assert r.root == folder
    assert r.databases == [".", "sub", "sub/deep1", "sub/deep1/deep2", "sub/deep1/deep2/deep3"]
    # .hidden and the symlink are absent; deep4 is past FOLDER_DEPTH

def test_test_connection_succeeds_on_a_folder(folder):
    assert _run(DuckDBDriver().test(DuckConfig(folder)))["ok"] is True
```

Keep `test_list_databases_is_empty` for file mode.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --group test pytest backend/queryview/drivers/test_duckdb.py -k "folder" -v`
Expected: FAIL (`root` attribute missing / wrong list / `duckdb.connect` IOException on a directory).

- [ ] **Step 3: Implement** `root` on `DatabasesResult`; `_is_folder`, `_list_folders` (`os.walk(root, followlinks=False)`, prune `dirs` in place of hidden names and `os.path.islink`, stop at `FOLDER_DEPTH` levels, sort, `"."` first, `posixpath` separators) with the comment `# shortcut: depth capped, upgrade to lazy per-folder listing if roots get deep`; `list_databases` and `test` folder branches (`test` checks `os.access(path, os.R_OK)` and runs `SELECT 1` on `:memory:`).

- [ ] **Step 4: Run the DuckDB tests**

Run: `uv run --group test pytest backend/queryview/drivers -v`
Expected: PASS, including the contract tests.

- [ ] **Step 5: Commit** `feat(duckdb): list folders as databases in folder mode`

### Task 2: Folder tables and folder-scoped queries

**Files:**
- Modify: `backend/queryview/drivers/duckdb.py`
- Test: `backend/queryview/drivers/test_duckdb.py`

**Interfaces:**
- Produces: `_open(path: str, database: str | None, read_only: bool = True)`; every call site passes `config.path, database`. In folder mode it opens `:memory:` and runs `SET file_search_path = '<root>/<database or .>'`.
- Produces: `_data_ext(name: str) -> str | None` (full extension such as `.csv.gz`, else `None`), `_read_query(name: str, union: bool) -> str`, `_list_files(folder: str, union: bool) -> list[dict[str, Any]]`.
- Produces: `DuckDBDriver.list_tables(config, database, union: bool = False)`.

- [ ] **Step 1: Write the failing tests** (reuse the `folder` fixture; `items.csv` holds `id,name` rows `1,alpha` `2,beta` `3,gamma`, `extra.csv` one row `4,delta`; add `o'neil.csv` with one row):

```python
def test_list_tables_in_folder_mode_lists_files_and_globs(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), "."))
    names = [t["name"] for t in r.tables]
    assert names == ["extra.csv", "items.csv", "o'neil.csv", "*.csv"]
    items = next(t for t in r.tables if t["name"] == "items.csv")
    assert items["rows"] is None and items["bytes"] == os.path.getsize(os.path.join(folder, "items.csv"))
    assert items["query"] == "SELECT * FROM read_csv('items.csv')"
    glob = r.tables[-1]
    assert glob["query"] == "SELECT * FROM read_csv('*.csv')"
    assert glob["bytes"] == sum(t["bytes"] for t in r.tables[:-1])
    assert next(t for t in r.tables if t["name"] == "o'neil.csv")["query"] == "SELECT * FROM read_csv('o''neil.csv')"

def test_list_tables_union_flag_only_changes_globs(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), ".", union=True))
    assert r.tables[-1]["query"] == "SELECT * FROM read_csv('*.csv', union_by_name = true)"
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('extra.csv')"

def test_list_tables_recognizes_compressed_files_in_a_subfolder(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), "sub"))
    assert [t["name"] for t in r.tables] == ["nested.csv.gz"]
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('nested.csv.gz')"

def test_folder_queries_resolve_relative_to_the_selected_folder(folder):
    d = DuckDBDriver()
    r = _run(d.run_query(DuckConfig(folder), "SELECT * FROM read_csv('items.csv')", ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
    assert r.rows.data == [[1, "alpha"], [2, "beta"], [3, "gamma"]]
    r = _run(d.run_query(DuckConfig(folder), "SELECT count(*) AS n FROM read_csv('nested.csv.gz')", "sub", 10, 0, None))
    assert isinstance(r, RowsResult)
    r = _run(d.run_query(DuckConfig(folder), "SELECT count(*) AS n FROM read_csv('*.csv', union_by_name = true)", ".", 10, 0, None))
    assert r.rows.data == [[5]]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run --group test pytest backend/queryview/drivers/test_duckdb.py -k "folder or union or compressed" -v`
Expected: FAIL (`union` unexpected kwarg; file-mode `SHOW TABLES` on a directory raises).

- [ ] **Step 3: Implement** `_open` (folder branch; quote the folder path with `'` doubled), `_data_ext`, `_read_query`, `_list_files` (`os.scandir`, regular non-symlink non-hidden files, sorted by name; glob bytes summed), and the `list_tables` folder branch; thread `database` into every `_open` call (`run_query`, `run_sql`, `export_csv`, `describe_query`, `execute_script`, `test`).

- [ ] **Step 4: Run all backend tests**

Run: `uv run --group test pytest backend/queryview -q`
Expected: PASS.

- [ ] **Step 5: Commit** `feat(duckdb): browse a folder's data files as tables`

### Task 3: Session layer: root, default folder, union parameter

**Files:**
- Modify: `backend/queryview/drivers/base.py` (`Driver.list_tables` signature), `backend/queryview/drivers/clickhouse.py`, `backend/queryview/drivers/postgres.py` (accept and ignore `union`)
- Modify: `backend/queryview/connect.py`, `backend/queryview/main.py`
- Test: `backend/queryview/drivers/test_contract.py`, `backend/queryview/test_api_db.py`

**Interfaces:**
- Consumes: `DatabasesResult.root`, `DuckDBDriver.list_tables(..., union)` from Tasks 1–2.
- Produces: `Driver.list_tables(self, config, database, union: bool = False)`; `_SessionState.root: str | None = None`; `_list_databases(...) -> tuple[DatabasesResult | None, str | None]`; `connect.list_tables(sid: str, union: bool = False)`; `GET /api/db/tables?union=1`.
- Responses: `/api/session`, `/api/db/connect`, `/api/db/open` include `root` (only when not None) and `database` (`connect_new` adds it).

- [ ] **Step 1: Write the failing tests**

In `test_contract.py`:

```python
@pytest.mark.parametrize("type_", ALL)
def test_list_tables_accepts_union_flag(type_):
    assert "union" in inspect.signature(DRIVERS[type_].list_tables).parameters
```

In `test_api_db.py` (build a folder under `tmp_path` with `a.csv`, `b.csv`, `sub/c.csv`):

```python
def test_folder_connection_lands_on_root_with_tables_and_union(tmp_path):
    c = TestClient(app, headers={"X-QV-Session": "folder-test"})
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": "folder-duck", "path": str(tmp_path)}).json()
    assert r["ok"] and r["databases"] == [".", "sub"] and r["database"] == "." and r["root"] == str(tmp_path)
    assert c.get("/api/session").json()["root"] == str(tmp_path)
    names = [t["name"] for t in c.get("/api/db/tables").json()["tables"]]
    assert names == ["a.csv", "b.csv", "*.csv"]
    glob = c.get("/api/db/tables", params={"union": "1"}).json()["tables"][-1]
    assert glob["query"] == "SELECT * FROM read_csv('*.csv', union_by_name = true)"
    assert c.post("/api/db/database", json={"database": "sub"}).json()["ok"]
    assert [t["name"] for t in c.get("/api/db/tables").json()["tables"]] == ["c.csv"]
    r = c.post("/api/db/open", json={"name": "folder-duck"}).json()
    assert r["database"] == "." and r["root"] == str(tmp_path)  # reopening resets to the root
```

Add to the same test a vanished-folder rebuild: select `sub`, `shutil.rmtree(tmp_path / "sub")`, clear the cache with `connect._sessions.clear()`, then `c.get("/api/session").json()["database"] == "."`.

- [ ] **Step 2: Run to see them fail**

Run: `uv run --group test pytest backend/queryview/drivers/test_contract.py backend/queryview/test_api_db.py -k "union or folder" -v`
Expected: FAIL (`union` missing on CH/PG; `database`/`root` keys missing).

- [ ] **Step 3: Implement**: protocol + CH/PG signatures; `_SessionState.root`; `_list_databases` returning the result; in `_build_session` the one-line default (`database` if in list, else `"."` if `"."` in list, else `None`) with a comment that `.` is folder mode's root; `root` in `get_session`, `connect_new`, `open_saved` (`open_saved` reports the state's database when none was requested); `connect.list_tables(sid, union)` using `t.get("query") or select_all_sql(...)`; `db_tables` reads `request.query_params.get("union") == "1"`.

- [ ] **Step 4: Run all backend tests**

Run: `uv run --group test pytest backend/queryview -q`
Expected: PASS.

- [ ] **Step 5: Commit** `feat(api): folder root, default folder and union flag for DuckDB folder mode`

### Task 4: Frontend folder-nav helpers

**Files:**
- Create: `frontend/src/app/folderNav.ts`
- Test: `frontend/src/app/folderNav.test.ts`
- Modify: `frontend/src/app/connection.ts` (`Connection.root?: string`, read in `toConnection` from `data.root`)

**Interfaces:**
- Produces:
  - `isFolderNav(c: Connection): boolean` — `c.type === 'duckdb' && c.databases.length > 0`
  - `parentFolder(path: string): string | null` — `'.'` → `null`, `'a'` → `'.'`, `'a/b'` → `'a'`
  - `childFolders(databases: string[], current: string): string[]` — entries whose `parentFolder` equals `current`, in list order
  - `folderLabel(path: string, root?: string): string` — last segment; `'.'` → last segment of `root` (or `'.'` without one)
  - `fullPath(root: string, path: string): string` — `root` for `'.'`, else `` `${root}/${path}` ``
  - `PARENT = '..'` (the pseudo-entry the menu shows)

- [ ] **Step 1: Write the failing tests** in `folderNav.test.ts` (plain vitest, no mocks), one `it` per function with the values above, plus `childFolders(['.', 'a', 'a/b', 'c'], '.')` → `['a', 'c']` and `childFolders(['.', 'a', 'a/b'], 'a')` → `['a/b']`.

- [ ] **Step 2: Run to see them fail**

Run: `npm test -w frontend -- folderNav`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `folderNav.ts` and the `root` field in `connection.ts`.

- [ ] **Step 4: Run frontend unit tests and typecheck**

Run: `npm test -w frontend` and `npm run -w frontend build`
Expected: PASS.

- [ ] **Step 5: Commit** `feat(frontend): folder navigation helpers`

### Task 5: Pill menu as a one-level folder picker

**Files:**
- Modify: `frontend/src/app/App.tsx` (`DatabaseMenu`, the pill label)

**Interfaces:**
- Consumes: Task 4 helpers.

- [ ] **Step 1: Implement in `DatabaseMenu`**: when `isFolderNav(connection)`, `items` = `[PARENT]` (only when `parentFolder(connection.database ?? '.')` is not null) followed by `childFolders(connection.databases, connection.database ?? '.')`; `nameOf`/`renderItem` show `folderLabel(item, connection.root)` (and literally `..` for `PARENT`); `onPick(PARENT)` selects the parent; `headerExtra` renders `fullPath(connection.root ?? '', current)` in a `<span data-testid="db-select-path" className="truncate text-xs text-slate-400" title={...}>`. Non-folder connections are untouched.

- [ ] **Step 2: Pill label**: in folder mode show `` `${connection.name} · ${folderLabel(connection.database, connection.root)}` `` and set `title` on the `connection-status` button to `fullPath(...)`. `status-db-copy` keeps copying the relative path.

- [ ] **Step 3: Verify**: `npm run -w frontend build` passes and `npm run -w frontend lint` is clean.

- [ ] **Step 4: Commit** `feat(frontend): one-level folder picker in the connection pill`

### Task 6: Explorer "Union by name" checkbox

**Files:**
- Modify: `frontend/src/app/explorerSettings.ts`, `frontend/src/app/ExplorerView.tsx`
- Test: `frontend/src/app/explorerSettings.test.ts`

**Interfaces:**
- Produces: `loadUnionByName(): boolean` (from `viewState('explorer').unionByName`, default `false`), `saveUnionByName(on: boolean): void`.

- [ ] **Step 1: Write the failing test** in `explorerSettings.test.ts` (same mocked session mirror): `loadUnionByName()` is `false` by default, `true` after `saveUnionByName(true)`.

- [ ] **Step 2: Run to see it fail**: `npm test -w frontend -- explorerSettings` → FAIL (not exported).

- [ ] **Step 3: Implement** the two functions; in `ExplorerView`: `const [union, setUnion] = useState(loadUnionByName)`; the tables effect fetches `` `/api/db/tables${union ? '?union=1' : ''}` `` and lists `union` as a dependency; a checkbox `<label><input type="checkbox" data-testid="explorer-union" .../> Union by name</label>` in the sidebar header row, rendered only when `isFolderNav(connection)`, `onChange` → `setUnion` + `saveUnionByName`. The selected entry's new `query` flows through the existing `selected` effect, so no extra reload code.

- [ ] **Step 4: Verify**: `npm test -w frontend`, `npm run -w frontend build`, `npm run -w frontend lint` → PASS.

- [ ] **Step 5: Commit** `feat(explorer): union-by-name checkbox for folder globs`

### Task 7: End-to-end flow

**Files:**
- Modify: `e2e/conftest.py` (fixture), Create: `e2e/test_folder_nav.py`

**Interfaces:**
- Produces fixture `seeded_folder(tmp_path_factory) -> str`: a directory with `items.csv` (`id,name` / `1,alpha` / `2,beta` / `3,gamma`), `extra.csv` (`4,delta`), and `sub/nested.csv.gz` (gzip of `items.csv`).

- [ ] **Step 1: Write the test** (reuse `open_connect`, `start_new_connection`; databases up via the `claudeai-run` skill; build the SPA with `npm run build:e2e`):

```python
def test_folder_connection_navigates_folders_and_browses_files(seeded_folder, page: Page) -> None:
    open_connect(page)
    start_new_connection(page, "duckdb")
    page.get_by_test_id("duck-path").fill(seeded_folder)
    page.get_by_test_id("duck-connect").click()
    expect(page.get_by_test_id("duckdb-form")).to_have_count(0)
    expect(page.get_by_test_id("db-picker")).to_have_count(0)  # lands on the root
    expect(page.get_by_test_id("connection-status")).to_contain_text(f"· {os.path.basename(seeded_folder)}")
    expect(page.get_by_test_id("connection-status")).to_have_attribute("title", seeded_folder)
    tables = page.get_by_test_id("explorer-table")
    expect(tables).to_have_text(["extra.csv", "items.csv", "*.csv"])
    page.get_by_test_id("connection-status").click()
    expect(page.get_by_test_id("db-select-path")).to_have_text(seeded_folder)
    expect(page.get_by_test_id("db-select").get_by_role("option")).to_have_text(["sub"])  # no ".." at the root
    page.get_by_test_id("db-select").get_by_role("option", name="sub").click()
    expect(page.get_by_test_id("connection-status")).to_contain_text("· sub")
    expect(tables).to_have_text(["nested.csv.gz"])
    tables.first.click()
    expect(page.get_by_test_id("explorer-panel")).to_contain_text("gamma")
    page.get_by_test_id("connection-status").click()
    expect(page.get_by_test_id("db-select").get_by_role("option")).to_have_text([".."])
    page.get_by_test_id("db-select").get_by_role("option", name="..").click()
    expect(tables).to_have_text(["extra.csv", "items.csv", "*.csv"])
    page.get_by_test_id("explorer-union").check()
    tables.last.click()
    expect(page.get_by_test_id("explorer-panel")).to_contain_text("delta")
```

(Check how `SearchPanel` marks options — `role="option"` is what `test_app.py` queries — and adjust the `name=` lookups to the rendered label.)

- [ ] **Step 2: Run it**: `uv run --group test pytest e2e/test_folder_nav.py -v` → PASS. If a selector fails, fix the component's `data-testid`, not the assertion's intent.

- [ ] **Step 3: Run the existing DuckDB e2e cases** to confirm file mode is unchanged: `uv run --group test pytest e2e/test_drivers.py -k duckdb -v` → PASS.

- [ ] **Step 4: Commit** `test(e2e): DuckDB folder navigation`

### Task 8: Docs and cleanup

**Files:**
- Modify: `docs/connect.md`, `docs/explorer.md`, `docs/api.md`, `docs/queryview.md`
- Delete: `docs/superpowers/specs/2026-10-30-duckdb-folder-nav-design.md`, `docs/superpowers/plans/2026-10-30-duckdb-folder-nav.md`

- [ ] **Step 1: Load the `docs-writing` skill**, then update: `connect.md` (DuckDB takes a file *or a folder*; a folder gets the folder picker, landing on the root); `explorer.md` (DuckDB row of the per-driver table becomes two rows, file mode and folder mode; a **Union by name** bullet in Layout; the folder picker with the ASCII sketch from the spec); `api.md` (`/api/db/tables?union=1`; `root` and `database` in the connect/open/session rows); `queryview.md` where the picker-less driver is described.

- [ ] **Step 2: Delete the spec and this plan** (`docs/AGENTS.md`), and check `docs/future.md` still links to `explorer.md` correctly.

- [ ] **Step 3: Full verification**: `uv run --group test pytest backend/queryview -q`, `npm test -w frontend`, `npm run -w frontend lint`, `uv run --group test pytest e2e -n auto` → all PASS.

- [ ] **Step 4: Commit** `docs: DuckDB folder navigation` and push the branch.
