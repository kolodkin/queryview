# Viewer Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A display-only `queryview-server` that shows a git repo's dashboards on connections from a mounted config file, with parameter substitution done in Python for both it and the app.

**Architecture:** Phase 1 ports `frontend/src/core/dashboard/params.ts` to a pure Python module and moves the app onto it through three extended endpoints. Phase 2 adds a second FastAPI app under `backend/queryview/server/` (config, a polling git reader, viewer routes) and a second Vite page that imports `src/core` only.

**Tech Stack:** Python 3.11+, FastAPI, PyYAML, the existing drivers and `gitsync`; React 19, TypeScript, Vite; pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-20-viewer-server-design.md`

## Global Constraints

- Run Python with `uv run` (`uv run --group test pytest backend/queryview`).
- Before adding or changing a test, load the project `testing` skill.
- Before editing a page under `docs/`, load the project `docs-writing` skill.
- Imports at the top of the file; no `__all__`; no imports inside functions.
- Example data is invented (`sales_reporting`, `example.internal`); no real names.
- Commit messages carry no AI attribution trailers.
- The viewer server never accepts SQL text and never returns SQL or `options_sql`.
- Error messages never echo a connection config or the git token.
- `QV_CONFIG` names the config path, default `/etc/queryview/server.yaml`; `sync_interval` defaults to 60 seconds, `branch` to `main`.
- Phase 1 changes no behaviour for the app's users: `e2e/dashboard.spec.ts` and `e2e/widgets.spec.ts` pass unchanged.

## Review Focus

- A dashboard in the repo with malformed YAML: the others still load and the bad one is skipped (Task 6).
- An empty repo or a branch with no dashboards: the server starts and lists nothing (Task 6).
- A hostile body, such as `values` holding numbers, lists or `null`, or a non-JSON body: a 400, never a 500 (Task 7).
- A dashboard deleted from the repo while a viewer has it open: the next run is a 404 and the page says so (Tasks 7, 9).
- A database that is down: that request fails with the driver's message, the server and its other connections keep serving (Task 7).

---

## File structure

| File | Responsibility |
| --- | --- |
| `backend/queryview/dashboard_params.py` (new) | Pure param rules: parse, substitute, order, resolve |
| `backend/queryview/dashboard_queries.py` | Run queries on a driver, with or without a session |
| `backend/queryview/staticfiles.py` (new) | Serving built frontend files, shared by both apps |
| `backend/queryview/server/config.py` (new) | Load and validate the config file |
| `backend/queryview/server/repo.py` (new) | Poll the repo, hold its dashboards in memory |
| `backend/queryview/server/main.py` (new) | The viewer FastAPI app and `run()` |
| `frontend/src/core/dashboard/frameHost.ts` (new) | Frame message dispatch and the widget answerer, transport passed in |
| `frontend/src/viewer/` (new), `frontend/viewer.html` (new) | The viewer page |

---

### Task 1: Param rules in Python

**Files:**
- Create: `backend/queryview/dashboard_params.py`
- Test: `backend/queryview/test_dashboard_params.py`

**Interfaces:**
- Produces:

```python
MAX_TEXT_PARAM = 10_000

class ParamError(ValueError): ...

@dataclass(frozen=True)
class Dialect:
    quote: str
    backslash_escapes: bool

@dataclass(frozen=True)
class Param:
    name: str
    kind: str                                  # value | identifier | dimension | text
    options: tuple[str, ...] | None = None
    options_sql: str | None = None
    auto_select: bool = True
    text: str | None = None

Runner = Callable[[str], Awaitable[list[Any]]]  # one SQL -> its first column; raises ParamError

