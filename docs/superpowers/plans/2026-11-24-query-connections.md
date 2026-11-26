# A Connection per Dashboard Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dashboard query may name the connection it runs on; a plain SQL string still runs on the session's connection.

**Architecture:** A query entry is `str | {connection, sql, database?}`. One pure module validates and reads entries. The runner takes a target (driver, config, database) per query and per `options_sql`, found through a lookup the app, the agent tools and the viewer server each supply. The frontend carries entries through unchanged and edits them in the SQL panel.

**Tech Stack:** Python 3 / FastAPI / pytest (`uv run --group test pytest`), React + TypeScript / vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-24-query-connections-design.md`

## Global Constraints

- **Every task follows the project `vmodel` skill.** Load it first. Per layer: write the statement with its `<!-- req: <slug> -->` marker, then a test that names the full ID and fails, then the code. Unit layer: the module's docstring and the test beside it, no ID. The spec's "Docs and tests, by layer" table fixes the pages and slugs.
- Never reword a slug a test names: `system/dashboard/viewing-connection`, `architecture/dashboards/runqueries`, `architecture/mcp/push-dashboard`, `architecture/mcp/run-dashboard`, `architecture/mcp/locked-refuses-both` keep their slugs while their text changes.
- A string entry behaves exactly as today in every reader. Every existing test passes unchanged, apart from call signatures this plan changes.
- Error messages, verbatim (`orders` is the query, `warehouse` the connection): `orders: unknown connection "warehouse"`, `orders: connection "warehouse" is locked`, `orders: no database selected on "warehouse"`.
- A failing connection lookup for a query is `{"ok": False, "reason": "query", "message": …}`; for a param, `reason: "params"`.
- Over MCP a locked connection reads as unknown: the agent tools never return the `is locked` message for a named connection.
- `DASHBOARD_CONCURRENCY` stays 5 per run, across connections.
- Built on today's endpoints (`/api/runqueries`, `/api/db/query`, `/api/db/describe`; viewer `/api/run`, `/api/query`, `/api/describe`). No endpoint is added.
- Repo rules (`AGENTS.md`): `uv run`, imports at the top of the file, no `__all__`, no AI attribution in commits, invented example names only (`warehouse`, `sales_reporting`).
- Every commit: `uv run python scripts/vmodel_check.py --strict` exits 0 (also the pre-commit hook). Backend tasks: `uv run ruff check backend && uv run ruff format --check backend`. Frontend tasks: `npm run lint -w frontend`. Docs edits end with `devpowers:shortify` on the touched pages.

## Review Focus

- A map entry naming the session's own active connection, with no `database`: it runs on the session's selected database, not the stored one. (Task 4)
- An `each` query on a named connection: every run goes to that connection. (Task 3)
- One param value used by queries on two dialects: each query gets its own quoting. (Task 3)
- An agent naming a locked connection: both tools answer `unknown connection`, never `is locked`. (Task 6)
- Opening the SQL panel on an entry whose connection this instance lacks, then editing its text: `connection` and `database` survive. (Task 7)

## File Structure

| File | Responsibility |
|---|---|
| `backend/queryview/dashboard_entries.py` (new) | The entry shape: validate, clean, read. Pure. |
| `backend/queryview/dashboard_params.py` | `Param.connection` / `.database`; a dialect and runner per param. |
| `backend/queryview/dashboard_queries.py` | `Target`, `Lookup`, resolving targets, running per target. |
| `backend/queryview/connect.py` | `connection_target`: a named connection for a session, with the lock and database rules. |
| `backend/queryview/app.py`, `server/main.py`, `mcp_server.py`, `yamlio.py`, `validation.py` | Callers. |
| `frontend/src/core/dashboard/entries.ts` (new) | The entry type and its pure edits. |
| `frontend/src/app/DashboardView.tsx`, `DashboardSqlPanel.tsx` | Carry and edit entries. |

---

### Task 1: Top of the V — the user and system statements and their failing browser tests

Entry layer: user. This task writes the two top layers and their tests, which fail until Task 7.

**Files:**
- Modify: `docs/requirements/queryview.md`, `docs/system/dashboard.md`
- Test: `e2e/acceptance.spec.ts`, `e2e/dashboard.spec.ts` (and `e2e/fixtures.ts` only if a helper is missing)

- [ ] **Step 1: Write the requirement** in `docs/requirements/queryview.md`, under "Live dashboard":

```md
<!-- req: dashboard-many-connections -->
A user can open one dashboard that shows data from several connections side by side.
```

- [ ] **Step 2: Write the system statements** in `docs/system/dashboard.md`: rewrite the `viewing-connection` paragraph (a query written as SQL runs on the viewing session's connection and database; the rest of its text stays); add below it `<!-- req: query-connection -->` with the map entry, `database`, the three messages, the locked rule and the no-session rule from the spec; in "The SQL panel" add `<!-- req: sql-panel-connection -->`: the **Session connection** drop-down. Add the entry to the `queries.yaml` sketch, to params (`connection`, `database` beside `options_sql`) and to the widgets note. Run shortify.
- [ ] **Step 3: Write the failing browser tests.**
  - `e2e/acceptance.spec.ts`, marker `// req: requirements/queryview/dashboard-many-connections, system/dashboard/query-connection`: the session is on the worker's ClickHouse database; a saved Postgres connection exists; a dashboard saved through `POST /api/dashboards` holds a string query and a map query naming the Postgres connection, each bound to a `data-qv-query` element; opening it shows both seeded values.
  - `e2e/dashboard.spec.ts`, marker `// req: system/dashboard/sql-panel-connection`: open **Edit queries**, pick the Postgres connection in `dash-sql-connection`, **Execute**; the bound element shows the Postgres value; pick **Session connection**, **Execute**; it shows the ClickHouse one.
