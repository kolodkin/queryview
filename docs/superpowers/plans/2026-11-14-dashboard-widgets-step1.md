# Dashboard Widgets, Step 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `<qv-select-view>` and `<qv-param>` work inside dashboard HTML, and
`/dashboard` gains an app-side SQL panel and a **New query** draft. Studio is
untouched.

**Architecture:** The tags are React components built into one classic-script
bundle (`/widgets.js`) that the frame prologue loads when the HTML contains
`<qv-`. Each tag mounts in a shadow root and talks to the app over
`postMessage`, sending a query name and values only; `DashboardView` answers by
running the dashboard's own SQL through the existing `/api/db/query` and
`/api/db/describe`.

**Tech Stack:** React 19, TypeScript, Vite 8 (second config in lib/IIFE mode),
Tailwind 4, vitest, Playwright. No new dependency. No backend change.

**Spec:** `docs/superpowers/specs/2026-11-13-dashboard-widgets-design.md`.
This plan covers its build step 1. Step 2 (migration, Studio removal) gets its
own plan once this ships.

## Global Constraints

- The frame sends values only: a declared query name, `limit`, `offset`,
  order-by columns, param values. Never SQL.
- The host answers only messages whose `source` is its own frame.
- Sandbox is exactly `allow-scripts allow-popups allow-popups-to-escape-sandbox`.
- `src/core` never fetches or imports `src/app` (lint-enforced).
- Dashboards without `<qv-` render byte-for-byte as before (no bundle tag).
- No `__all__`; run Python with `uv run`; example data uses invented names.
- Commit messages carry no AI attribution trailer.
- Load the project `testing` skill before writing a test, and `docs-writing`
  before editing `docs/`.

## Review Focus

1. Tag children parse after the tag upgrades: a `<template column>` written
   inside `<qv-select-view>` must still apply. (Task 2, e2e in Task 3.)
2. Pickers live in a shadow root: clicking inside the **Select fields**
   dropdown must not count as an outside click and close it. (Task 3.)
3. `query="missing"` names no dashboard query: the widget shows
   `Unknown query “missing”` and nothing runs. (Task 3.)
4. A forged message (`limit: "x"`, `limit: 99999`, `dir: "; DROP"`): rejected
   before any request. (Task 1.)
5. A slow reply for page 1 arrives after page 2 was requested: ignored, page 2
   stays. (Task 3.)

---

### Task 1: Pure widget logic

**Files:**
- Create: `frontend/src/core/dashboard/widgetChannel.ts`, `frontend/src/core/dashboard/widgetChannel.test.ts`
- Create: `frontend/src/core/cells/cellTemplate.ts`, `frontend/src/core/cells/cellTemplate.test.ts`
- Modify: `frontend/src/core/index.ts` (export the names below)

**Interfaces — Produces:**

```ts
// widgetChannel.ts
export type WidgetRequest =
  | { type: 'widget-query'; id: string; query: string; limit: number; offset: number; orderBy: OrderCol[] }
  | { type: 'widget-describe'; id: string; query: string }
  | { type: 'widget-csv'; query: string; limit: number; offset: number; orderBy: OrderCol[] }
export type WidgetReply =
  | { type: 'widget-result'; id: string; ok: true; meta: ColumnMeta[]; data: Cell[][] }
  | { type: 'widget-result'; id: string; ok: false; message: string }
  | { type: 'widget-fields'; id: string; ok: true; fields: Field[] }
  | { type: 'widget-fields'; id: string; ok: false; message: string }
export function parseWidgetRequest(data: unknown): WidgetRequest | null
export function widgetQueryNames(html: string): string[]      // distinct, in order
export function parseOrderByAttr(attr: string | null): OrderCol[]
export function parseFieldsAttr(attr: string | null): string[]
// cellTemplate.ts
export function renderCellTemplate(template: string, raw: string, row: string[], columns: string[]): string
```

The wire shape of `orderBy` is `order_by: [{name, dir}]`; `parseWidgetRequest`
maps it. `limit` must be an integer 1..1000, `offset` an integer ≥ 0, `dir`
exactly `ASC` or `DESC`; anything else returns `null`.