def option_text(v: Any) -> str
def parse_params(raw: object) -> list[Param]
def placeholders_in(sql: str) -> list[str]
def substitute(sql: str, params: list[Param], values: dict[str, str], dialect: Dialect) -> str
def resolve_order(params: list[Param]) -> list[Param]
def missing(sql: str, params: list[Param], values: dict[str, str]) -> list[str]
async def resolve(params: list[Param], values: dict[str, str], run: Runner, dialect: Dialect) -> list[dict[str, Any]]
def apply_to_queries(queries: dict[str, str], params: list[Param], resolved: list[dict[str, Any]], dialect: Dialect) -> dict[str, str]
```

`resolve` returns `[{"name", "kind", "options", "value"}]` in resolution order.

- [ ] **Step 1: Write the failing tests.** Port every `test(...)` in `frontend/src/core/dashboard/params.test.ts` under `parseDashboardParams`, `substituteParams`, `placeholdersIn`, `resolveOrder`, `default: none`, `missingParams`, `resolveParams`, `applyToQueries`, `an unchecked dimension` and `text params`, with the same inputs and expected outputs. Skip `parseParamsRequest` and `a message that leaves a text out keeps what was typed` (both stay in the frontend, Task 4). Errors are `ParamError` with these exact messages:

```
invalid identifier for {<param>}: <name>
unknown cast for {<name>}: <cast>
{<name>} is text: it cannot be an identifier
no value selected for {<name>}
params dependency cycle at <name>
```

Add:

```python
def test_option_text_matches_the_browser():
    assert [option_text(v) for v in ["a", 1, 1.0, 1.5, True, None]] == ["a", "1", "1", "1.5", "true", "null"]

def test_static_options_drop_null_and_containers():
    assert parse_params([{"name": "r", "options": ["eu", 2, None, [1], {"a": 1}]}])[0].options == ("eu", "2")

def test_a_text_is_capped():
    out = asyncio.run(resolve(parse_params([{"name": "n", "kind": "text"}]), {"n": "x" * 20_000}, _no_run, PG))
    assert len(out[0]["value"]) == MAX_TEXT_PARAM
```

- [ ] **Step 2: Run and see them fail.** `uv run --group test pytest backend/queryview/test_dashboard_params.py` fails on import.
- [ ] **Step 3: Implement the module** as a line-for-line port of `params.ts`. No import from `connect`, `drivers` or FastAPI. A text left out of `values` opens on its default (there is no `previous` argument).
- [ ] **Step 4: Run and see them pass.** Same command, all green.
- [ ] **Step 5: Commit.** `git commit -m "Dashboard param rules in Python"`

### Task 2: The app's endpoints substitute server-side

**Files:**
- Modify: `backend/queryview/dashboard_queries.py`, `backend/queryview/main.py` (`/api/runqueries`, `/api/db/query`, `/api/db/describe`), `docs/api.md`
- Test: `backend/queryview/test_dashboard_queries.py`, `backend/queryview/test_api_db.py`

**Interfaces:**
- Consumes: Task 1.
- Produces, in `dashboard_queries.py`:

```python
def dialect_of(driver: Driver) -> Dialect
def clean_values(raw: object) -> dict[str, str]     # a mapping's str keys with str values; anything else dropped
async def run_queries_on(driver, config, database, queries: dict[str, str],
                         limit: int = DASHBOARD_ROW_CAP, offset: int = 0) -> dict[str, Any]
async def run_dashboard_on(driver, config, database, queries: dict[str, str],
                           params: object, values: dict[str, str]) -> dict[str, Any]
async def run_dashboard(sid: str, queries: dict[str, str], params: object, values: dict[str, str]) -> dict[str, Any]
async def session_sql(sid: str, sql: str, params: object, values: dict[str, str]) -> tuple[str | None, dict[str, Any] | None]
```

`run_queries_on` is today's loop in `run_dashboard_queries`, which now calls it. `run_dashboard_on` returns `{"ok": True, "results", "meta", "params"}` or `{"ok": False, "reason": "query" | "params", "message"}`; it resolves, applies, and runs what is ready. Its `Runner` calls `driver.run_query` with `DASHBOARD_ROW_CAP` and returns the first column. `session_sql` returns the substituted SQL, or an error dict whose `reason` is the session gate's or `"params"`.

- [ ] **Step 1: Write the failing tests.** Each session is connected first with `connect.connect_new`, as the file's existing tests do.

```python
# test_dashboard_queries.py, on the existing _RowsDriver (returns columns n=[1,2], s=["a","b"])
def test_run_dashboard_resolves_then_substitutes(monkeypatch):
    seen: list[str] = []
    # a _RowsDriver subclass whose run_query appends sql to `seen`
    out = asyncio.run(run_dashboard("s-p1", {"q": "SELECT {pick}"}, [{"name": "pick", "options_sql": "SELECT n"}], {}))
    assert out["params"] == [{"name": "pick", "kind": "value", "options": ["1", "2"], "value": "1"}]
    assert seen == ["SELECT n", "SELECT '1'"]

