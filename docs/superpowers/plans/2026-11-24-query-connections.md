# A Connection per Dashboard Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dashboard query may name the connection it runs on; a plain SQL string still runs on the session's connection.

**Architecture:** A query entry is `str | {connection, sql, database?}`. One pure module validates and reads entries. The runner takes a target (driver, config, database) per query and per `options_sql`, found through a lookup the app and the viewer server each supply. The frontend carries entries through unchanged and edits them in the SQL panel.

**Tech Stack:** Python 3 / FastAPI / pytest (`uv run --group test pytest`), React + TypeScript / vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-24-query-connections-design.md`

## Global Constraints

- A string entry behaves exactly as today in every reader. Every existing test passes unchanged, apart from call signatures this plan changes.
- Error messages, verbatim (`orders` is the query, `warehouse` the connection):
  `orders: unknown connection "warehouse"`, `orders: connection "warehouse" is locked`, `orders: no database selected on "warehouse"`.
- A failing connection lookup for a query is `{"ok": False, "reason": "query", "message": …}`; for a param, `reason: "params"`.
- `DASHBOARD_CONCURRENCY` stays 5 per run, across connections.
- Built on today's endpoints (`/api/runqueries`, `/api/db/query`, `/api/db/describe`, viewer `/api/run`, `/api/query`, `/api/describe`). No endpoint is added.
- Repo rules (`AGENTS.md`): `uv run`, imports at the top of the file, no `__all__`, no AI attribution in commits, invented example names only (`warehouse`, `sales_reporting`).
- Load the project `testing` skill before writing a test, and `docs-writing` before editing `docs/`.
- After each backend task: `uv run ruff check backend && uv run ruff format --check backend`. After each frontend task: `npm run lint -w frontend`.

## Review Focus

- A map entry naming the session's own active connection, with no `database`: it runs on the session's selected database, not the stored one. (Task 3)
- An `each` query on a named connection: every run goes to that connection. (Task 2)
- One param value used by queries on two dialects: each query gets its own quoting. (Task 2)
- Many queries naming one connection: it is looked up once per run. (Task 2)
- Opening the SQL panel on an entry whose connection this instance lacks, then editing its text: `connection` and `database` survive. (Task 6)

## File Structure

| File | Responsibility |
|---|---|
| `backend/queryview/dashboard_entries.py` (new) | The entry shape: validate, clean, read. Pure. |
| `backend/queryview/dashboard_params.py` | `Param.connection` / `.database`; a dialect and runner per param. |
| `backend/queryview/dashboard_queries.py` | `Target`, `Lookup`, resolving targets, running per target. |
| `backend/queryview/connect.py` | `connection_target`: a named connection for a session, with the lock and database rules. |
| `backend/queryview/app.py`, `server/main.py`, `mcp_server.py`, `yamlio.py` | Callers. |
| `frontend/src/core/dashboard/entries.ts` (new) | The entry type and its pure edits. |
| `frontend/src/app/DashboardView.tsx`, `DashboardSqlPanel.tsx` | Carry and edit entries. |

---

### Task 1: The entry

**Files:**
- Create: `backend/queryview/dashboard_entries.py`, `backend/queryview/test_dashboard_entries.py`
- Modify: `backend/queryview/app.py` (`_clean_queries` and its two callers), `backend/queryview/yamlio.py` (`dashboard_from_data`), `backend/queryview/validation.py` (`_entry_error`), `backend/queryview/dashboards.py` (type hints only)
- Test: also `backend/queryview/test_yamlio.py`, `backend/queryview/test_validation.py`, `backend/queryview/test_dashboards.py`

**Interfaces:**
- Produces, in `dashboard_entries.py`:
  - `Entry = str | dict[str, str]`
  - `map_error(entry: dict[str, Any]) -> str | None`: `sql must be a non-empty string`, `connection must be a non-empty string`, `database must be a non-empty string`, `unknown key 'x'`.
  - `queries_error(raw: object) -> str | None`: strict, for push, import and git sync. A non-mapping, a non-string name, or a value that is neither string nor mapping: `queries must be a {name: SQL} map`. A malformed map: `query 'orders': <map_error>`. Strings pass whatever they hold.
  - `clean_entries(raw: object) -> dict[str, Entry]`: lenient, for Save and run requests. Keeps non-blank strings (today's `_clean_queries` rule) and well-formed maps.
  - `entry_sql(entry: Entry) -> str`
  - `entry_connection(entry: Entry) -> tuple[str, str | None] | None`: `(connection, database)`, `None` for a string.

- [ ] **Step 1: Write the failing tests** in `test_dashboard_entries.py`:

```python
ORDERS = {"connection": "warehouse", "sql": "SELECT 1"}