- [ ] **Step 1: Write the failing tests**

```ts
// widgetChannel.test.ts
it('accepts a well-formed widget-query', () => {
  expect(parseWidgetRequest({ type: 'widget-query', id: 'a', query: 'sales', limit: 100, offset: 0,
    order_by: [{ name: 'day', dir: 'DESC' }] })).toEqual({ type: 'widget-query', id: 'a',
    query: 'sales', limit: 100, offset: 0, orderBy: [{ name: 'day', dir: 'DESC' }] })
})
it.each([
  { limit: 'x' }, { limit: 99999 }, { limit: 0 }, { offset: -1 }, { offset: 1.5 },
  { order_by: [{ name: 'day', dir: '; DROP' }] }, { query: 7 }, { id: undefined },
  { sql: 'select 1', query: undefined },
])('rejects %o', (bad) => {
  expect(parseWidgetRequest({ type: 'widget-query', id: 'a', query: 'sales', limit: 100, offset: 0,
    order_by: [], ...bad })).toBeNull()
})
it('ignores other messages', () => {
  expect(parseWidgetRequest({ type: 'set-params', values: {} })).toBeNull()
  expect(parseWidgetRequest(null)).toBeNull()
})
it('finds the queries widgets own', () => {
  const html = `<qv-select-view query="sales"></qv-select-view><p>x</p>
    <qv-select-view limit="5" query='top'></qv-select-view><qv-select-view query="sales">`
  expect(widgetQueryNames(html)).toEqual(['sales', 'top'])
  expect(widgetQueryNames('<canvas id="c"></canvas>')).toEqual([])
})
it('parses presentation attributes', () => {
  expect(parseOrderByAttr('day desc, name')).toEqual([{ name: 'day', dir: 'DESC' }, { name: 'name', dir: 'ASC' }])
  expect(parseOrderByAttr(null)).toEqual([])
  expect(parseFieldsAttr(' day, revenue ')).toEqual(['day', 'revenue'])
  expect(parseFieldsAttr('')).toEqual([])
})

// cellTemplate.test.ts
const cols = ['id', 'name']
it('escapes substituted values as HTML', () => {
  expect(renderCellTemplate('<strong>{cell}</strong>', '<b>&', ['1', '<b>&'], cols))
    .toBe('<strong>&lt;b&gt;&amp;</strong>')
})
it('URL-encodes inside href and src', () => {
  expect(renderCellTemplate('<a href="https://example.internal/i/{row.id}?q={cell}">{cell}</a>',
    'a b', ['1/2', 'a b'], cols))
    .toBe('<a href="https://example.internal/i/1%2F2?q=a%20b">a b</a>')
})
it('is single pass and keeps unknown columns', () => {
  expect(renderCellTemplate('{cell} {row.nope}', '{row.id}', ['1', '{row.id}'], cols))
    .toBe('{row.id} {row.nope}')
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -w frontend -- widgetChannel cellTemplate`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement**

`renderCellTemplate` reuses `substituteCellTemplate` and `escapeHtml` from
`./cellView`: first substitute inside each `href="…"` / `src="…"` attribute
value with `encodeURIComponent`, then the rest with `escapeHtml`. Both passes
read the original row, so a value is never re-resolved.

- [ ] **Step 4: Run to verify they pass**

Run: `npm test -w frontend -- widgetChannel cellTemplate && npm run lint -w frontend`
Expected: PASS, lint clean.

- [ ] **Step 5: Commit** — `git commit -m "Widget channel parsing and cell templates"`

---

### Task 2: The widget bundle and `<qv-param>`

**Files:**
- Create: `frontend/vite.widgets.config.ts`, `frontend/src/widgets.tsx`
- Create: `frontend/src/core/widgets/ParamSelect.tsx`, `frontend/src/core/widgets/mount.ts`
- Modify: `frontend/package.json` (`build`), `frontend/vite.config.ts` (dev proxy)
- Modify: `frontend/src/core/dashboard/srcDoc.ts`, `srcDoc.test.ts`, `DashboardFrame.tsx`
- Test: `e2e/widgets.spec.ts`