def test_run_dashboard_holds_back_a_query_waiting_on_a_choice():
    out = asyncio.run(run_dashboard("s-p2", {"q": "SELECT {r}"}, [{"name": "r", "options": ["eu"], "default": "none"}], {}))
    assert out["ok"] and out["results"] == {}

def test_run_dashboard_reports_a_bad_value():
    out = asyncio.run(run_dashboard("s-p3", {"q": "SELECT {r:nope}"}, [{"name": "r", "options": ["eu"]}], {}))
    assert out == {"ok": False, "reason": "params", "message": "unknown cast for {r}: nope"}
```

```python
# test_api_db.py, on a DuckDB file connection as test_execute_runs_a_script_per_statement does
def test_runqueries_with_params_returns_resolved_params(tmp_path): ...
    # body {"queries": {"q": "SELECT {r} AS v"}, "params": [{"name": "r", "options": ["eu", "us"]}], "values": {"r": "us"}}
    # 200; results == {"q": {"v": ["us"]}}; params[0]["value"] == "us"
def test_runqueries_with_params_allows_no_queries(tmp_path): ...       # {"queries": {}, "params": [...]} -> 200 with params
def test_runqueries_without_params_is_unchanged(tmp_path): ...         # {"queries": {}} -> 400 "queries are required"
def test_db_query_substitutes_values(tmp_path): ...                    # {"query": "SELECT {r} AS v", "params": [...], "values": {"r": "eu"}} -> data == [["eu"]]
def test_db_query_waits_for_a_choice(tmp_path): ...                    # no value -> 400, message "Waiting for a parameter choice."
def test_db_describe_substitutes_values(tmp_path): ...                 # fields == [{"name": "v", ...}]
def test_bad_value_is_a_400(tmp_path): ...                             # identifier value containing '"' -> 400 with the ParamError message
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** The handlers take the new path only when the body has a `params` key. `/api/runqueries` then allows empty `queries` and adds `params` to the reply; `reason: "params"` is a 400.
- [ ] **Step 4: Run the backend suite.** `uv run --group test pytest backend/queryview` all green.
- [ ] **Step 5: Document** the optional `params` and `values` on the three rows of `docs/api.md`.
- [ ] **Step 6: Commit.** `git commit -m "Dashboard endpoints substitute params server-side"`

### Task 3: Stricter `ORDER BY` names

**Files:**
- Modify: `backend/queryview/drivers/base.py` (`build_order_by`), its callers in `clickhouse.py` and `mysql.py`
- Test: `backend/queryview/drivers/test_base.py`

**Interfaces:**
- Produces: `build_order_by(order_by, quote, backslash_escapes: bool = False) -> str`. A name holding the quote character, or a backslash when `backslash_escapes`, is skipped like any malformed entry. ClickHouse and MySQL pass `True`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_order_by_skips_a_name_with_the_quote_character():
    assert build_order_by([{"name": 'a"b'}, {"name": "c"}], '"') == 'ORDER BY "c" ASC'

def test_order_by_skips_a_backslash_only_where_the_dialect_escapes():
    assert build_order_by([{"name": "a\\"}], "`", backslash_escapes=True) == ""
    assert build_order_by([{"name": "a\\"}], '"') == 'ORDER BY "a\\" ASC'
```

- [ ] **Step 2: Run and see them fail**, then update any existing test that expects a doubled quote.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview/drivers` all green.
- [ ] **Step 5: Commit.** `git commit -m "ORDER BY names follow the identifier rule"`