def test_a_string_and_a_map_are_both_entries():
    assert queries_error({"sales": "SELECT 1", "orders": ORDERS, "blank": ""}) is None
    assert entry_sql("SELECT 1") == entry_sql(ORDERS) == "SELECT 1"
    assert entry_connection("SELECT 1") is None
    assert entry_connection(ORDERS) == ("warehouse", None)
    assert entry_connection({**ORDERS, "database": "reporting"}) == ("warehouse", "reporting")

@pytest.mark.parametrize("entry, why", [
    ({"connection": "warehouse"}, "sql must be a non-empty string"),
    ({"connection": "warehouse", "sql": " "}, "sql must be a non-empty string"),
    ({"sql": "SELECT 1"}, "connection must be a non-empty string"),
    ({**ORDERS, "connection": 5}, "connection must be a non-empty string"),
    ({**ORDERS, "database": ""}, "database must be a non-empty string"),
    ({**ORDERS, "limit": 5}, "unknown key 'limit'"),
])
def test_a_malformed_map_is_named(entry, why):
    assert queries_error({"orders": entry}) == f"query 'orders': {why}"

@pytest.mark.parametrize("raw", [None, [], {"q": 5}, {"q": ["SELECT 1"]}, {5: "SELECT 1"}])
def test_anything_else_is_not_a_queries_map(raw):
    assert queries_error(raw) == "queries must be a {name: SQL} map"

def test_cleaning_keeps_what_can_run():
    raw = {"sales": "SELECT 1", "blank": " ", "orders": ORDERS, "bad": {"sql": "SELECT 1"}, "n": 5, "": "SELECT 1"}
    assert clean_entries(raw) == {"sales": "SELECT 1", "orders": ORDERS}
    assert clean_entries("nope") == {}