- [ ] **Step 4: Run** `npm run build:e2e -w frontend && npx playwright test --trace off e2e/acceptance.spec.ts e2e/dashboard.spec.ts -g "connection"`. Expected: the two new tests FAIL (no map entries yet); the existing `viewing-connection` test PASSES. Then `uv run python scripts/vmodel_check.py --strict`: exit 0.
- [ ] **Step 5: Commit** `Docs and failing e2e: a dashboard over several connections`.

### Task 2: The entry (unit)

**Files:**
- Create: `backend/queryview/dashboard_entries.py`, `backend/queryview/test_dashboard_entries.py`
- Modify: `backend/queryview/dashboard_queries.py` (move `clean_queries` out), `backend/queryview/app.py` and `backend/queryview/mcp_server.py` (its callers), `backend/queryview/yamlio.py` (`dashboard_from_data`), `backend/queryview/validation.py` (`_entry_error`), `backend/queryview/dashboards.py` (type hints only)
- Test: also `backend/queryview/test_yamlio.py`, `backend/queryview/test_validation.py`, `backend/queryview/test_dashboards.py`

**Interfaces:**
- Produces, in `dashboard_entries.py` (module docstring states the shape and the strict/lenient split):
  - `Entry = str | dict[str, str]`
  - `map_error(entry: dict[str, Any]) -> str | None`: `sql must be a non-empty string`, `connection must be a non-empty string`, `database must be a non-empty string`, `unknown key 'x'`.
  - `queries_error(raw: object) -> str | None`: strict, for the agent tools, import and git sync. A non-mapping, a non-string name, or a value that is neither string nor mapping: `queries must be a {name: SQL} map`. A malformed map: `query 'orders': <map_error>`. Strings pass whatever they hold.
  - `clean_queries(raw: object) -> dict[str, Entry]`: lenient, for Save and run requests. Keeps non-blank strings (today's rule) and well-formed maps.
  - `entry_sql(entry: Entry) -> str`
  - `entry_connection(entry: Entry) -> tuple[str, str | None] | None`: `(connection, database)`, `None` for a string.

- [ ] **Step 1: Write the failing tests** in `test_dashboard_entries.py` (unit: no marker):

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
    assert clean_queries(raw) == {"sales": "SELECT 1", "orders": ORDERS}
    assert clean_queries("nope") == {}
```

In `test_yamlio.py`: `dashboard_from_data` accepts `{"name": "d", "html": "<p>", "queries": {"orders": ORDERS}}` and returns the entry unchanged; with `{"orders": {"sql": "SELECT 1"}}` it raises `YamlIOError` matching `query 'orders': connection must be a non-empty string`; a string-only dashboard dumps byte-identical through `dashboard_to_data`. In `test_validation.py`: a param `{"name": "r", "options_sql": "SELECT 1", "connection": "warehouse", "database": "reporting"}` has no error; `{"name": "r", "options": ["a"], "connection": "warehouse"}` errors with `invalid params[0] 'r' connection needs options_sql`; `connection: ""` errors with `invalid params[0] 'r' connection must be a non-empty string` (same wording for `database`). In `test_dashboards.py`: `POST /api/dashboards` with a map entry stores it and `GET` returns it; a malformed map beside a good string saves without the malformed one.

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_entries.py backend/queryview/test_yamlio.py backend/queryview/test_validation.py backend/queryview/test_dashboards.py -q`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement.** Move `clean_queries` from `dashboard_queries.py` into the new module; `app.py` and `mcp_server.run_dashboard` import it from there. `yamlio.dashboard_from_data`: replace the inline check with `queries_error`, keeping the `malformed {where}: ` prefix. `validation._entry_error`: the two param rules.
- [ ] **Step 4: Run the same command, then `uv run --group test pytest backend/queryview scripts -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `Dashboards: a query entry may be a map naming its connection`.

### Task 3: A target per query and per param (unit)

**Files:**
- Modify: `backend/queryview/dashboard_params.py`, `backend/queryview/dashboard_queries.py`, `backend/queryview/mcp_server.py` and `backend/queryview/server/main.py` (call sites only, behavior unchanged until Tasks 4–6)
- Test: `backend/queryview/test_dashboard_params.py`, `backend/queryview/test_dashboard_queries.py`

**Interfaces:**
- Consumes: `Entry`, `entry_sql`, `entry_connection` (Task 2).
- Produces, in `dashboard_params.py` (docstring: "The caller passes a dialect per query and per param"):
  - `Param` gains `connection: str | None = None`, `database: str | None = None`, read by `_parse_entry` only beside `options_sql`.
  - `Runner = Callable[[Param, str], Awaitable[list[Any]]]`
  - `resolve(params, values, run: Runner, dialects: Mapping[str, Dialect])`: `dialects[p.name]` quotes param `p`'s `options_sql`. Only params with `options_sql` are looked up.
  - `apply_to_queries(queries: dict[str, str], params, resolved, dialects: Mapping[str, Dialect])`: `dialects[query_name]`.
- Produces, in `dashboard_queries.py` (docstring: queries run on the session's connection unless their entry names one):
  - `@dataclass(frozen=True) class Target: driver: Driver; config: DriverConfig; database: str | None`
  - `Lookup = Callable[[str, str | None], Awaitable[Target | str]]`: a connection name and an entry's `database` to its target, or the message without the query's name (`unknown connection "warehouse"`).
  - `run_queries_on(targets: Mapping[str, Target], queries: Mapping[str, str | dict[str, str]], limit: int = DASHBOARD_ROW_CAP, offset: int = 0) -> dict[str, Any]`: `targets[query_name]`.
  - `run_dashboard_on(default: Target | None, lookup: Lookup, queries: dict[str, Entry], params: object, values: dict[str, str], limit: int = DASHBOARD_ROW_CAP) -> dict[str, Any]`. A string entry, or an `options_sql` with no connection, uses `default`. Each `(connection, database)` pair is looked up once. A query's failed lookup returns `{"ok": False, "reason": "query", "message": f"{name}: {message}"}` for the first failing query in the given order, with `params` attached as a failing query has today; a param's returns the params error `f"{name}: {message}"`.
  - `resolve_on(default: Target | None, lookup: Lookup, params: list[Param], values) -> list[dict[str, Any]]`.
  - `needs_default(queries: dict[str, Entry], params: object) -> bool`: whether any string entry or connection-less `options_sql` is present.

- [ ] **Step 1: Write the failing tests** in `test_dashboard_queries.py` (unit: no marker), using two `_SeenDriver`s, the second a subclass with `ident_quote = "`"` and `backslash_escapes = True`:

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
    assert not needs_default(q, [])
    assert asyncio.run(run_dashboard_on(None, lookup, q, [], {}))["ok"]
```

In `test_dashboard_params.py`: `parse_params` reads `connection`/`database` beside `options_sql` and ignores them elsewhere; existing `resolve` and `apply_to_queries` tests pass a mapping where they passed one dialect.

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_queries.py backend/queryview/test_dashboard_params.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `run_dashboard_on`: parse params; look up every distinct connection a param or entry names; resolve params with a runner that runs on the param's target; substitute per query dialect; run with `targets`. Update `run_dashboard_queries`, `run_dashboard`, `session_sql` and `server/main.py`'s three call sites to the new signatures with a lookup that answers `unknown connection "…"` for every name, so behavior is unchanged.
- [ ] **Step 4: Run** `uv run --group test pytest backend/queryview scripts -q`. Expected: PASS.
- [ ] **Step 5: Commit** `Dashboards: run each query and options_sql on its own target`.

### Task 4: The app (integration)

**Files:**
- Modify: `docs/architecture/dashboards.md`, `docs/architecture/api.md`, `docs/system/connect.md` (one line: a dashboard naming a locked connection needs the tab's token)
- Modify: `backend/queryview/connect.py`, `backend/queryview/dashboard_queries.py` (`run_dashboard`, `run_dashboard_queries`, `session_sql`), `backend/queryview/app.py` (`/api/runqueries`, `/api/db/query`, `/api/db/describe`)
- Test: `backend/queryview/test_dashboard_queries.py`, `backend/queryview/test_api_db.py`, `backend/queryview/test_locked_connections.py`

**Interfaces:**
- Consumes: `Target`, `Lookup`, `run_dashboard_on`, `needs_default` (Task 3); `clean_queries` (Task 2).
- Produces:
  - `connect.connection_target(sid: str, name: str, database: str | None) -> tuple[str, DriverConfig, str | None] | str`: `(type, config, database)` or one of the three messages without the query's name. Resolution `_resolve(sid, name)`; a saved connection with a lock hash needs `_is_unlocked(sid, name)`; database is the argument, else the session's selected one when `name` is its active connection, else the stored row's; none on a `requires_database` driver is the third message.
  - `dashboard_queries.session_lookup(sid: str) -> Lookup` wrapping it into `Target`.
  - `run_dashboard(sid, queries: dict[str, Entry], params, values, limit=…)` and `run_dashboard_queries(sid, queries: dict[str, Entry], …)`: the session gate runs only when `needs_default`; when it refuses, the whole call fails as today.
  - `/api/db/query` and `/api/db/describe` accept optional body fields `connection` and `database` (strings). With `connection` the request runs on `connection_target` instead of the session gate; a failed lookup is `400 {"ok": false, "reason": "query", "message": 'unknown connection "nope"'}`. Without it, both routes are untouched.

- [ ] **Step 1: Write the statements.** `architecture/dashboards.md`: extend `runqueries` (an entry naming a connection runs there) and add `<!-- req: named-connection -->` with the lookup order, the database rule, the lock and per-connection quoting. `architecture/api.md`: the two new fields on `/api/db/query` and `/api/db/describe`. Run shortify.
- [ ] **Step 2: Write the failing tests**, each marked `# req: architecture/dashboards/named-connection`. In `test_dashboard_queries.py`, with `rowsfake` and a second registered driver type saved as connection `warehouse` through `connect.connect_new` on another session:
  - `test_a_named_saved_connection_runs_from_any_session`: session `s-a` on `main`; `{"orders": {"connection": "warehouse", "sql": "SELECT 2"}}` reaches warehouse's driver.
  - `test_all_named_queries_need_no_session`: a never-connected sid, `out["ok"] is True`.
  - `test_a_mixed_dashboard_still_needs_the_session`: never-connected sid with one string entry, `out["reason"] == "no-session"` and nothing ran on warehouse.
  - `test_naming_the_sessions_own_connection_uses_its_selected_database`: the session selected `today`, the stored row says `yesterday`; the driver saw `today`.
  - `test_the_entrys_database_wins`.
  - `test_a_connection_that_needs_a_database_and_has_none`: `orders: no database selected on "warehouse"`.

  In `test_locked_connections.py`: `test_a_dashboard_reaches_a_locked_connection_only_with_the_token`: another session's run returns `orders: connection "warehouse" is locked`; the locking session's run succeeds. In `test_api_db.py` (marked also `architecture/dashboards/runqueries`): `/api/runqueries` with a map entry returns its rows; a malformed map beside a string runs only the string; `/api/db/query` with `connection` returns that connection's rows, and an unknown one the 400 above; `/api/db/describe` likewise.
- [ ] **Step 3: Run:** `uv run --group test pytest backend/queryview/test_dashboard_queries.py backend/queryview/test_api_db.py backend/queryview/test_locked_connections.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** as in Interfaces. In the two `/api/db/*` routes, the `connection` branch substitutes with `ready_sql(sql, params, values, dialect_of(target.driver))` when `params` is in the body and calls the target driver's `run_query` / `export_csv` / `describe_query` directly, shaping the reply as the session branch does.
- [ ] **Step 5: Run** `uv run --group test pytest backend/queryview scripts -q` and `uv run python scripts/vmodel_check.py --strict`. Expected: PASS, exit 0.
- [ ] **Step 6: Commit** `App: dashboard queries run on the connections they name`.

### Task 5: The viewer server (integration)

**Files:**
- Modify: `docs/architecture/viewer_server_api.md`, `backend/queryview/server/main.py`
- Test: `backend/queryview/server/test_main.py`

**Interfaces:**
- Consumes: `Target`, `Lookup`, `run_dashboard_on`, `resolve_on` (Task 3); `entry_sql`, `entry_connection` (Task 2).
- Produces: no new names. `/api/run`, `/api/query` and `/api/describe` look a map entry's connection up in `config.connections`; its database is the entry's, else the configured one. A string entry runs on the request's `connection`, as today. `GET /api/dashboards/{name}` still returns query names only.

- [ ] **Step 1: Write the statement** `<!-- req: named-connection -->` in `viewer_server_api.md`. Run shortify.
- [ ] **Step 2: Write the failing tests**, marked `# req: architecture/viewer_server_api/named-connection`, with a second sqlite connection `warehouse` in the config and a repo dashboard holding `orders: {connection: warehouse, sql: …}` beside a string query:
  - `test_a_query_runs_on_the_connection_it_names`: `POST /api/run` on `local` returns `orders` rows only `warehouse`'s file holds, and the string query's rows from `local`.
  - `test_a_query_naming_an_unconfigured_connection_fails_by_name`: `orders: unknown connection "nope"`.
  - `test_a_widget_pages_on_its_querys_connection`: `/api/query` and `/api/describe` for `orders` answer from `warehouse`.
  - `test_the_dashboard_listing_never_carries_an_entry` (also `architecture/viewer_server_api/names-not-sql`): `GET /api/dashboards/sales` has `queries == ["total", "orders"]`.
- [ ] **Step 3: Run:** `uv run --group test pytest backend/queryview/server -q`. Expected: FAIL.
- [ ] **Step 4: Implement.** One lookup closure over `config.connections`; `_widget_sql` returns the SQL with its target.
- [ ] **Step 5: Run** `uv run --group test pytest backend/queryview scripts -q`. Expected: PASS.
- [ ] **Step 6: Commit** `Viewer server: a query runs on the configured connection it names`.

### Task 6: The agent tools (integration)

**Files:**
- Modify: `docs/architecture/mcp.md` (`push-dashboard`, `run-dashboard`, `locked-refuses-both`), `backend/queryview/mcp_server.py`
- Test: `backend/queryview/test_mcp_dashboards.py`, `backend/queryview/test_mcp_connections.py`

**Interfaces:**
- Consumes: `queries_error`, `entry_connection` (Task 2); `session_lookup`, `needs_default` (Tasks 3–4); `agent_connections_for`, `_AGENT_DRIVERS` (existing).
- Produces:
  - `mcp_server._agent_lookup(session_id: str) -> Lookup`: a name absent from `agent_connections_for(session_id)` (unknown, or locked and so hidden) answers `unknown connection "x"`; a listed one not agent-created with a type outside `_AGENT_DRIVERS` answers `use_connection`'s message; otherwise `session_lookup`'s answer.
  - `run_dashboard(queries: dict[str, str | dict[str, str]] | None, …)`: refuses `queries_error`; runs with `_agent_lookup`; needs no session connection when `not needs_default(...)`.
  - `push_dashboard(queries: dict[str, str | dict[str, str]] | None, …)`: refuses `queries_error`; for each connection a query or a param names, refuses the push with `_agent_lookup`'s message, prefixed by the query or param name; drops the `not connected` refusal when `not needs_default(...)`.

- [ ] **Step 1: Write the statements** in `architecture/mcp.md`: both tools take either entry shape and hold a named connection to `use_connection`'s rules; `locked-refuses-both` gains that a named locked connection reads as unknown. Update both tools' docstrings ("a dashboard never names a connection" goes; `queries.yaml (a {name: SQL} map)` names both shapes). Run shortify.
- [ ] **Step 2: Write the failing tests.** In `test_mcp_dashboards.py`, marked `# req: architecture/mcp/run-dashboard`: `test_a_query_runs_on_the_connection_it_names`, `test_a_disconnected_session_runs_named_queries`, `test_a_file_connection_the_agent_did_not_add_is_refused`, `test_a_malformed_entry_is_refused` (`query 'orders': connection must be a non-empty string`). In `test_mcp_connections.py`, marked `# req: architecture/mcp/push-dashboard`: `test_push_takes_a_query_naming_a_connection` (the pushed event carries the entry), `test_push_refuses_a_file_connection_the_agent_did_not_add`, `test_push_refuses_an_unknown_connection`, one through `dir` with a map entry in `queries.yaml`. Marked `# req: architecture/mcp/locked-refuses-both`: `test_a_locked_connection_named_by_a_query_reads_as_unknown`, for both tools, asserting the message is `orders: unknown connection "warehouse"` and contains no `locked`.
- [ ] **Step 3: Run:** `uv run --group test pytest backend/queryview/test_mcp_dashboards.py backend/queryview/test_mcp_connections.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** as in Interfaces.
- [ ] **Step 5: Run** `uv run --group test pytest backend/queryview scripts -q`. Expected: PASS.
- [ ] **Step 6: Commit** `MCP: push_dashboard and run_dashboard take queries naming a connection`.

### Task 7: The dashboard page, and up the V

**Files:**
- Create: `frontend/src/core/dashboard/entries.ts`, `frontend/src/core/dashboard/entries.test.ts`
- Modify: `frontend/src/core/index.ts` (export, as its neighbours are), `frontend/src/app/DashboardView.tsx`, `frontend/src/app/DashboardSqlPanel.tsx`
- Modify: `docs/system/gitsync.md`, `docs/system/export-import.md` (the file shapes)
- Delete: `docs/superpowers/specs/2026-11-24-query-connections-design.md`, this plan
- Modify: `docs/superpowers/plans/2026-11-24-one-run-per-page.md` (Global Constraints: "a query entry may be a map naming its connection; the shared run takes a target per query")

**Interfaces:**
- Produces, in `entries.ts` (leading comment states the shape):
  - `type QueryEntry = string | { connection: string; sql: string; database?: string }`
  - `entrySql(e: QueryEntry): string`, `entryConnection(e: QueryEntry): string | null`
  - `withSql(e: QueryEntry, sql: string): QueryEntry`: a string stays a string; a map keeps its other keys.
  - `withConnection(e: QueryEntry, connection: string | null): QueryEntry`: `null` gives the bare SQL string; a name gives a map, keeping `database` only when the name is unchanged.
- `DashboardPush.queries` and the panel's `queries` prop become `Record<string, QueryEntry>`. The panel gains `onConnection: (name: string, connection: string | null) => void` and `connections: string[]`.

- [ ] **Step 1: Write the failing unit tests** in `entries.test.ts` (no marker):

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

- [ ] **Step 2: Run:** `npm test -w frontend -- entries`. Expected: FAIL, module not found. Implement `entries.ts`; run again: PASS.
- [ ] **Step 3: Wire the page.** `DashboardView.tsx`: `editQuery` uses `withSql`; a new `setConnection` uses `withConnection`; the widget `post` (the `/api/db/${kind}` body) sends `query: entrySql(entry)` and, for a map, `connection` and `database`; the draft restore accepts both shapes; the panel's names come from `GET /api/db/connections` when it opens. Replace the comment `A dashboard names no connection…`. `DashboardSqlPanel.tsx`: the textarea shows `entrySql`; beside the query drop-down, `<select data-testid="dash-sql-connection" aria-label="Connection">` with **Session connection** (value `''`) first, then `connections`, plus the entry's own connection when the list lacks it.
- [ ] **Step 4: Go up.** Side by side: `uv run --group test pytest backend/queryview scripts`, `npm test -w frontend && npm run lint -w frontend`, `npm run build:e2e -w frontend && npx playwright test --trace off e2e/acceptance.spec.ts e2e/dashboard.spec.ts e2e/widgets.spec.ts e2e/server.spec.ts e2e/remote.spec.ts`, then `uv run python scripts/vmodel_check.py --strict`. Expected: all PASS, including Task 1's two browser tests; exit 0. A failure goes back down the V to the layer where it starts (vmodel step 5).
- [ ] **Step 5: Run the whole browser suite:** `npm run e2e -- --trace off`. Expected: PASS.
- [ ] **Step 6: Finish the docs** (`gitsync.md`, `export-import.md` file shapes; shortify), delete the spec and this plan, update the one-run-per-page plan, and fix links (`grep -rn "query-connections" docs`).
- [ ] **Step 7: Commit** `Dashboard page: a query's connection, carried and picked in the SQL panel`.