### Task 4: The app posts templates and values

**Files:**
- Modify: `frontend/src/app/DashboardView.tsx`, `frontend/src/app/widgetHost.ts`, `frontend/src/app/App.tsx`, `frontend/src/core/dashboard/params.ts`, `frontend/src/core/index.ts`, `docs/dashboard.md`
- Test: `frontend/src/core/dashboard/params.test.ts`

**Interfaces:**
- Consumes: Task 2's request and reply shapes.
- Produces, in `params.ts`:

```ts
export function valuesOf(resolved: ResolvedParam[]): Record<string, string>
// values, plus each text param in `resolved` that `values` leaves out
export function withKeptText(values: Record<string, string>, resolved: ResolvedParam[]): Record<string, string>
```

`params.ts` keeps `ParamKind`, `ResolvedParam`, `MAX_TEXT_PARAM`, `parseParamsRequest` and the two functions above. Everything else in it is deleted, with its tests and its `core/index.ts` exports.

- [ ] **Step 1: Write the failing tests** in `params.test.ts`, replacing the deleted cases:

```ts
test('a message that leaves a text out keeps what was typed', () => {
  const resolved = [{ name: 'note', kind: 'text', options: [], value: 'hi' },
                    { name: 'r', kind: 'value', options: ['eu'], value: 'eu' }] as ResolvedParam[]
  expect(withKeptText({ r: 'us' }, resolved)).toEqual({ r: 'us', note: 'hi' })
  expect(withKeptText({ note: '' }, resolved)).toEqual({ note: '' })
})
test('valuesOf maps names to chosen values', () => {
  expect(valuesOf([{ name: 'r', kind: 'value', options: ['eu'], value: 'eu' }])).toEqual({ r: 'eu' })
})
```

- [ ] **Step 2: Run and see them fail.** `npm test -w frontend`
- [ ] **Step 3: Switch the four sites in `DashboardView.tsx`.** One runner posts `/api/runqueries` with `{queries, params, values}` and returns `{results, params}`:
  - load: non-widget queries, `values: {}`;
  - `set-params`: `withKeptText(values, resolvedRef.current)`;
  - **Execute**: `valuesOf(resolvedRef.current)`;
  - widget host: `answerWidget` posts the query's template with `params` and `valuesOf(...)` to `/api/db/query` and `/api/db/describe`.
- [ ] **Step 4: Delete** the `identQuote` and `backslashEscapes` props of `DashboardView` and their pass-through in `App.tsx`. Keep the fields in `connection.ts` if `scriptRun.ts` still reads them.
- [ ] **Step 5: Verify.** `npm test -w frontend` and `npm run lint -w frontend` pass; `npm run e2e -- dashboard widgets --trace off` passes with those two spec files unchanged.
- [ ] **Step 6: Update `docs/dashboard.md`** where it says the browser substitutes: the server does.
- [ ] **Step 7: Commit.** `git commit -m "Dashboard page sends templates and values, not SQL"`

### Task 5: The config file

**Files:**
- Create: `backend/queryview/server/__init__.py` (empty), `backend/queryview/server/config.py`
- Test: `backend/queryview/server/test_config.py`

**Interfaces:**
- Produces:

```python
DEFAULT_CONFIG_PATH = Path("/etc/queryview/server.yaml")

class ConfigError(Exception): ...

@dataclass(frozen=True)
class Connection:
    name: str
    type: str
    config: DriverConfig
    database: str | None

@dataclass(frozen=True)
class ServerConfig:
    remote: str
    branch: str
    sync_interval: float
    connections: dict[str, Connection]      # by name, in file order

def config_path() -> Path                   # $QV_CONFIG, else DEFAULT_CONFIG_PATH
def load_config(path: Path) -> ServerConfig
```

Each connection entry goes through `connect.parse_driver_config`. `database` is the entry's `database`; required when the driver's `requires_database` is true, `None` for the file drivers.