```

In `test_yamlio.py`: `dashboard_from_data` accepts `{"name": "d", "html": "<p>", "queries": {"orders": ORDERS}}` and returns the entry unchanged; with `{"orders": {"sql": "SELECT 1"}}` it raises `YamlIOError` matching `query 'orders': connection must be a non-empty string`; a string-only dashboard round-trips through `dashboard_to_data` byte-identical when dumped. In `test_validation.py`: a param `{"name": "r", "options_sql": "SELECT 1", "connection": "warehouse", "database": "reporting"}` has no error; `{"name": "r", "options": ["a"], "connection": "warehouse"}` errors with `invalid params[0] 'r' connection needs options_sql`; `connection: ""` errors with `invalid params[0] 'r' connection must be a non-empty string` (same wording for `database`). In `test_dashboards.py`: `POST /api/dashboards` with a map entry stores it and `GET` returns it; with a malformed map beside a good string, it saves and the malformed one is gone.

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_entries.py backend/queryview/test_yamlio.py backend/queryview/test_validation.py backend/queryview/test_dashboards.py -q`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement.** `dashboard_entries.py` as above. `app.py`: delete `_clean_queries`, call `clean_entries`. `yamlio.dashboard_from_data`: replace the inline check with `queries_error`, keeping the `malformed {where}: ` prefix. `validation._entry_error`: the two param rules. `dashboards.py`: hints become `dict[str, Entry]`.
- [ ] **Step 4: Run the same command, then `uv run --group test pytest backend/queryview -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `Dashboards: a query entry may be a map naming its connection`.

### Task 2: A target per query and per param

**Files:**
- Modify: `backend/queryview/dashboard_params.py`, `backend/queryview/dashboard_queries.py`, `backend/queryview/server/main.py` (call sites only, behavior unchanged until Task 4)
- Test: `backend/queryview/test_dashboard_params.py`, `backend/queryview/test_dashboard_queries.py`

**Interfaces:**
- Consumes: `Entry`, `entry_sql`, `entry_connection` (Task 1).
- Produces, in `dashboard_params.py`:
  - `Param` gains `connection: str | None = None`, `database: str | None = None`, read by `_parse_entry` only beside `options_sql`.
  - `Runner = Callable[[Param, str], Awaitable[list[Any]]]`
  - `resolve(params, values, run: Runner, dialects: Mapping[str, Dialect])`: `dialects[p.name]` quotes param `p`'s `options_sql`. Only params with `options_sql` are looked up.
  - `apply_to_queries(queries: dict[str, str], params, resolved, dialects: Mapping[str, Dialect])`: `dialects[query_name]`.
- Produces, in `dashboard_queries.py`:
  - `@dataclass(frozen=True) class Target: driver: Driver; config: DriverConfig; database: str | None`
  - `Lookup = Callable[[str, str | None], Awaitable[Target | str]]`: a connection name and an entry's `database` to its target, or the message without the query's name (`unknown connection "warehouse"`).
  - `run_queries_on(targets: Mapping[str, Target], queries: Mapping[str, str | dict[str, str]], limit: int = DASHBOARD_ROW_CAP, offset: int = 0) -> dict[str, Any]`: `targets[query_name]`.
  - `run_dashboard_on(default: Target | None, lookup: Lookup, queries: dict[str, Entry], params: object, values: dict[str, str]) -> dict[str, Any]`. A string entry, or an `options_sql` with no connection, uses `default`. Each `(connection, database)` pair is looked up once. A query's failed lookup returns `{"ok": False, "reason": "query", "message": f"{name}: {message}"}` for the first failing query in the given order, with `params` attached as a failing query has today; a param's returns the params error `f"{name}: {message}"`.
  - `resolve_on(default: Target | None, lookup: Lookup, params: list[Param], values) -> list[dict[str, Any]]`.
  - `run_dashboard_on` raises nothing new when `default is None` and nothing needs it; callers guarantee a default when something does (Task 3).

- [ ] **Step 1: Write the failing tests** in `test_dashboard_queries.py`, using two `_SeenDriver`s, the second a subclass with `ident_quote = "`"` and `backslash_escapes = True`:

```python
def _targets():
    here, there = _SeenDriver(), _BacktickDriver()
    looked: list[tuple[str, str | None]] = []

    async def lookup(name, database):
        looked.append((name, database))
        return Target(there, {"v": 2}, database or "reporting") if name == "warehouse" else f'unknown connection "{name}"'

    return here, there, looked, Target(here, {"v": 1}, "main"), lookup

def test_each_entry_runs_on_its_own_connection():
    here, there, looked, default, lookup = _targets()
    q = {"sales": "SELECT 1", "orders": {"connection": "warehouse", "sql": "SELECT 2"}}
    out = asyncio.run(run_dashboard_on(default, lookup, q, [], {}))
    assert out["ok"] and set(out["results"]) == {"sales", "orders"}
    assert here.seen == ["SELECT 1"] and there.seen == ["SELECT 2"]

def test_a_connection_is_looked_up_once_per_run():
    _, there, looked, default, lookup = _targets()
    q = {n: {"connection": "warehouse", "sql": f"SELECT {i}"} for i, n in enumerate("abc")}
    asyncio.run(run_dashboard_on(default, lookup, q, [], {}))
    assert looked == [("warehouse", None)] and len(there.seen) == 3