**Interfaces:**
- Produces: `buildSrcDoc(html, results, params = [], widgetsSrc = '/widgets.js')`;
  `defineWidget(tag: string, render: (host: HTMLElement) => React.ReactNode): void`
  in `mount.ts`; `dist/widgets.js`.

Decisions:
- `vite.widgets.config.ts`: `build.lib` with `entry: 'src/widgets.tsx'`,
  `formats: ['iife']`, `name: 'QvWidgets'`, `fileName: () => 'widgets.js'`,
  `outDir: 'dist'`, `emptyOutDir: false`, plus
  `define: { 'process.env.NODE_ENV': '"production"' }` and the same plugins.
  A classic script, because a module script would need CORS from the frame's
  opaque origin.
- `build` becomes `tsc -b && vite build && vite build -c vite.widgets.config.ts`.
  The dev server proxies `/widgets.js` to `http://localhost:8000`.
- `mount.ts`: `defineWidget` registers a custom element that attaches an open
  shadow root, adds a `<style>` holding `index.css` imported with `?inline`,
  and mounts a React root. It mounts on `DOMContentLoaded` when the document
  is still loading, so children are parsed first (Review Focus 1).
- `buildSrcDoc` appends `<script src="${widgetsSrc}"></script>` after the
  prologue only when `html` contains `<qv-`.
- `ParamSelect`: reads `window.params`; a `<select data-testid="qv-param">`
  per param (a checkbox for `dimension`). On change it calls
  `window.setParams` with **every** param's current value (the host
  re-defaults omitted ones), and re-reads `window.params` on each
  `params-results` message.

- [ ] **Step 1: Write the failing tests**

```ts
// srcDoc.test.ts
it('loads the widget bundle only for dashboards that use a tag', () => {
  expect(buildSrcDoc('<qv-param name="r"></qv-param>', {})).toContain('<script src="/widgets.js"></script>')
  expect(buildSrcDoc('<canvas></canvas>', {})).not.toContain('widgets.js')
})
```