- [ ] **Step 1: Write the failing tests**, each writing YAML to `tmp_path`:

```python
def test_loads_git_and_connections(tmp_path): ...
    # git.remote only -> branch == "main", sync_interval == 60; a sqlite connection "local" -> connections["local"].type == "sqlite"
def test_missing_file_names_the_path(tmp_path): ...             # ConfigError containing str(path)
@pytest.mark.parametrize("text", ["", "- a", "git: {}", "git: {remote: r}\nconnections: []", "git: {remote: r}\nconnections: {}"])
def test_rejects_a_malformed_document(tmp_path, text): ...      # ConfigError
@pytest.mark.parametrize("interval", [0, -5, "soon"])
def test_rejects_a_bad_interval(tmp_path, interval): ...
def test_rejects_duplicate_names(tmp_path): ...
def test_rejects_an_unknown_type(tmp_path): ...                 # message names the connection
def test_requires_a_database_where_the_driver_has_a_picker(tmp_path): ...   # postgres entry without database
def test_refuses_a_duckdb_folder(tmp_path): ...                 # path = tmp_path -> "connection 'files': a DuckDB folder is not allowed on the server"
def test_errors_never_echo_a_password(tmp_path): ...            # postgres entry with password "s3cret-example", port "x" -> "s3cret-example" not in str(error)
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Every message starts with `connection '<name>': ` for a connection fault.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview/server` all green.
- [ ] **Step 5: Commit.** `git commit -m "Viewer server config file"`

### Task 6: The repo reader

**Files:**
- Create: `backend/queryview/server/repo.py`, `backend/queryview/server/conftest.py`
- Test: `backend/queryview/server/test_repo.py`

**Interfaces:**
- Consumes: `gitsync._ensure_repo`, `_origin_head`, `_repo_entities`, `_read_repo_entity`, `dashboard_to_files`, `dashboard_reldir`; `workspaces.WorkspaceRec`.
- Produces:

```python
class Repo:
    def __init__(self, remote: str, branch: str) -> None
    async def refresh(self) -> bool              # fetch; re-read when the head moved; True if it did. Raises GitSyncError.
    def names(self) -> list[str]                 # sorted
    def get(self, name: str) -> dict[str, Any] | None   # {name, html, queries, params}
```

`Repo` drives `gitsync` with `WorkspaceRec(id=0, name="server", remote=remote, branch=branch)`; no workspace row has id 0. The dashboards are swapped in as one new dict, so a request never sees half a refresh.

- `conftest.py` fixture `dash_repo(tmp_path, clone_base)` returns an object with `remote: Path` (a bare repo on `main`) and `commit(dashboards: list[dict], remove: list[str] = [])`, which writes each dashboard's three files with `dashboard_to_files` under `dashboard_reldir(name)`, commits and pushes from a scratch clone.

- [ ] **Step 1: Write the failing tests.**

```python
SALES = {"name": "sales", "html": "<p>hi</p>", "queries": {"q": "SELECT 1 AS n"}, "params": []}

def test_reads_the_dashboards_at_the_head(dash_repo): ...       # commit [SALES]; refresh() is True; names() == ["sales"]; get("sales")["queries"] == SALES["queries"]
def test_refresh_is_false_when_nothing_moved(dash_repo): ...
def test_picks_up_a_new_commit(dash_repo): ...                  # second commit adds "ops", removes "sales" -> names() == ["ops"]
def test_an_empty_remote_lists_nothing(dash_repo): ...          # no commit: refresh() does not raise; names() == []
def test_a_malformed_dashboard_is_skipped(dash_repo): ...       # SALES plus a dir whose meta.yaml is "name: [" -> names() == ["sales"]
def test_a_failed_fetch_keeps_the_last_copy(dash_repo): ...     # commit, refresh, delete the bare repo; refresh() raises GitSyncError; names() == ["sales"]
def test_fetch_errors_hide_the_token(tmp_path, clone_base): ... # remote "https://user:tok-example@invalid.example/x.git" -> "tok-example" not in str(error)
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** A dashboard whose files fail to parse is logged with its path and skipped.
- [ ] **Step 4: Run** the `server` tests, all green.
- [ ] **Step 5: Commit.** `git commit -m "Viewer server reads dashboards from the repo"`

### Task 7: The viewer API

**Files:**
- Create: `backend/queryview/staticfiles.py`, `backend/queryview/server/main.py`
- Modify: `backend/queryview/main.py` (static serving moves out), `pyproject.toml` (`queryview-server = "queryview.server.main:run"`)
- Test: `backend/queryview/server/test_main.py`, `backend/queryview/test_static.py` (still green)

**Interfaces:**
- Consumes: Tasks 1, 2, 5, 6.
- Produces:

```python
# staticfiles.py — moved from main.py, plus `index`
def static_root() -> Path
async def serve_static(full_path: str, versioned: bool = False, index: str = "index.html") -> Response