def test_an_unknown_connection_fails_its_query_by_name():
    *_, default, lookup = _targets()
    q = {"sales": "SELECT 1", "orders": {"connection": "nope", "sql": "SELECT 2"}}
    out = asyncio.run(run_dashboard_on(default, lookup, q, [], {}))
    assert (out["ok"], out["reason"], out["message"]) == (False, "query", 'orders: unknown connection "nope"')

def test_a_value_is_quoted_for_the_connection_its_query_runs_on():
    here, there, _, default, lookup = _targets()
    params = [{"name": "col", "kind": "identifier", "options": ["city"]}, {"name": "who", "options": ["a\\b"]}]
    q = {"sales": "SELECT {col} WHERE u = {who}", "orders": {"connection": "warehouse", "sql": "SELECT {col} WHERE u = {who}"}}
    asyncio.run(run_dashboard_on(default, lookup, q, params, {}))
    assert here.seen == ["SELECT \"city\" WHERE u = 'a\\b'"]
    assert there.seen == ["SELECT `city` WHERE u = 'a\\\\b'"]

def test_options_sql_runs_on_the_params_connection():
    here, there, _, default, lookup = _targets()
    params = [{"name": "r", "options_sql": "SELECT r", "connection": "warehouse"}]
    asyncio.run(run_dashboard_on(default, lookup, {"sales": "SELECT {r}"}, params, {}))
    assert there.seen == ["SELECT r"] and len(here.seen) == 1

def test_an_unknown_connection_on_a_param_is_a_params_error():
    *_, default, lookup = _targets()
    params = [{"name": "r", "options_sql": "SELECT r", "connection": "nope"}]
    out = asyncio.run(run_dashboard_on(default, lookup, {}, params, {}))
    assert (out["ok"], out["reason"], out["message"]) == (False, "params", 'r: unknown connection "nope"')

def test_a_query_per_value_fans_out_on_its_own_connection():
    here, there, _, default, lookup = _targets()
    params = [{"name": "region", "kind": "each", "options": ["eu", "us"]}]
    q = {"orders": {"connection": "warehouse", "sql": "SELECT {region}"}}
    asyncio.run(run_dashboard_on(default, lookup, q, params, {}))
    assert there.seen == ["SELECT 'eu'", "SELECT 'us'"] and here.seen == []

def test_nothing_on_the_default_needs_no_default():
    _, there, _, _, lookup = _targets()
    q = {"orders": {"connection": "warehouse", "sql": "SELECT 2"}}
    assert asyncio.run(run_dashboard_on(None, lookup, q, [], {}))["ok"]
```

In `test_dashboard_params.py`: `parse_params` reads `connection`/`database` beside `options_sql` and ignores them elsewhere; existing `resolve` and `apply_to_queries` tests pass a mapping where they passed one dialect.

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_queries.py backend/queryview/test_dashboard_params.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `run_dashboard_on`: parse params; look up every distinct connection named by a param or entry; resolve params with a runner that runs `sql` on the param's target; substitute per query dialect; run with `targets`. Update `run_dashboard_queries`, `run_dashboard`, `session_sql` and `server/main.py`'s three call sites to the new signatures with a lookup that answers `unknown connection "…"` for every name, so behavior is unchanged.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview -q`. Expected: PASS.
- [ ] **Step 5: Commit** `Dashboards: run each query and options_sql on its own target`.

### Task 3: The app

**Files:**
- Modify: `backend/queryview/connect.py`, `backend/queryview/dashboard_queries.py` (`run_dashboard`, `run_dashboard_queries`, `session_sql`), `backend/queryview/app.py` (`/api/runqueries`, `/api/db/query`, `/api/db/describe`)
- Test: `backend/queryview/test_dashboard_queries.py`, `backend/queryview/test_api_db.py`, `backend/queryview/test_locked_connections.py`

