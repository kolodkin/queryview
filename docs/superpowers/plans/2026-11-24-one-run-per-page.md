# One Run for a Dashboard Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `POST /api/run` serves every dashboard request in the app and the viewer server, and the page re-runs only what depends on a change.

**Architecture:** A shared backend function runs the queries it is asked for, resolves only the params they use, and returns per-query results plus a dependency map (`uses`). A shared frontend layer holds the page's params and results, batches the asks of one change into one call, and answers the frame's widgets from what it holds. The two pages differ only in a transport function.

**Tech Stack:** Python 3.11, FastAPI, pytest; React, TypeScript, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-24-one-run-per-page-design.md`. Read it first; this plan argues from it.

## Global Constraints

- The viewer server never accepts SQL and never puts an unchecked value into SQL.
- The browser never parses SQL or `{placeholders}`: dependencies come from `uses`.
- Both servers check each value against its param's options (the app too).
- A dashboard is federated (every query and `options_sql` names a connection) or not; the shared run takes a target per query and returns `connections` for a federated one (see `docs/architecture/dashboards.md`, `named-connection`).
- `window.queries`, `window.params`, `setParams`, `<qv-select-view>`, `<qv-param>` keep their meaning for dashboard authors.
- Explorer and Scripts keep `/api/db/query` and `/api/db/describe`.
- A query's page defaults to no sort, offset 0, limit 1000 (`DASHBOARD_ROW_CAP`); a given limit is clamped to 1..1000.
- At most 5 queries of one call in flight (`DASHBOARD_CONCURRENCY`).
- Repo rules: `uv run`, imports at file top, no `__all__`, invented example names only, no AI attribution in commits. Load the project `vmodel` skill before adding a test and before editing docs.
- Old endpoints and code paths stay working until Task 8 removes them, so every task leaves the app and the viewer usable.

## Review Focus

1. **A slow reply after a newer one** (two quick param changes): the older reply must not overwrite newer params or results. Test in Task 4.
2. **A widget ask that arrives after the batch was sent:** it costs a second call and still gets its rows. Test in Task 4.
3. **A whole-call failure during a change** (failing `options_sql`, session gate): the page keeps its previous state, shows the message, and no widget stays busy. Test in Task 5.
4. **The dashboard is switched while a call is in flight:** the reply is dropped, nothing from the old dashboard reaches the new frame. Test in Task 5.
5. **A query or param named like an object member** (`constructor`, `__proto__`): looked up as a name, never as a property. Tests in Tasks 2 and 4.

---

### Task 1: The dependency map

**Files:**
- Modify: `backend/queryview/dashboard_params.py`
- Test: `backend/queryview/test_dashboard_params.py`

**Interfaces:**
- Consumes: `placeholders_in`, `Param` (same module).
- Produces: `uses(queries: dict[str, str], params: list[Param]) -> dict[str, dict[str, list[str]]]`. Returns `{"queries": {name: [param, …]}, "params": {param: [param, …]}}`: for each query and each given param, the declared params it references directly, in order of first appearance. Every key is present, with `[]` when it references none. A placeholder that names no declared param is left out.

- [ ] **Step 1: Write the failing test**

```python
def test_uses_maps_queries_and_params_to_the_params_they_reference():
    params = parse_params(
        [
            {"name": "region", "options": ["eu", "us"]},
            {"name": "city", "options_sql": "SELECT city FROM orders WHERE region = {region}"},
            {"name": "sort_col", "kind": "identifier", "options": ["amount"]},
        ]
    )
    queries = {"rows": "SELECT * FROM orders WHERE region = {region} ORDER BY {sort_col}", "plain": "SELECT '{nope}'"}
    assert uses(queries, params) == {
        "queries": {"rows": ["region", "sort_col"], "plain": []},
        "params": {"region": [], "city": ["region"], "sort_col": []},
    }