# server/main.py
def create_app(config: ServerConfig) -> FastAPI
def run() -> None     # load_config(config_path()); uvicorn on $PORT / --port, as the app
```

Lifespan: `await repo.refresh()` (a failure aborts startup), then a task that sleeps `sync_interval` and refreshes, logging a `GitSyncError` and carrying on. Static files serve with `index="viewer.html"`. `create_app` keeps the `Repo` on `app.state.repo`.

Routes, exactly the spec's "Phase 2: API" table. Details the table leaves open:

- `POST /api/run`: `queries` is an optional list of names; omitted means all. The reply is `run_dashboard_on`'s, without `meta`.
- `POST /api/query`: `limit` defaults to 100 and is clamped to 1..1000, `offset` to >= 0, as `/api/db/query`. The SQL is `apply_to_queries({query: sql}, …)` over freshly resolved params; when the query is held back the reply is a 400 `Waiting for a parameter choice.`
- Status codes: 404 unknown connection, dashboard or query name; 400 bad body, bad value, or a failing query (with the driver's message); 200 otherwise.
- `values` goes through `clean_values`.

- [ ] **Step 1: Write the failing tests.** One fixture builds `ServerConfig` over `dash_repo` and a SQLite file with table `orders(region, amount)` holding `("eu", 10), ("us", 20)`, and yields `TestClient(create_app(config))` inside `with` so the lifespan runs. The repo holds:

```python
SALES = {
    "name": "sales", "html": '<qv-select-view query="rows"></qv-select-view>',
    "queries": {"total": "SELECT sum(amount) AS t FROM orders WHERE region = {region}",
                "rows": "SELECT * FROM orders ORDER BY {col}"},
    "params": [{"name": "region", "options_sql": "SELECT DISTINCT region FROM orders ORDER BY 1"},
               {"name": "col", "kind": "identifier", "options": ["amount", "region"]}],
}
```

```python
def test_health(client): ...                                    # 200
def test_connections_list_names_and_types_only(client): ...     # == [{"name": "local", "type": "sqlite"}]
def test_dashboard_carries_no_sql(client): ...                  # == {"name": "sales", "html": ..., "queries": ["total", "rows"]}; "SELECT" not in r.text
def test_run_resolves_and_runs(client): ...                     # values {} -> results["total"] == {"t": [10]}; params[0]["options"] == ["eu", "us"]
def test_run_only_the_named_queries(client): ...                # queries ["total"] -> set(results) == {"total"}
def test_a_value_outside_the_options_never_reaches_the_sql(client): ...
    # /api/query rows with values {"col": "amount FROM orders; --"} -> 200, sorted by amount (the default)