**Interfaces:**
- Consumes: `Target`, `Lookup`, `run_dashboard_on` (Task 2); `clean_entries` (Task 1).
- Produces:
  - `connect.connection_target(sid: str, name: str, database: str | None) -> tuple[str, DriverConfig, str | None] | str`: `(type, config, database)` or one of the three messages without the query's name. Resolution order `_resolve(sid, name)`; a saved connection with a lock hash needs `_is_unlocked(sid, name)`; database is the argument, else the session's selected one when `name` is its active connection, else the stored row's; none on a `requires_database` driver is the third message.
  - `dashboard_queries.session_lookup(sid: str) -> Lookup` wrapping it into `Target`.
  - `run_dashboard(sid, queries: dict[str, Entry], params, values)` and `run_dashboard_queries(sid, queries: dict[str, Entry], …)`: the session gate runs only when a string entry or a connection-less `options_sql` is present; when it refuses, the whole call fails as today.
  - `/api/db/query` and `/api/db/describe` accept optional body fields `connection` (string) and `database` (string). With `connection`, the request runs on `connection_target` instead of the session gate; a failed lookup is `400 {"ok": false, "reason": "query", "message": 'unknown connection "nope"'}`. Without it, both routes are untouched.

- [ ] **Step 1: Write the failing tests.** In `test_dashboard_queries.py`, with `rowsfake` and a second registered driver type saved as connection `warehouse` through `connect.connect_new` on another session:

```python
def test_a_named_saved_connection_runs_from_any_session(monkeypatch): ...
    # session s-a on "main"; {"orders": {"connection": "warehouse", "sql": "SELECT 2"}} -> warehouse's driver saw "SELECT 2"
def test_all_named_queries_need_no_session(monkeypatch): ...
    # sid never connected -> out["ok"] is True
def test_a_mixed_dashboard_still_needs_the_session(monkeypatch): ...
    # sid never connected, one string entry -> out["reason"] == "no-session", nothing ran on warehouse
def test_naming_the_sessions_own_connection_uses_its_selected_database(monkeypatch): ...
    # session selects "today"; stored row says "yesterday" -> driver saw database == "today"
def test_the_entrys_database_wins(monkeypatch): ...
def test_a_connection_that_needs_a_database_and_has_none(monkeypatch): ...
    # message == 'orders: no database selected on "warehouse"'
```

In `test_locked_connections.py`: `test_a_dashboard_reaches_a_locked_connection_only_with_the_token`: a second session's run of a map entry on a locked connection returns `orders: connection "warehouse" is locked`; the locking session's run succeeds. In `test_api_db.py`: `/api/runqueries` with a map entry returns its rows; with a malformed map beside a string, only the string runs; `/api/db/query` with `connection` returns that connection's rows and with an unknown one the 400 above; `/api/db/describe` likewise; both without `connection` behave as before (existing tests).

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_queries.py backend/queryview/test_api_db.py backend/queryview/test_locked_connections.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces. In the two `/api/db/*` routes, the `connection` branch substitutes with `ready_sql(sql, params, values, dialect_of(target.driver))` when `params` is in the body and calls `target.driver.run_query` / `export_csv` / `describe_query` directly, shaping the reply as the session branch does.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview -q`. Expected: PASS.
- [ ] **Step 5: Commit** `App: dashboard queries run on the connections they name`.

### Task 4: The viewer server

**Files:**
- Modify: `backend/queryview/server/main.py`
- Test: `backend/queryview/server/test_main.py`

**Interfaces:**
- Consumes: `Target`, `Lookup`, `run_dashboard_on`, `resolve_on` (Task 2); `entry_sql`, `entry_connection` (Task 1).
- Produces: no new names. `/api/run`, `/api/query` and `/api/describe` look a map entry's connection up in `config.connections`; its database is the entry's, else the configured one. A string entry runs on the request's `connection`, as today. `GET /api/dashboards/{name}` still returns query names only.

- [ ] **Step 1: Write the failing tests** in `test_main.py`, with a second sqlite connection `warehouse` in the config and a repo dashboard holding `orders: {connection: warehouse, sql: …}` beside a string query:
  - `test_a_query_runs_on_the_connection_it_names`: `POST /api/run` on `local` returns `orders` rows that exist only in `warehouse`'s file and the string query's rows from `local`.
  - `test_a_query_naming_an_unconfigured_connection_fails_by_name`: message `orders: unknown connection "nope"`.
  - `test_a_widget_pages_on_its_querys_connection`: `POST /api/query` and `/api/describe` for `orders` answer from `warehouse`.
  - `test_the_dashboard_listing_never_carries_an_entry`: `GET /api/dashboards/sales` has `queries == ["total", "orders"]`.
- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/server -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** One lookup closure over `config.connections`; `_widget_sql` returns the SQL with its target.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview -q`. Expected: PASS.
- [ ] **Step 5: Commit** `Viewer server: a query runs on the configured connection it names`.