```

- [ ] **Step 2: Run it:** `uv run --group test pytest backend/queryview/test_dashboard_params.py -k uses -q`. Expected: FAIL, `uses` not defined.
- [ ] **Step 3: Implement `uses` in `dashboard_params.py`.**
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit** `Dashboard params: a dependency map of what each query and param references`.

### Task 2: The shared run

**Files:**
- Modify: `backend/queryview/dashboard_queries.py`
- Test: `backend/queryview/test_dashboard_queries.py` (reuse the fake driver defined at its top)

**Interfaces:**
- Consumes: `uses`, `needed`, `parse_params`, `missing`, `substitute` (Task 1 and `dashboard_params.py`); `resolve_on`, `_no_options`, `dialect_of`, `DASHBOARD_ROW_CAP`, `DASHBOARD_CONCURRENCY`; `page_bounds` from `validation.py`.
- Produces:

```python
@dataclass(frozen=True)
class QueryAsk:
    name: str
    limit: int = DASHBOARD_ROW_CAP
    offset: int = 0
    order_by: list[dict[str, Any]] | None = None
    csv: bool = False

Target = tuple[Driver, DriverConfig, str | None]        # driver, config, database
Resolve = list[str] | Literal["all"]

def parse_asks(raw: object) -> list[QueryAsk] | None     # None: not a list of {name, …} objects
def parse_resolve(raw: object) -> Resolve                # "all", a list of strings, else []
def needs_database(params: object, asks: list[QueryAsk], resolve: Resolve) -> bool
async def run_page(target: Target | None, sql: dict[str, str], params: object,
                   asks: list[QueryAsk], resolve: Resolve, values: dict[str, str]) -> dict[str, Any]
```

`run_page` returns either `{"ok": True, "results": [...], "params": [...], "uses": {...}}` or `{"ok": False, "reason": "params" | "unknown-query", "message": str}`.

Rules the tests pin:
- `parse_asks`: `limit` absent means `DASHBOARD_ROW_CAP`; a given `limit`/`offset` goes through `page_bounds`; `order_by` is kept when it is a list; `format == "csv"` sets `csv`.
- Params resolved: those the asked queries use (`needed`), plus those `resolve` names with the params their `options_sql` reference; `"all"` means every declared param. `params` in the reply lists exactly these, in declaration order.
- `needs_database` is true when there is an ask, or any param that would be resolved has an `options_sql`. `run_page(None, …)` is called only when it is false and resolves with `_no_options`.
- An ask naming a query not in `sql` (checked with `in` on the dict, so `constructor` is just a missing name) fails the whole call: `reason: "unknown-query"`, message `unknown query`.
- A `ParamError` while resolving or substituting an `options_sql` fails the whole call: `reason: "params"`.
- Each result is one of `{"name", "ok": True, "meta": [{name, type}], "data": [[…]]}`, `{"name", "ok": True, "output": csv_text}`, `{"name", "ok": False, "message"}`, `{"name", "ok": False, "waiting": True}`, in the order asked. A failing query does not stop the others; a `ParamError` substituting one query (unknown cast) is that query's `message`.
- `uses` covers the asked queries and the resolved params.

- [ ] **Step 1: Write the failing tests.** Name them as below; each builds a dashboard with params `region` (`options_sql`), `city` (`options_sql` referencing `{region}`, `default: none`), `sort_col` (static identifier), `year` (`options_sql`, used by no asked query), and records every SQL the fake driver receives.

```python
def test_run_page_resolves_only_what_the_asks_use():        # ask "rows" (uses region, sort_col): driver sees region's options_sql + rows; not city's, not year's
def test_run_page_resolve_all_resolves_every_param():       # resolve="all", no asks: params == all four, in declaration order
def test_run_page_resolve_names_a_param_and_what_it_references():  # resolve=["city"]: region and city resolved
def test_run_page_pages_sorts_and_exports():                # limit/offset/order_by reach the driver; csv=True returns {"output": …}
def test_run_page_one_failing_query_fails_alone():          # results: [ok, {"ok": False, "message": …}, ok]
def test_run_page_reports_a_waiting_query():                # query using {city}, no city chosen: {"ok": False, "waiting": True}, driver never sees it
def test_run_page_unknown_query_fails_the_call():           # including the name "constructor"
def test_run_page_failing_options_sql_fails_the_call():     # reason == "params"
def test_run_page_value_outside_options_never_reaches_sql() # values={"region": "' OR 1=1 --"}: rows runs with the first option
def test_run_page_without_a_target_resolves_static_params() # needs_database False; run_page(None, …) returns params, no driver
def test_run_page_returns_uses()                            # equals uses({asked}, resolved params)
def test_parse_asks_bounds_and_defaults()                   # absent limit → 1000; limit 5000 → 1000; limit 0 → 100; not a list → None
```

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_dashboard_queries.py -k "run_page or parse_asks" -q`. Expected: FAIL, names not defined.
- [ ] **Step 3: Implement the names above in `dashboard_queries.py`.** Run the asks under one `asyncio.Semaphore(DASHBOARD_CONCURRENCY)` with `asyncio.gather`; no cancellation on failure. Use `driver.export_csv` for `csv` asks and `driver.run_query` otherwise.
- [ ] **Step 4: Run the same command.** Expected: PASS. Then `uv run --group test pytest backend/queryview -q`: all pass.
- [ ] **Step 5: Commit** `Dashboards: one shared run for the queries a page asks for`.