def test_query_pages_and_sorts(client): ...                     # limit 1, order_by [{"name": "amount", "dir": "DESC"}] -> data == [["us", 20]]
def test_query_csv(client): ...                                 # format "csv" -> output starts with the header row
def test_describe(client): ...                                  # fields names == ["region", "amount"]
@pytest.mark.parametrize("body", [{"connection": "nope"}, {"dashboard": "nope"}, {"query": "nope"}])
def test_unknown_names_are_404(client, body): ...
@pytest.mark.parametrize("values", [None, [1], {"region": 5}, {"region": None}, {"region": ["eu"]}])
def test_hostile_values_are_not_a_500(client, values): ...      # status < 500
def test_a_non_json_body_is_a_400(client): ...
def test_a_dashboard_removed_from_the_repo_is_a_404(client, dash_repo): ...   # commit(remove=["sales"]); app.state.repo.refresh(); /api/run -> 404
def test_a_failing_database_does_not_stop_the_server(client): ...
    # a second connection "gone" on a path whose file is deleted after startup -> /api/run on it is 400 with a message; "local" still 200
def test_no_app_routes_exist(client): ...                       # POST /api/db/query, /api/dashboards, /api/runqueries and GET /mcp/ -> 404 or 405
def test_startup_fails_when_the_clone_fails(tmp_path, clone_base): ...   # remote to a missing path -> entering TestClient raises
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Move static serving** into `staticfiles.py`; `main.py` imports it. `uv run --group test pytest backend/queryview/test_static.py` stays green.
- [ ] **Step 4: Implement `server/main.py`** and add the console script.
- [ ] **Step 5: Run the backend suite**, all green.
- [ ] **Step 6: Commit.** `git commit -m "Viewer server API"`

### Task 8: Shared frame host in core

**Files:**
- Create: `frontend/src/core/dashboard/frameHost.ts`, `frontend/src/core/download.ts`
- Modify: `frontend/src/app/DashboardView.tsx`, `frontend/src/app/widgetHost.ts` (deleted, its logic moves), `frontend/src/app/yamlio.ts` (`downloadText` moves to core and is re-imported), `frontend/src/core/index.ts`
- Test: `frontend/src/core/dashboard/frameHost.test.ts`

**Interfaces:**
- Produces:

```ts
// download.ts
export function downloadText(name: string, text: string, type: string): void

// frameHost.ts
export type WidgetPost = (kind: 'query' | 'describe', req: WidgetRequest) => Promise<Record<string, unknown>>
// Answer one widget request through `post`; null for a CSV (downloaded, or reported through onCsvError).
export function answerWidget(req: WidgetRequest, post: WidgetPost, onCsvError: (message: string) => void): Promise<WidgetReply | null>

export type FrameHandlers = {
  onSnapshot(result: SnapshotResult): void
  onWidget(req: WidgetRequest): Promise<WidgetReply | null>
  onSetParams(values: Record<string, string>): Promise<Record<string, unknown>>   // the params-results message
}
// Dispatch the frame's messages; ignores other windows. Returns the unsubscribe.
export function listenToFrame(frame: () => HTMLIFrameElement | null, handlers: FrameHandlers): () => void
```

`post` owns the request body, so the app adds `{query: <template>, params, values}` and the viewer adds `{connection, dashboard, query: <name>, values}`; paging fields come from `req`.

- [ ] **Step 1: Write the failing tests** for `answerWidget` with a fake `post`: a describe reply maps to `widget-fields`; a query reply maps to `widget-result` with `meta` and `data`; `{ok: false, message}` maps to `failureReply`; a failed CSV calls `onCsvError` and returns `null`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement**, then replace `DashboardView.tsx`'s message listener and `widgetHost.ts` with the core functions.
- [ ] **Step 4: Verify.** `npm test -w frontend`, `npm run lint -w frontend`, and `npm run e2e -- dashboard widgets --trace off` pass.
- [ ] **Step 5: Commit.** `git commit -m "Dashboard frame host moves to core"`

### Task 9: The viewer page

**Files:**
- Create: `frontend/viewer.html`, `frontend/src/viewer/main.tsx`, `frontend/src/viewer/ViewerApp.tsx`, `frontend/src/viewer/api.ts`, `e2e/server.spec.ts`
- Modify: `frontend/vite.config.ts` (`build.rollupOptions.input: { main: 'index.html', viewer: 'viewer.html' }`), `frontend/eslint.config.js` (`src/viewer` may import `src/core` and packages only), `e2e/fixtures.ts` (start `queryview-server`), `frontend/AGENTS.md` (the `viewer/` line)