### Task 5: `push_dashboard`

**Files:**
- Modify: `backend/queryview/mcp_server.py`
- Test: `backend/queryview/test_mcp_connections.py`

**Interfaces:**
- Consumes: `queries_error`, `entry_connection` (Task 1); `connect._resolve`, `agent_connections_for`, `_AGENT_DRIVERS` (existing).
- Produces: `push_dashboard(queries: dict[str, str | dict[str, str]] | None, …)`. Before pushing, for each connection a query or a param names:
  - exists but is absent from `agent_connections_for(session_id)` (locked): refused, `connection is locked`;
  - listed, not agent-created, type outside `_AGENT_DRIVERS`: refused with `use_connection`'s message;
  - does not exist: accepted; the reply's `message` ends with `; unknown connections: nope, other` (sorted, once each).

- [ ] **Step 1: Write the failing tests:** `test_push_takes_a_query_naming_a_connection` (the pushed event carries the entry), `test_push_refuses_a_locked_connection`, `test_push_refuses_a_file_connection_the_agent_did_not_add`, `test_push_reports_a_connection_this_instance_lacks` (`pushed` is true and the message ends as above), `test_push_refuses_a_malformed_entry` (message `query 'orders': connection must be a non-empty string`), and one through `dir` with a map entry in `queries.yaml`.
- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_mcp_connections.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Update the docstring: replace "a dashboard never names a connection" with the two entry shapes, and `queries.yaml (a {name: SQL} map)` likewise.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview -q`. Expected: PASS.
- [ ] **Step 5: Commit** `MCP: push_dashboard takes queries naming a connection`.

### Task 6: The dashboard page and the SQL panel

**Files:**
- Create: `frontend/src/core/dashboard/entries.ts`, `frontend/src/core/dashboard/entries.test.ts`
- Modify: `frontend/src/core/index.ts` (export, as its neighbours are), `frontend/src/app/DashboardView.tsx`, `frontend/src/app/DashboardSqlPanel.tsx`

**Interfaces:**
- Produces, in `entries.ts`:
  - `type QueryEntry = string | { connection: string; sql: string; database?: string }`
  - `entrySql(e: QueryEntry): string`
  - `entryConnection(e: QueryEntry): string | null`
  - `withSql(e: QueryEntry, sql: string): QueryEntry`: a string stays a string; a map keeps its other keys.
  - `withConnection(e: QueryEntry, connection: string | null): QueryEntry`: `null` gives the bare SQL string; a name gives a map, keeping `database` only when the name is unchanged.
- `DashboardPush.queries` and the panel's `queries` prop become `Record<string, QueryEntry>`. The panel gains `onConnection: (name: string, connection: string | null) => void` and `connections: string[]`.

- [ ] **Step 1: Write the failing tests** in `entries.test.ts`:

```ts
const orders = { connection: 'warehouse', sql: 'SELECT 1', database: 'reporting' }
it('reads either shape', () => {
  expect(entrySql('SELECT 1')).toBe('SELECT 1'); expect(entrySql(orders)).toBe('SELECT 1')
  expect(entryConnection('SELECT 1')).toBeNull(); expect(entryConnection(orders)).toBe('warehouse')
})
it('editing the text keeps the connection and database', () => {
  expect(withSql(orders, 'SELECT 2')).toEqual({ ...orders, sql: 'SELECT 2' })
  expect(withSql('SELECT 1', 'SELECT 2')).toBe('SELECT 2')
})
it('picking a connection turns a string into a map and back', () => {
  expect(withConnection('SELECT 1', 'warehouse')).toEqual({ connection: 'warehouse', sql: 'SELECT 1' })
  expect(withConnection(orders, null)).toBe('SELECT 1')
  expect(withConnection(orders, 'warehouse')).toEqual(orders)
  expect(withConnection(orders, 'other')).toEqual({ connection: 'other', sql: 'SELECT 1' })
})
```

- [ ] **Step 2: Run:** `npm test -w frontend -- entries`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement `entries.ts`.** Run the same command. Expected: PASS.
- [ ] **Step 4: Wire the page.** `DashboardView.tsx`: `editQuery` uses `withSql`; a new `setConnection` uses `withConnection`; the widget `post` (the `/api/db/${kind}` body) sends `query: entrySql(entry)` and, for a map, `connection` and `database`; the draft restore accepts both shapes; fetch the names from `GET /api/db/connections` when the panel opens. Replace the comment `A dashboard names no connection…`. `DashboardSqlPanel.tsx`: textarea value is `entrySql`; beside the query drop-down add `<select data-testid="dash-sql-connection" aria-label="Connection">` whose first option is **Session connection** (value `''`), then `connections`, plus the entry's own connection when the list lacks it.
- [ ] **Step 5: Run** `npm test -w frontend && npm run lint -w frontend`. Expected: PASS.
- [ ] **Step 6: Commit** `Dashboard page: a query's connection, carried and picked in the SQL panel`.