### Task 3: The app's `/api/run`

**Files:**
- Modify: `backend/queryview/dashboard_queries.py`, `backend/queryview/app.py`
- Test: `backend/queryview/test_api_db.py` (reuse `_duck` and `REGION`), `backend/queryview/test_dashboards.py`, `backend/queryview/test_locked_connections.py`

**Interfaces:**
- Consumes: Task 2's names; `_gated_session`; `_clean_queries`, `clean_values`, `dashboard_params_error`.
- Produces: `async def run_page_for_session(sid: str, sql, params, asks, resolve, values) -> dict[str, Any]` in `dashboard_queries.py` (skips the session gate when `needs_database` is false; otherwise the gate's failure reply or `run_page`), and the route `POST /api/run` in `app.py`.

Request body: `{sql: {name: SQL}, params: [...], queries: [{name, limit?, offset?, order_by?, format?}], resolve?: "all" | [name], values?: {name: string}}`.
Statuses: `200` on `ok`; `400` for a malformed body (`queries` not a list of objects: message `queries must be a list`) and for `reason: params`; `404` for `unknown-query`; `409` for `no-session` / `no-database`; `403` for `locked`. The body of a failure is `{ok: false, message, reason}`. When `dashboard_params_error(params)` returns a message, the reply (success or failure) carries it as `warning`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_run_returns_rows_params_and_uses(tmp_path):              # 200; results[0] == {"name": "q", "ok": True, "meta": [...], "data": [["us"]]}; uses present
def test_run_checks_a_value_against_its_options(tmp_path):        # values {"r": "nope"}: the query runs with "eu"
def test_run_a_failing_query_is_still_a_200(tmp_path):            # results[0]["ok"] is False
def test_run_a_bad_cast_is_that_querys_failure(tmp_path):         # "SELECT {r:nope}": results[0]["message"] == "unknown cast for {r}: nope"
def test_run_unknown_query_is_404_and_bad_body_is_400(tmp_path)
def test_run_names_a_malformed_param(tmp_path):                   # warning starts "invalid params[0] 'bad' kind"
# test_dashboards.py
def test_run_resolves_static_params_on_a_disconnected_session():  # 200 with params, no session
def test_run_on_a_disconnected_session_is_409():                  # one ask: 409, reason "no-session"
# test_locked_connections.py: add /api/run to the routes the existing locked test covers (403)
```

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/test_api_db.py backend/queryview/test_dashboards.py backend/queryview/test_locked_connections.py -k "run_" -q`. Expected: FAIL with 404 (no route).
- [ ] **Step 3: Implement `run_page_for_session` and the route.** `/api/runqueries` stays untouched.
- [ ] **Step 4: Run the same command, then the whole backend suite and `uv run ruff check backend && uv run ruff format --check backend`.** Expected: PASS.
- [ ] **Step 5: Commit** `App: POST /api/run`.

### Task 4: The page's run state (pure frontend logic)

**Files:**
- Create: `frontend/src/core/dashboard/pageRun.ts`, `frontend/src/core/dashboard/pageRun.test.ts`
- Modify: `frontend/src/core/dashboard/widgetChannel.ts` (+ its test), `frontend/src/core/index.ts`

**Interfaces:**
- Consumes: `ResolvedParam`, `valuesOf`, `withKeptText` (`params.ts`); `OrderCol`, `ColumnMeta`, `Cell`; `parseOrderByAttr`, `widgetQueryNames` (`widgetChannel.ts`).
- Produces (all exported from `pageRun.ts` unless noted):

```ts
export type Ask = { name: string; limit?: number; offset?: number; order_by?: OrderCol[]; format?: 'csv' }
export type QueryResult = { name: string } & (
  | { ok: true; meta: ColumnMeta[]; data: Cell[][] }
  | { ok: true; output: string }
  | { ok: false; message: string }
  | { ok: false; waiting: true })
export type Uses = { queries: Record<string, string[]>; params: Record<string, string[]> }
export type RunRequest = { queries: Ask[]; resolve?: 'all' | string[]; values: Record<string, string> }
export type RunReply =
  | { ok: true; results: QueryResult[]; params: ResolvedParam[]; uses: Uses; warning?: string }
  | { ok: false; message: string; reason?: string }
export type Transport = (req: RunRequest) => Promise<RunReply>

// The values of the params `names` lists, by name: a node's inputs.
export function inputsOf(names: string[], params: ResolvedParam[]): Record<string, string>
export function sameInputs(a: Record<string, string>, b: Record<string, string>): boolean
// `resolved` merged into `current` by name; new names keep the reply's order.
export function mergeParams(current: ResolvedParam[], resolved: ResolvedParam[]): ResolvedParam[]
export function mergeUses(current: Uses, next: Uses): Uses
// A rows result as window.queries wants it: {column: values[]}.
export function toColumns(r: Extract<QueryResult, { meta: ColumnMeta[] }>): Record<string, unknown[]>
// The params to re-resolve after `changed`: those names and every param that references one, transitively.
export function paramsReached(changed: string[], uses: Uses): string[]
// Whether a query whose result ran with `ranWith` must run again under `params`.
export function isStale(name: string, ranWith: Record<string, string> | null, uses: Uses, params: ResolvedParam[]): boolean

export type Batcher = {
  query(ask: Ask): Promise<QueryResult>      // identical asks in one batch share one entry
  resolve(names: 'all' | string[]): void
  idle(): Promise<void>                      // resolves when no call is pending or in flight
}
// Collects asks until `schedule` fires, then sends one call with `values()`.
// `onReply` gets each reply with its request and a sequence number rising per call.
export function createBatcher(
  transport: Transport,
  values: () => Record<string, string>,
  onReply: (reply: RunReply, request: RunRequest, seq: number) => void,
  schedule?: (flush: () => void) => void,    // default: setTimeout(flush, 0)
): Batcher
```

- In `widgetChannel.ts`: `export function viewsInHtml(html: string): { view: string; ask: Ask }[]`. One entry per `<qv-select-view>` tag with a `query`, in document order; `view` is `v0`, `v1`, …; `ask` is `{name, limit, offset: 0, order_by}` with `limit` from the tag's `limit` attribute (default 100, clamped to 1..`MAX_LIMIT`) and `order_by` from `order-by` via `parseOrderByAttr`.
- Maps keyed by query or param names are read with `Object.hasOwn`.
- A whole-call failure rejects nothing: each `query()` promise of that batch resolves to `{name, ok: false, message}` with the reply's message.

- [ ] **Step 1: Write the failing tests** in `pageRun.test.ts` and `widgetChannel.test.ts`:

```ts
test('one batch makes one call: params become resolve, asks become queries')
test('identical asks in one batch share one entry and one result')
test('an ask after the batch was sent goes in a second call and is answered')   // Review Focus 2
test('a failed call answers every ask of its batch with the message')
test('replies carry a rising sequence number')                                    // the caller drops an older one: Review Focus 1
test('paramsReached follows options_sql references transitively')               // region → city → district
test('isStale: true with no result, true when a used value differs, false when only an unused param changed')
test('a server-corrected value causes no second run')   // ranWith {city: "Paris"}, params now city "Paris" after the reply: isStale false
test('mergeParams replaces by name and keeps the order')
test('inputsOf and isStale treat "constructor" as a name')                        // Review Focus 5
test('toColumns turns rows into columns, an empty result into empty columns')
// widgetChannel.test.ts
test('viewsInHtml reads query, limit and order-by of each tag, in order')
test('viewsInHtml defaults limit to 100 and skips a tag with no query')
```

- [ ] **Step 2: Run:** `npm test -w frontend -- pageRun widgetChannel`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement.** No React in this file.
- [ ] **Step 4: Run the same command, then `npm run lint -w frontend`.** Expected: PASS.
- [ ] **Step 5: Commit** `Core: the dashboard page's run state and batching`.

### Task 5: The page runner and the frame's inputs

**Files:**
- Create: `frontend/src/core/dashboard/PageRunner.tsx`, `frontend/src/core/dashboard/pageRunner.test.ts`
- Modify: `frontend/src/core/dashboard/srcDoc.ts` (+ test), `DashboardFrame.tsx`, `widgetChannel.ts` (+ test), `frameHost.ts` (+ test), `frontend/src/core/widgets/SelectView.tsx`, `frameChannel.ts`, `frontend/src/core/index.ts`

**Interfaces:**
- Consumes: everything Task 4 produces; `listenToFrame`, `markedRuns`, `answerWidget` shapes in `frameHost.ts`.
- Produces:

```ts
// srcDoc.ts: the frame also gets window.uses and window.revs ({query: number}).
export function buildSrcDoc(html, results, params = [], theme = {}, uses: Uses = { queries: {}, params: {} }): string
// DashboardFrame gains an optional `uses` prop, passed through.

// widgetChannel.ts: widget-query and widget-describe carry `view`, a string of at most 20 characters; parseWidgetRequest rejects one without it.

// PageRunner.tsx
export type PageRunnerOptions = {
  transport: Transport | null                 // null: nothing is open
  html: string
  own: string[]                               // the page's own query names (not a widget's)
  frames: () => { id: string; frame: HTMLIFrameElement | null }[]   // e.g. [{id: 'page', …}, {id: 'popup', …}]
  loadKey: string                             // a new value starts a fresh load
  onError: (message: string | null) => void
}
export type PageRunnerState = {
  results: DashboardResults | null            // null until the load has answered, or when it failed
  params: ResolvedParam[]
  uses: Uses
  loading: boolean
  loadSeq: number                             // rises per successful load: the frame's key
  rerun: (names: string[] | null) => void     // Execute: those queries, or everything
}
export function usePageRunner(o: PageRunnerOptions): PageRunnerState

// The pure core of the runner, so it is testable without rendering React:
export function createPageRunner(transport: Transport, html: string, own: string[], post: (frameId: string | null, message: unknown) => void, onError: (m: string | null) => void): {
  load(): Promise<{ ok: true; results: DashboardResults; params: ResolvedParam[]; uses: Uses } | { ok: false; message: string }>
  setParams(values: Record<string, string>): Promise<void>
  rerun(names: string[] | null): Promise<void>
  widget(frameId: string, req: WidgetRequest): Promise<WidgetReply | null>
  dispose(): void                             // every later reply is dropped
}
```

Behaviour the tests pin (spec sections "The dependency tree in the page", "Widgets and the frame", "Errors"):
- **Load** is one call: `resolve: 'all'`, the `own` queries, and one ask per `viewsInHtml(html)` entry. A failing own query makes `load()` return `{ok: false, message: "<name>: <message>"}`; a waiting own query is left out of `results`.
- **`setParams(values)`** sends `withKeptText(values, params)`. One call: `resolve` is `paramsReached(changed)`, `queries` are the own queries and held widget views that use a changed param, widget views at offset 0. If the reply changes another param's value, the queries stale under the new params go in one more call. Then it posts one `params-results` message to every frame (`post(null, …)`): `{type, ok, results, params, uses, revs, queries, message?}`, where `results` is the whole `window.queries` map (a failing own query keeps its previous entry), `queries` names the queries that ran, and `message` is the first failure.
- **`rerun(names)`** bumps `revs[name]` for each, runs those own queries and held widget views (all when `null`), and posts `params-results` the same way.
- **`widget(frameId, req)`**: a view is identified by `${frameId}:${req.view}` and holds its latest ask and result. An ask equal to what the view holds and not stale is answered from it with no call. Otherwise it goes through the batch and replaces the view's ask. The views `load()` created are `page:v0`, `page:v1`, …. `widget-describe` is answered from the view's `meta` as `{name, type}` fields, running the view's ask first when it has no result. `widget-csv` is sent with `format: 'csv'` and never kept.
- **A whole-call failure** on `setParams` or `rerun` keeps the previous state, calls `onError(message)`, and posts `params-results` with `ok: false`.
- **A reply with a lower sequence number** than one already applied does not change params or own results.
- **After `dispose()`** nothing is posted and no state changes.
- `usePageRunner` creates a runner per `loadKey`, disposes the previous one, and wires `listenToFrame` to `widget` and `setParams` through `markedRuns`. It holds no dependency logic of its own: what has no element (the own queries, the params) is an entry in the runner's state, judged by the same `isStale` rule a widget element applies to its inputs.
- **In the frame:** `params-results` stores `d.uses` in `window.uses` and `d.revs` in `window.revs` when present. `SelectView` computes its inputs from `window.params`, `window.uses.queries[query]` and `window.revs[query]`, re-reads them on `params-results`, and when they change returns to offset 0 and asks. It sends `view` (`v` + its index among the document's `qv-select-view` elements when first rendered). **Until Task 8** it also keeps today's trigger (ask again when `params-results` names its query or names none) for a host that sends no `uses`.

- [ ] **Step 1: Write the failing tests** in `pageRunner.test.ts`, driving `createPageRunner` with a fake transport that records requests:

```ts
test('load is one call with resolve all, the own queries and each widget tag')
test('a failing own query fails the load with its name')
test('a widget asking for its preloaded first page costs no call')
test('paging a widget asks for that one query and replaces the view')
test('a param change is one call: the reached params, the queries that use them, widgets at offset 0')
test('a query that uses no changed param is not asked')
test('a dependent param whose value changed costs exactly one more call')
test('a failing own query on a re-run keeps its previous columns and reports the message')
test('a failed call keeps the state, reports the message and answers waiting widgets')   // Review Focus 3
test('an older reply does not overwrite a newer one')                                     // Review Focus 1
test('after dispose a late reply posts nothing')                                          // Review Focus 4
test('rerun bumps revs for the named queries and posts them in params-results')
test('describe is answered from the view, and csv is not kept')
```

Add to `srcDoc.test.ts`: `window.uses` is written, escaped like the rest; to `widgetChannel.test.ts`: a `widget-query` without `view` is rejected, one with `view` parses.

- [ ] **Step 2: Run:** `npm test -w frontend -- pageRunner srcDoc widgetChannel`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test -w frontend`, `npm run lint -w frontend`, `npm run build:e2e -w frontend`, then `npx playwright test --trace off e2e/dashboard.spec.ts e2e/widgets.spec.ts e2e/server.spec.ts`. Expected: all pass; the pages still use the old path and widgets fall back to today's trigger.
- [ ] **Step 5: Commit** `Core: the page runner, and widgets that re-run on their inputs`.

### Task 6: The app's dashboard page

**Files:**
- Modify: `frontend/src/app/DashboardView.tsx`, `frontend/src/app/DashboardSqlPanel.tsx`, `frontend/src/app/widgetHost.ts`
- Test: `e2e/dashboard.spec.ts`, `e2e/widgets.spec.ts`

**Interfaces:**
- Consumes: `usePageRunner`, `Transport`, `RunRequest`, `RunReply` (Tasks 4 and 5); `POST /api/run` (Task 3).
- Produces: nothing new for later tasks.

What changes:
- The transport posts `{...request, sql: executedRef.current, params: active.params ?? []}` to `/api/run`. A `409` maps to the existing `runError` wording; a network failure is `{ok: false, message: 'Failed to run queries.'}`. A reply's `warning` is shown through `setError`, as today.
- `own` is the executed query names without those `widgetQueryNames(html)` owns. `loadKey` is built from the dashboard name, `runOn`, `reloadNonce` and the local push identity, so each reason for a reload today still reloads.
- `frames` is `[{id: 'page', frame: frameRef.current}, {id: 'popup', frame: popupFrameRef.current}]`.
- Execute calls `rerun(changedNames)`, or `rerun(null)` when nothing was edited.
- Removed from the file: `runDashboard`, `RunReply`, `withoutWidgetQueries`, `rerun`/`rerunNow`/`rerunQueue`, the `post` widget transport, `resolvedRef`, `shownRef`, and the load effect's run. `sharedPost` is deleted from `widgetHost.ts`.
- `DashboardFrame` is passed `uses`.

- [ ] **Step 1: Add the failing e2e tests** (both count requests with `page.on('request')` filtered to `/api/run`):

```ts
// widgets.spec.ts
test('opening a dashboard with two table widgets is one run call')
test('a param change re-runs only the widget that uses it')   // two widgets; assert the second call's body names one query, and the other table's rows are untouched
```

- [ ] **Step 2: Run them:** `npx playwright test --trace off e2e/widgets.spec.ts -g "one run call|only the widget"`. Expected: FAIL (the page still calls `/api/runqueries`).
- [ ] **Step 3: Migrate the page as listed.** Update any e2e route interception that names `/api/runqueries`, `/api/db/query` or `/api/db/describe` for a dashboard widget to `/api/run`; assertions stay as they are. Explorer and query-page specs are not touched.
- [ ] **Step 4: Run** `npm run lint -w frontend && npm test -w frontend && npm run e2e`. Expected: all pass.
- [ ] **Step 5: Commit** `Dashboard page: one run call, re-running only what a change reaches`.

### Task 7: The viewer server and its page

**Files:**
- Modify: `backend/queryview/server/main.py`, `frontend/src/viewer/ViewerApp.tsx`
- Test: `backend/queryview/server/test_main.py`, `e2e/server.spec.ts`

**Interfaces:**
- Consumes: `run_page`, `parse_asks`, `parse_resolve`, `clean_values` (Task 2); `usePageRunner` (Task 5).
- Produces: nothing new.

What changes:
- `POST /api/run` on the viewer server takes `{connection, dashboard, queries: [{name, …}], resolve?, values?}` and calls `run_page((driver, conn.config, conn.database), dash["queries"], dash["params"], …)`. Statuses: `404` unknown connection, dashboard or query; `400` malformed body or `reason: params`; `200` otherwise. No `warning`: the viewer server stays silent about a malformed param.
- `/api/query`, `/api/describe` and `_widget_sql` are deleted.
- `ViewerApp`'s transport posts `{...request, connection, dashboard}` to `/api/run`; a `404` sets the page error as today. `own` is `dash.queries` without the widget-owned names; `loadKey` is `connection + dashboard`; one frame, `id: 'page'`. The load effect's run, `resolvedRef`, `shownResultsRef` and the hand-written `onSetParams`/`onWidget` go.

- [ ] **Step 1: Rewrite the affected tests in `server/test_main.py` to the new shape and add:**

```python
def test_run_pages_and_sorts_one_query(client)                     # replaces test_query_pages_and_sorts
def test_run_csv(client)                                           # replaces test_query_csv
def test_run_returns_uses_and_no_sql(client)                       # "SELECT" not in r.text
def test_a_widget_page_runs_only_the_options_its_query_needs(...)  # same counts, through /api/run
def test_query_and_describe_routes_are_gone(client)                # 404
```

Keep every security test (`a value outside the options never reaches the sql`, `a param declared twice…`, hostile values, hostile order-by now a per-query failure) passing through `/api/run`.

- [ ] **Step 2: Run:** `uv run --group test pytest backend/queryview/server -q`. Expected: FAIL on the new shape.
- [ ] **Step 3: Implement the route and migrate `ViewerApp`.**
- [ ] **Step 4: Run** the backend suite, ruff, `npm run lint -w frontend`, `npm test -w frontend`, `npm run e2e`. Expected: all pass.
- [ ] **Step 5: Commit** `Viewer server: the shared run, and a page on the page runner`.

### Task 8: Remove the old paths, and the docs

**Files:**
- Modify: `backend/queryview/app.py`, `backend/queryview/dashboard_queries.py`, their tests; `frontend/src/core/widgets/SelectView.tsx`, `frameChannel.ts`, `frontend/src/core/dashboard/frameHost.ts` (+ test); `docs/architecture/api.md`, `docs/architecture/viewer_server_api.md`, `docs/user_guide/dashboard.md`
- Delete: `docs/superpowers/specs/2026-11-24-one-run-per-page-design.md`, this plan

What goes:
- App: the `/api/runqueries` route; `_with_params` and the `params`/`values` handling in `/api/db/query` and `/api/db/describe`.
- `dashboard_queries.py`: `run_dashboard`, `run_dashboard_on`, `run_dashboard_queries`, `run_queries_on`, `session_sql`, `ready_sql`, `resolved_part`, and anything left with no caller. Grep each name across `backend/` before deleting; `rows_to_columns` in `drivers/base.py` goes too if nothing else uses it.
- Tests of the removed functions and routes: port any behaviour not already covered by Tasks 2, 3 and 7 to `run_page` / `/api/run`, then delete the rest.
- Frontend: `SelectView`'s legacy trigger and `onParamsResults`' query list if unused; `answerWidget`, `widgetPage` and `WidgetPost` in `frameHost.ts` if the page runner replaced them.
- Docs: `/api/run` replaces `/api/runqueries` in `api.md` (also drop `params`/`values` from the `/api/db/query` and `/api/db/describe` rows); `viewer_server/api.md` drops `/api/query` and `/api/describe`; `dashboard.md`'s "Running the queries" and Widgets sections describe the one call and that a change re-runs only what uses it. Grep `docs/` and code comments for `runqueries` and the old heading text, and fix back-links.

- [ ] **Step 1: Add the failing tests:** `test_runqueries_route_is_gone` (404) in `test_dashboards.py`; in `test_api_db.py`, `/api/db/query` with `params` in the body runs the query text as written.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Remove the code, update the docs, delete the spec and this plan.** Run the `devpowers:shortify` pass on the docs touched.
- [ ] **Step 4: Run** the backend suite, ruff, `npm run lint -w frontend`, `npm test -w frontend`, `npm run e2e`, and `grep -rn "runqueries" backend frontend/src e2e docs` (expected: no match). All pass.
- [ ] **Step 5: Commit** `Remove the per-widget dashboard endpoints; docs for /api/run`.