**Interfaces:**
- Consumes: Task 7's routes, Task 8's `listenToFrame`, `answerWidget`, `downloadText`; core's `DashboardFrame`, `widgetQueryNames`, `snapshotDocument`, `withKeptText`, `valuesOf`.
- Produces: `data-testid`s `viewer-connection`, `viewer-dashboard`, `viewer-snapshot`, `viewer-error`; local storage keys `qv_viewer_connection`, `qv_viewer_dashboard`.

Behaviour:

- Layout as the spec's sketch; styles from `index.css`, as the app.
- Selection: `?connection=` and `?name=` first, then local storage, then the first connection and no dashboard. A stored connection or dashboard that is gone falls back the same way. Each pick writes both the URL and local storage. Storage access is wrapped in try/catch.
- Load: `GET /api/dashboards/{name}`, then `POST /api/run` with the names not in `widgetQueryNames(html)` and `values: {}`.
- `set-params`: `POST /api/run` with `withKeptText(values, resolved)`; the frame gets `{type: 'params-results', ok, results, params}` or `{ok: false, message, params}`.
- Changing the connection re-runs the open dashboard.
- A failed request shows its `message` in `viewer-error`; a 404 for the dashboard reads `Dashboard “<name>” not found.`

- [ ] **Step 1: Add the e2e fixture.** Beside the existing `queryview-backend` starter in `e2e/fixtures.ts`, a starter for `queryview-server` that writes a config (`QV_CONFIG`) pointing at a local bare repo and a SQLite file it seeds, on a free port with a scratch `DATA_DIR`.
- [ ] **Step 2: Write the failing e2e** in `e2e/server.spec.ts`:
  - the page lists the repo's dashboard, renders it, and a `<qv-param>` change re-runs the query;
  - a `<qv-select-view>` pages and sorts;
  - `?connection=…&name=…` opens directly, and a reload with no query string reopens the last pick;
  - no **Save**, **Edit queries** or **New query** control exists;
  - after a push to the repo, a reload within the sync interval (set to 1 second) shows the new dashboard;
  - opening `?name=gone` shows `Dashboard “gone” not found.`
- [ ] **Step 3: Run and see it fail.** `npm run e2e -- server --trace off`
- [ ] **Step 4: Implement** the page, the Vite entry and the lint rule.
- [ ] **Step 5: Verify.** `npm run lint -w frontend`, `npm test -w frontend`, and the full `npm run e2e -- --trace off` pass.
- [ ] **Step 6: Commit.** `git commit -m "Viewer page"`

### Task 10: Docs and cleanup

**Files:**
- Create: `docs/server.md`
- Modify: `README.md` (docs list), `docs/docker.md`, `docs/future.md`, `docs/api.md`
- Delete: `docs/superpowers/specs/2026-11-20-viewer-server-design.md`, `docs/superpowers/plans/2026-11-20-viewer-server.md`

- [ ] **Step 1: Write `docs/server.md`** in the house style: what the server is, the page sketch, the config file with the spec's example, sync, the security notes (no login, put a proxy or SSO in front, read-only login without file privileges, DuckDB folders refused), an `## API` section naming the routes, `## Related docs`.
- [ ] **Step 2: Update the others.** `docker.md`: running the image with the command `queryview-server` and the config mounted. `api.md`: the viewer routes. `future.md`: a line under Dashboards for an agent tool that runs a dashboard with values, and remove "multi-user sync needs git pulling or a webhook first" only if it no longer holds for the app (it still does: leave it).
- [ ] **Step 3: Run `devpowers:shortify`** on the pages touched.
- [ ] **Step 4: Delete the spec and this plan**, and fix any link to them.
- [ ] **Step 5: Final check.** `uv run --group test pytest backend/queryview`, `npm test -w frontend`, `npm run lint -w frontend`, `npm run e2e -- --trace off` all pass.
- [ ] **Step 6: Commit.** `git commit -m "Docs: the viewer server"`