### Task 7: End to end, and the docs

**Files:**
- Modify: `e2e/dashboard.spec.ts` (and `e2e/fixtures.ts` only if a helper is missing)
- Modify: `docs/dashboard.md`, `docs/api.md`, `docs/mcp.md`, `docs/gitsync.md`, `docs/export-import.md`, `docs/connect.md`, `docs/viewer_server/api.md`
- Delete: `docs/superpowers/specs/2026-11-24-query-connections-design.md`, this plan
- Modify: `docs/superpowers/plans/2026-11-24-one-run-per-page.md` (Global Constraints: one line, "a query entry may be a map naming its connection; the shared run takes a target per query")

- [ ] **Step 1: Write the failing e2e tests** in `dashboard.spec.ts`:
  - `a dashboard shows two connections side by side`: the session is on the worker's ClickHouse database; a saved Postgres connection exists; a pushed dashboard has a string query and a map query naming the Postgres connection, each bound to an element with `data-qv-query`; both elements show their seeded value.
  - `the SQL panel picks a query's connection`: open **Edit queries**, choose the Postgres connection in `dash-sql-connection`, **Execute**; the bound element shows the Postgres value; choosing **Session connection** and **Execute** shows the ClickHouse one.
- [ ] **Step 2: Run:** `npm run build:e2e -w frontend && npx playwright test --trace off e2e/dashboard.spec.ts -g "two connections|picks a query"`. Expected: PASS (Tasks 1–6 built it); if a test fails, fix the task that owns the code.
- [ ] **Step 3: Run the whole suite:** `npm run e2e -- --trace off`. Expected: PASS.
- [ ] **Step 4: Write the docs.** `dashboard.md`: rewrite the "A dashboard never names a connection" paragraph (default is the session's; a map entry names one; the three failure messages; locked connections; the no-session rule), add the entry to `queries.yaml` and the SQL panel sections, `connection`/`database` to params, the widget note. The other pages: the request and file shapes, `push_dashboard`'s refusals, the viewer server's lookup. Finish with `devpowers:shortify` on the touched pages.
- [ ] **Step 5: Delete the spec and this plan; fix links to them** (`grep -rn "query-connections" docs`).
- [ ] **Step 6: Commit** `Docs and e2e: a connection per dashboard query`.