```ts
// e2e/widgets.spec.ts — model the push on "dashboard params resolve and
// rerun through setParams" in dashboard.spec.ts
test("qv-param reruns the dashboard", async ({ page, seeds, baseURL }) => {
  // push: html `<qv-param name="pick"></qv-param><div id="out"></div><script>
  //   const show = () => out.textContent = window.queries.q.name.join(',');
  //   show(); window.onQueryResults = show</script>`,
  // params [{name:'pick', options_sql:'SELECT name FROM items ORDER BY id'}],
  // queries {q: "SELECT name FROM items WHERE name = {pick}"}
  const frame = page.frameLocator('[data-testid="dashboard-frame"]')
  await expect(frame.locator('#out')).toHaveText(FIRST_ITEM)
  await frame.getByTestId('qv-param').selectOption(SECOND_ITEM)
  await expect(frame.locator('#out')).toHaveText(SECOND_ITEM)
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -w frontend -- srcDoc` → FAIL. `npm run e2e -- widgets` → FAIL
(no `qv-param` element; start databases with the `claudeai-run` skill first).

- [ ] **Step 3: Implement** the files above; set the sandbox attribute in
  `DashboardFrame.tsx` to the Global Constraints value.

- [ ] **Step 4: Run to verify they pass**

Run: `npm test -w frontend && npm run lint -w frontend && npm run e2e -- widgets dashboard`
Expected: PASS; `frontend/dist/widgets.js` exists; `dashboard.spec.ts` still green.

- [ ] **Step 5: Commit** — `git commit -m "Widget bundle, qv-param, sandbox popups"`

---

### Task 3: `<qv-select-view>` and the host channel

**Files:**
- Create: `frontend/src/core/widgets/SelectView.tsx`, `frontend/src/core/widgets/frameChannel.ts`
- Create: `frontend/src/app/widgetHost.ts`
- Modify: `frontend/src/widgets.tsx`, `frontend/src/app/DashboardView.tsx`, `frontend/src/core/useDismiss.ts`
- Test: `e2e/widgets.spec.ts`

**Interfaces:**
- Consumes: Task 1's types and parsers, Task 2's `defineWidget`.
- Produces:

```ts
// frameChannel.ts (runs in the frame)
export function requestHost<R extends WidgetReply>(msg: object): Promise<R>   // adds id, resolves on the reply with that id
export function onParamsResults(fn: () => void): () => void
// widgetHost.ts (runs in the app)
export async function answerWidget(
  req: WidgetRequest,
  sqlFor: (query: string) => string | null,   // substituted SQL, or null when not declared
): Promise<WidgetReply | null>                // null for widget-csv (it downloads)
```

Decisions:
- `SelectView` props: `query`, `limit` (default `100`), `orderBy`, `fields`,
  `templates: Record<string, string>`. The element reads `query`, `limit`,
  `order-by`, `fields` attributes and its `:scope > template[column]`
  children's `innerHTML`.
- It reuses `ResultsTable`, `FieldPickers`, `shownColumnIndices` and the
  default complex-cell rendering. A column with a template renders
  `<span data-testid="cell-<col>" dangerouslySetInnerHTML>` from
  `renderCellTemplate`; other columns render as Studio's do with no cell view.
- Test ids: root `qv-select-view`, table `qv-results`, `qv-prev`, `qv-next`,
  `qv-limit`, `qv-offset`, `qv-fields`, `qv-csv`, error `qv-error`.
- It queries on mount, on paging / order-by change, and at offset 0 on
  `params-results`. It keeps only the reply to its latest request (Review
  Focus 5).
- `answerWidget`: `sqlFor` null → `{ok: false, message: 'Unknown query “<name>”'}`;
  empty SQL → `{ok: false, message: 'Enter a query.'}`; neither calls the API.
  Otherwise `POST /api/db/query` (`{query, limit, offset, order_by}`) or
  `/api/db/describe`; `widget-csv` adds `format: 'csv'` and calls
  `downloadText('query.csv', output, 'text/csv')` from `./yamlio`.
- `DashboardView`: the message handler tries `parseWidgetRequest` next to
  `parseParamsRequest` (same `e.source` check) and posts the reply. `sqlFor`
  substitutes the **current** resolved params (keep them in a ref, updated at
  load and on every `set-params`) via `applyToQueries`. Both the load and the
  `set-params` path drop `widgetQueryNames(active.html)` from the up-front
  `/api/runqueries` map.
- `useDismiss`: test `e.composedPath().includes(el)` instead of
  `el.contains(e.target)`, so it works across a shadow boundary (Review Focus 2).

- [ ] **Step 1: Write the failing e2e tests** in `e2e/widgets.spec.ts`

```ts
test("qv-select-view pages a query", ...)
// html `<qv-select-view query="q" limit="2" order-by="id"></qv-select-view>`,
// queries {q: "SELECT id, name FROM items"}: 2 rows in qv-results;
// qv-next shows the next 2; qv-prev is disabled at offset 0.
test("a cell template designs a column", ...)
// `<template column="name"><a href="https://example.internal/i/{row.id}">{cell}</a></template>`
// → frame.getByTestId('cell-name').first() has that href and the name as text.
test("a widget query error stays in the widget", ...)
// queries {q: "SELECT * FROM no_such_table"}: qv-error is visible,
// page.getByTestId('dashboard-error') has count 0, the frame is rendered.
test("an unknown query name runs nothing", ...)
// query="missing" → qv-error has text 'Unknown query “missing”'.
test("the fields picker stays open on an inside click", ...)
// click qv-fields, open Select fields, toggle one column: the dropdown is
// still visible and that column left qv-results.
test("a widget query is not in window.queries", ...)
// html adds `<div id="keys"></div><script>keys.textContent =
//   Object.keys(window.queries).join(',')</script>`, queries {q, other}:
// #keys has text 'other'.
```

- [ ] **Step 2: Run to verify they fail** — `npm run e2e -- widgets`; FAIL, no `qv-select-view`.

- [ ] **Step 3: Implement** the files above.

- [ ] **Step 4: Run to verify they pass**

Run: `npm test -w frontend && npm run lint -w frontend && npm run e2e`
Expected: PASS, whole suite (the `useDismiss` change touches Studio and the explorer).

- [ ] **Step 5: Commit** — `git commit -m "qv-select-view and the widget host channel"`

---

### Task 4: SQL panel and New query

**Files:**
- Create: `frontend/src/app/DashboardSqlPanel.tsx`
- Modify: `frontend/src/app/DashboardView.tsx`, `frontend/src/app/App.tsx` (pass `remoteId`)
- Test: `e2e/widgets.spec.ts`

**Interfaces — Produces:**

```ts
function DashboardSqlPanel(props: {
  queries: Record<string, string>
  onChange: (name: string, sql: string) => void
  onExecute: () => void
  remoteId: string | null
}): JSX.Element
```

Decisions:
- Panel: a query `<select data-testid="dash-sql-query">`, the size buttons
  from `TEXTAREA_SIZES` / `textareaSizeClass`, `<textarea data-testid="dash-sql">`,
  **Execute** (`dash-sql-execute`). `useEditLock(panelRef, remoteId)` gives it
  the human edit lock.
- `DashboardView` adds **Edit queries** (`dashboard-edit-queries`, toggles the
  panel, disabled without an active dashboard) and **New query**
  (`dashboard-new-query`).
- `onChange` updates `active.queries` in state. **Save** already persists
  `active`, so an edited query saves with it.
- **Execute** does not rebuild the frame: it re-runs the non-widget queries
  with the current params and posts the existing `params-results` message,
  which also makes widgets re-query.
- **New query** clears `?name` and sets the local push to
  `{name: '', html: '<qv-select-view query="main"></qv-select-view>', queries: {main: ''}, params: []}`
  with the panel open. **Save** then prompts for a name, as for any unnamed draft.

- [ ] **Step 1: Write the failing e2e tests**

```ts
test("New query runs ad-hoc SQL and saves as a dashboard", ...)
// click dashboard-new-query; qv-error shows 'Enter a query.'; fill dash-sql with
// "SELECT name FROM items ORDER BY id", click dash-sql-execute → qv-results
// lists the items. Accept the Save prompt with "scratch" → dashboard-select
// has value "scratch"; reload → the rows render again.
test("Execute keeps the page state", ...)
// html `<input id="keep"><qv-select-view query="q"></qv-select-view>`; type
// "x" in #keep, edit dash-sql, Execute → #keep still has value "x" and
// qv-results shows the new rows.
test("an agent push is blocked while the SQL panel has focus", ...)
// arm remote, focus dash-sql, push a dashboard through the REST mirror →
// message 'blocked, user editing' (the pattern in remote.spec.ts).
```

- [ ] **Step 2: Run to verify they fail** — `npm run e2e -- widgets`; FAIL, no `dashboard-new-query`.

- [ ] **Step 3: Implement** the files above.

- [ ] **Step 4: Run to verify they pass** — `npm run lint -w frontend && npm run e2e`; PASS.

- [ ] **Step 5: Commit** — `git commit -m "Dashboard SQL panel and New query draft"`

---

### Task 5: Docs and agent guidance

**Files:**
- Modify: `docs/dashboard.md`, `docs/api.md` only if it lists frame messages
- Modify: `backend/queryview/skills/queryview/SKILL.md`, the `push_dashboard`
  docstring in `backend/queryview/mcp_server.py`
- Test: `backend/queryview/test_mcp_skills.py` if it pins skill text

- [ ] **Step 1:** In `docs/dashboard.md` add `## Widgets` (the two tags, their
  attributes, `<template column>`, the value-only channel), add the SQL panel
  and **New query** to "The page", and correct "Isolation & security" for the
  new sandbox flags and for widget queries being absent from `window.queries`.
  Present tense, per `docs-writing`; finish with `devpowers:shortify`.
- [ ] **Step 2:** In the skill text and the docstring, add the tag reference
  in at most ten lines, with the example from the spec's "Tags" section.
- [ ] **Step 3:** Run `uv run --group test pytest backend/queryview -q`; PASS.
- [ ] **Step 4: Commit** — `git commit -m "Document dashboard widgets"`
